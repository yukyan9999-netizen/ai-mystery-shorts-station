from __future__ import annotations

import base64
import json
import math
import re
import subprocess
import wave
from array import array
from difflib import SequenceMatcher
from pathlib import Path
from textwrap import wrap
from typing import Any

import imageio_ffmpeg
import yaml
from agents import Agent, ModelSettings, Runner
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.models import FinalEpisode, VideoAssets, VoiceCastPlan
from src.progress import heartbeat


class VideoStudio:
    def __init__(self, root: Path, live: bool = False) -> None:
        self.root = root.resolve()
        self.live = live
        load_dotenv(self.root / ".env")
        load_dotenv(self.root / ".env.local", override=True)
        config = yaml.safe_load((self.root / "config.yaml").read_text(encoding="utf-8"))
        self.model = str(config.get("model", "gpt-5-mini"))
        self.config: dict[str, Any] = config["video_studio"]
        self.heartbeat_seconds = float(config.get("heartbeat_seconds", 10))
        self.client = OpenAI()
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def _say(self, message: str) -> None:
        if self.live:
            print(f"[영상제작실] {message}", flush=True)

    def _agent_state(self, role: str, state: str) -> None:
        if self.live:
            print(
                "@@AGENT_STATE@@"
                + json.dumps({"role": role, "state": state}, ensure_ascii=False),
                flush=True,
            )

    def _agent_progress(self, role: str, percent: int, message: str) -> None:
        if self.live:
            print(
                "@@AGENT_PROGRESS@@"
                + json.dumps(
                    {
                        "role": role,
                        "percent": max(0, min(100, int(percent))),
                        "message": message,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    def _load_episode(self, run_id: str) -> tuple[Path, FinalEpisode]:
        final_dir = self.root / "outputs" / "final" / run_id
        episode_path = final_dir / "final_episode.json"
        if not episode_path.exists():
            raise FileNotFoundError(f"final_episode.json을 찾을 수 없습니다: {episode_path}")
        episode = FinalEpisode.model_validate_json(episode_path.read_text(encoding="utf-8"))
        allowed_conditional = (
            episode.completion_status == "conditional_after_revision_limit"
            and episode.mandatory_human_review
        )
        if episode.compliance_review.verdict != "pass" and not allowed_conditional:
            raise RuntimeError(
                "심의를 통과하거나 최대 수정 후 조건부 완성된 에피소드만 영상으로 제작할 수 있습니다."
            )
        return final_dir, episode

    def _character_prompt(self, episode: FinalEpisode) -> str:
        character = episode.character_direction
        return (
            f"Character lock: {character.protagonist_profile}. "
            f"Visual identity: {character.visual_identity}. "
            f"Personality: {character.personality}. "
            f"Consistency token: {character.consistency_token}."
        )

    def _panel_prompt(self, episode: FinalEpisode, panel_number: int) -> str:
        panel_count = len(episode.story.panels)
        panel = next(p for p in episode.story.panels if p.panel_number == panel_number)
        performance = next(
            p
            for p in episode.character_direction.panel_performances
            if p.panel_number == panel_number
        )
        return f"""
Use case: illustration-story
Asset type: vertical Korean webtoon shorts panel {panel_number} of {panel_count}
Primary request: {panel.image_prompt}
Scene: {panel.scene}
Action: {panel.action}
Character: {self._character_prompt(episode)}
Performance: expression {performance.expression}; pose {performance.pose};
gaze {performance.gaze}; framing {performance.framing}
Style: polished original digital webtoon illustration, expressive comedy,
clean linework, cinematic lighting, readable silhouette
Composition: portrait 2:3, one clear focal action, safe margins for later captions
Constraints: fictional people only; preserve the exact same protagonist design,
hair, face, clothing, bag and color palette across all {panel_count} panels
Avoid: speech bubbles, captions, letters, logos, watermarks, flags used as jokes,
real public figures, copyrighted characters, stereotypes or cultural caricatures
""".strip()

    def _write_image(self, response: Any, path: Path) -> None:
        encoded = response.data[0].b64_json
        if not encoded:
            raise RuntimeError("이미지 API 응답에 이미지 데이터가 없습니다.")
        path.write_bytes(base64.b64decode(encoded))

    def generate_panel_images(
        self, final_dir: Path, episode: FinalEpisode, force: bool = False
    ) -> list[Path]:
        images_dir = final_dir / "panels"
        images_dir.mkdir(exist_ok=True)
        panel_count = len(episode.story.panels)
        paths = [
            images_dir / f"panel_{number:02d}.png"
            for number in range(1, panel_count + 1)
        ]
        reference = paths[0]

        for index, path in enumerate(paths, start=1):
            if path.exists() and not force:
                self._say(f"{path.name} 재사용")
                percent = 10 + round(index / panel_count * 32)
                self._agent_progress(
                    "VideoRenderer", percent,
                    f"{index}컷 이미지는 이미 준비됐어요. 영상 작업 {percent}%입니다.",
                )
                continue
            self._say(f"{index}컷 이미지 생성 중")
            percent = 8 + round((index - 0.5) / panel_count * 32)
            self._agent_progress(
                "VideoRenderer", percent,
                f"{index}컷 이미지를 만들고 있어요. 영상 작업 {percent}%입니다.",
            )
            prompt = self._panel_prompt(episode, index)
            with heartbeat(
                self.live,
                f"{index}컷 이미지 생성",
                self.heartbeat_seconds,
                writer=self._say,
            ):
                if index == 1 or not reference.exists():
                    response = self.client.images.generate(
                        model=self.config["image_model"],
                        prompt=prompt,
                        size=self.config["image_size"],
                        quality=self.config["image_quality"],
                        output_format="png",
                    )
                else:
                    with reference.open("rb") as image_file:
                        response = self.client.images.edit(
                            model=self.config["image_model"],
                            image=image_file,
                            prompt=(
                                "Use the supplied first-panel image only as the definitive "
                                "character design reference. Create a new scene for the requested "
                                "panel while preserving the protagonist exactly.\n\n" + prompt
                            ),
                            size=self.config["image_size"],
                            quality=self.config["image_quality"],
                            output_format="png",
                        )
            self._write_image(response, path)
            percent = 10 + round(index / panel_count * 32)
            self._agent_progress(
                "VideoRenderer", percent,
                f"{index}컷 이미지 완료. 영상 작업 {percent}%예요.",
            )
        return paths

    def _font(self, bold: bool, size: int) -> ImageFont.FreeTypeFont:
        key = "bold_font_path" if bold else "font_path"
        return ImageFont.truetype(self.config[key], size=size)

    @staticmethod
    def _fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
        return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)

    def _draw_centered_lines(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        y: int,
        font: ImageFont.FreeTypeFont,
        max_chars: int,
        fill: str,
        stroke_width: int = 0,
        stroke_fill: str = "black",
    ) -> int:
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            lines.extend(wrap(paragraph, width=max_chars) or [""])
        spacing = int(font.size * 0.35)
        for line in lines:
            box = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
            x = (int(self.config["width"]) - (box[2] - box[0])) // 2
            draw.text(
                (x, y),
                line,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            y += (box[3] - box[1]) + spacing
        return y

    @staticmethod
    def _clean_screen_text(text: str) -> str:
        """Keep only viewer-facing dialogue; remove production notes and disclosures."""
        cleaned = str(text or "")
        cleaned = re.sub(r"\[(?:FICT|FICTION|창작|허구)[^\]]*\]", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\((?:상상|속|독백|점포 정책에 따름|확인 필요|연출|효과음|장면)[^)]*\)", "", cleaned)
        cleaned = re.sub(r"（(?:상상|속|독백|점포 정책에 따름|확인 필요|연출|효과음|장면)[^）]*）", "", cleaned)
        cleaned = re.sub(
            r"(?:본 작품|이 작품|이 영상)[^.?!]*(?:허구|창작|실제와 다를 수)[^.?!]*[.?!]?",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—·")
        return cleaned

    def _viewer_caption(self, episode: FinalEpisode, panel_number: int) -> str:
        beat = next(
            b
            for b in episode.shorts_editing_guide.beats
            if b.panel_number == panel_number
        )
        caption = self._clean_screen_text(beat.subtitle)
        if caption:
            return caption
        panel = next(p for p in episode.story.panels if p.panel_number == panel_number)
        for dialogue in panel.dialogue:
            dialogue = re.sub(r"^[^:]{1,14}:\s*", "", dialogue)
            dialogue = dialogue.strip().strip('"“”')
            caption = self._clean_screen_text(dialogue)
            if caption:
                return caption
        return self._clean_screen_text(panel.narration)

    def compose_frames(
        self, final_dir: Path, episode: FinalEpisode, images: list[Path]
    ) -> list[Path]:
        width = int(self.config["width"])
        height = int(self.config["height"])
        frames_dir = final_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        title_font = self._font(True, 55)
        subtitle_font = self._font(True, 62)
        frames: list[Path] = []

        for image_path, beat in zip(images, episode.shorts_editing_guide.beats):
            canvas = Image.new("RGB", (width, height), "#11131a")
            panel_image = self._fit_image(Image.open(image_path), (width, 1620))
            canvas.paste(panel_image, (0, 120))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((0, 0, width, 120), fill="#11131a")
            draw.text(
                (45, 28),
                f"{beat.panel_number} / {len(episode.story.panels)}",
                font=title_font,
                fill="#ffd84d",
            )
            draw.rounded_rectangle(
                (35, 1580, width - 35, height - 45),
                radius=34,
                fill=(10, 10, 14, 225),
            )
            self._draw_centered_lines(
                draw,
                self._viewer_caption(episode, beat.panel_number),
                1640,
                subtitle_font,
                max_chars=17,
                fill="white",
                stroke_width=3,
            )
            frame_path = frames_dir / f"frame_{beat.panel_number:02d}.png"
            canvas.save(frame_path, quality=95)
            frames.append(frame_path)
            self._agent_progress(
                "VideoRenderer",
                46 + beat.panel_number * 3,
                f"{beat.panel_number}컷 자막 프레임을 조립했습니다. 영상 작업 {46 + beat.panel_number * 3}%예요.",
            )
        return frames

    @staticmethod
    def _raw_speech_text(episode: FinalEpisode, panel_number: int) -> str:
        panel = next(p for p in episode.story.panels if p.panel_number == panel_number)
        parts = [panel.narration.strip(), *[line.strip() for line in panel.dialogue]]
        return " ".join(part for part in parts if part)

    def _speech_text(self, episode: FinalEpisode, panel_number: int) -> str:
        # Shorts audio should perform one concise viewer-facing line per panel.
        # Reading narration + every dialogue line caused rushed, unnatural speech.
        return self._viewer_caption(episode, panel_number)

    @staticmethod
    def _split_dialogue_line(line: str) -> tuple[str, str]:
        match = re.match(r'^\s*([^:：]{1,24})[:：]\s*(.+?)\s*$', str(line))
        if not match:
            return "", str(line).strip().strip('"“”')
        speaker = re.sub(r"\([^)]*\)|（[^）]*）", "", match.group(1)).strip()
        text = match.group(2).strip().strip('"“”')
        return speaker, text

    @staticmethod
    def _speaker_role(speaker: str) -> str:
        compact = speaker.replace(" ", "")
        if any(word in compact for word in ("주인공", "여행자", "나")):
            return "protagonist"
        if any(
            word in compact
            for word in ("직원", "점원", "기사", "승무원", "안내원", "경찰", "사장")
        ):
            return "staff"
        if any(word in compact for word in ("내레이션", "나레이션", "해설")):
            return "narrator"
        return "companion" if compact else "narrator"

    @staticmethod
    def _infer_unlabeled_speaker(text: str) -> str:
        compact = text.replace(" ", "")
        staff_markers = (
            "직원전용",
            "만지지마",
            "처리할게요",
            "확인해드릴",
            "도와드릴",
            "잠깐!",
            "고객님",
        )
        if any(marker in compact for marker in staff_markers):
            return "직원"
        return "주인공"

    def _speech_cue(
        self, episode: FinalEpisode, panel_number: int
    ) -> dict[str, str]:
        caption = self._viewer_caption(episode, panel_number)
        panel = next(p for p in episode.story.panels if p.panel_number == panel_number)
        best_speaker = ""
        best_text = caption
        best_score = 0.0
        for line in panel.dialogue:
            speaker, dialogue = self._split_dialogue_line(line)
            cleaned = self._clean_screen_text(dialogue)
            if not cleaned:
                continue
            score = SequenceMatcher(None, cleaned, caption).ratio()
            if cleaned in caption or caption in cleaned:
                score += 0.5
            if score > best_score:
                best_score = score
                best_speaker = speaker
                best_text = caption or cleaned
        if best_score < 0.45:
            best_speaker = "내레이션"
            best_text = caption
        elif not best_speaker:
            best_speaker = self._infer_unlabeled_speaker(best_text)

        role = self._speaker_role(best_speaker)
        cast = self.config.get("voice_cast", {})
        profile = cast.get(role) or cast.get("narrator") or {
            "voice": "marin",
            "direction": "",
        }
        base = str(self.config.get("speech_instructions", "")).strip()
        role_direction = str(profile.get("direction", "")).strip()
        return {
            "speaker": best_speaker or "내레이션",
            "role": role,
            "text": best_text,
            "voice": str(profile.get("voice", "marin")),
            "instructions": f"{base} {role_direction}".strip(),
        }

    def _voice_cast_plan(
        self, final_dir: Path, episode: FinalEpisode, force: bool = False
    ) -> tuple[VoiceCastPlan, bool]:
        audio_dir = final_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        path = audio_dir / "voice_cast_plan.json"
        if path.exists() and not force:
            plan = VoiceCastPlan.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            changed = False
            for line in plan.panel_lines:
                cleaned = self._clean_screen_text(line.spoken_text)
                if cleaned != line.spoken_text:
                    line.spoken_text = cleaned or self._viewer_caption(
                        episode, line.panel_number
                    )
                    changed = True
            if changed:
                path.write_text(
                    json.dumps(
                        plan.model_dump(mode="json"), ensure_ascii=False, indent=2
                    ),
                    encoding="utf-8",
                )
            return plan, False

        payload = {
            "characters": episode.story.characters,
            "protagonist_profile": episode.character_direction.protagonist_profile,
            "personality": episode.character_direction.personality,
            "panels": [
                {
                    "panel_number": panel.panel_number,
                    "scene": panel.scene,
                    "action": panel.action,
                    "dialogue": panel.dialogue,
                    "screen_caption": self._viewer_caption(
                        episode, panel.panel_number
                    ),
                }
                for panel in episode.story.panels
            ],
            "available_voices": [
                "alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
                "onyx", "sage", "shimmer", "verse", "marin", "cedar",
            ],
            "instruction": (
                "에피소드 전체를 보고 등장인물별 목소리를 자율적으로 캐스팅하세요. "
                "컷마다 화자 한 명과 실제로 읽을 짧은 문장 하나를 지정하세요."
            ),
        }
        settings = ModelSettings(
            reasoning={"effort": "low"}
            if self.model.startswith(("gpt-5", "o1", "o3", "o4"))
            else None,
            verbosity="low" if self.model.startswith("gpt-5") else None,
            max_tokens=3000,
        )
        agent = Agent(
            name="VoiceProducer",
            instructions=(self.root / "agents" / "VoiceProducer.md").read_text(
                encoding="utf-8"
            ),
            model=self.model,
            model_settings=settings,
            output_type=VoiceCastPlan,
        )
        self._agent_progress(
            "VoiceProducer", 3, "에피소드 전체를 읽고 등장인물별 목소리를 캐스팅하고 있어요."
        )
        result = Runner.run_sync(
            agent,
            json.dumps(payload, ensure_ascii=False, indent=2),
            max_turns=3,
        )
        plan = result.final_output
        if not isinstance(plan, VoiceCastPlan):
            plan = VoiceCastPlan.model_validate(plan)
        expected = {panel.panel_number for panel in episode.story.panels}
        received = {line.panel_number for line in plan.panel_lines}
        if received != expected:
            raise RuntimeError(
                "음성담당의 컷별 화자 배정이 스토리 컷 수와 일치하지 않습니다."
            )
        cast_names = {character.speaker_name for character in plan.cast}
        if any(line.speaker_name not in cast_names for line in plan.panel_lines):
            raise RuntimeError("음성담당이 캐스팅하지 않은 화자를 컷에 배정했습니다.")
        for line in plan.panel_lines:
            line.spoken_text = self._clean_screen_text(line.spoken_text)
            if not line.spoken_text:
                line.spoken_text = self._viewer_caption(episode, line.panel_number)
        path.write_text(
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.live:
            print(
                "@@AGENT_COMMENT@@"
                + json.dumps(
                    {
                        "role": "VoiceProducer",
                        "comment": plan.character_comment,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        return plan, True

    def generate_narration(
        self,
        final_dir: Path,
        episode: FinalEpisode,
        force: bool = False,
        recast: bool | None = None,
    ) -> list[Path]:
        audio_dir = final_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        files: list[Path] = []
        voice_cast_log: list[dict[str, Any]] = []
        self._agent_state("VoiceProducer", "working")
        panel_count = len(episode.story.panels)
        self._agent_progress(
            "VoiceProducer", 0,
            f"{panel_count}개 컷과 등장인물을 확인했습니다. 음성 제작을 시작해요.",
        )
        try:
            plan, plan_created = self._voice_cast_plan(
                final_dir,
                episode,
                force=force if recast is None else recast,
            )
        except Exception as exc:
            self._say(f"AI 음성 캐스팅 실패, 안전한 기본 캐스팅 사용: {exc}")
            fallback_cast: dict[str, dict[str, str]] = {}
            fallback_lines: list[dict[str, Any]] = []
            for beat in episode.shorts_editing_guide.beats:
                cue = self._speech_cue(episode, beat.panel_number)
                fallback_cast[cue["speaker"]] = {
                    "speaker_name": cue["speaker"],
                    "role": cue["role"],
                    "voice": cue["voice"],
                    "acting_direction": cue["instructions"],
                }
                fallback_lines.append(
                    {
                        "panel_number": beat.panel_number,
                        "speaker_name": cue["speaker"],
                        "spoken_text": cue["text"],
                        "emotion": "장면에 맞게 자연스럽게",
                    }
                )
            plan = VoiceCastPlan(
                character_comment="AI 캐스팅 오류로 장면 기반 기본 화자 구분을 적용했습니다.",
                cast=list(fallback_cast.values()),
                panel_lines=fallback_lines,
            )
            plan_created = True

        cast_by_name = {character.speaker_name: character for character in plan.cast}
        line_by_panel = {line.panel_number: line for line in plan.panel_lines}
        regenerate_audio = force or plan_created
        for index, beat in enumerate(episode.shorts_editing_guide.beats, start=1):
            path = audio_dir / f"panel_{beat.panel_number:02d}.wav"
            files.append(path)
            line = line_by_panel[beat.panel_number]
            character = cast_by_name[line.speaker_name]
            percent = round(index / panel_count * 100)
            if path.exists() and not regenerate_audio:
                self._say(f"{path.name} 재사용")
                self._agent_progress(
                    "VoiceProducer",
                    percent,
                    f"{beat.panel_number}컷 음성을 재사용합니다. 음성 제작 {percent}%예요.",
                )
                voice_cast_log.append(
                    {
                        "panel_number": beat.panel_number,
                        "speaker": character.speaker_name,
                        "role": character.role,
                        "voice": character.voice,
                        "text": line.spoken_text,
                        "emotion": line.emotion,
                    }
                )
                continue
            base = str(self.config.get("speech_instructions", "")).strip()
            instructions = (
                f"{base} 화자는 {character.speaker_name}이다. "
                f"{character.acting_direction} 현재 감정은 {line.emotion}."
            )
            voice_cast_log.append(
                {
                    "panel_number": beat.panel_number,
                    "speaker": character.speaker_name,
                    "role": character.role,
                    "voice": character.voice,
                    "text": line.spoken_text,
                    "emotion": line.emotion,
                }
            )
            self._say(
                f"{beat.panel_number}컷 {character.speaker_name} 음성 생성 중 "
                f"(voice={character.voice})"
            )
            self._agent_progress(
                "VoiceProducer",
                round((index - 1) / panel_count * 100),
                f"{beat.panel_number}컷은 ‘{character.speaker_name}’ 목소리로 연기합니다.",
            )
            with heartbeat(
                self.live,
                f"{beat.panel_number}컷 AI 음성",
                self.heartbeat_seconds,
                writer=self._say,
            ):
                with self.client.audio.speech.with_streaming_response.create(
                    model=self.config["speech_model"],
                    voice=character.voice,
                    input=line.spoken_text,
                    instructions=instructions,
                    response_format="wav",
                ) as response:
                    response.stream_to_file(path)
            self._agent_progress(
                "VoiceProducer",
                percent,
                f"{beat.panel_number}컷 목소리 완료. 음성 제작 {percent}%예요.",
            )
        (audio_dir / "voice_cast.json").write_text(
            json.dumps(voice_cast_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._agent_state("VoiceProducer", "idle")
        return files

    def generate_background_music(
        self, final_dir: Path, episode: FinalEpisode, force: bool = False
    ) -> Path:
        """Create a simple original instrumental bed locally; no third-party music is used."""
        audio_dir = final_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        path = audio_dir / "background_music.wav"
        self._agent_state("MusicProducer", "working")
        if path.exists() and not force:
            self._agent_progress(
                "MusicProducer", 100, "기존 자체 제작 BGM을 확인했습니다. 배경음악 100%예요."
            )
            self._agent_state("MusicProducer", "idle")
            return path

        self._agent_progress(
            "MusicProducer", 15, "저작권 문제 없는 자체 리듬을 설계 중입니다. 배경음악 15%예요."
        )
        duration = sum(
            float(beat.duration_seconds) for beat in episode.shorts_editing_guide.beats
        )
        sample_rate = 44_100
        total_samples = max(1, int(duration * sample_rate))
        notes = (261.63, 329.63, 392.00, 329.63, 293.66, 349.23, 440.00, 349.23)
        beat_seconds = 0.5
        samples = array("h")
        for sample_index in range(total_samples):
            t = sample_index / sample_rate
            note_index = int(t / beat_seconds) % len(notes)
            local_t = t % beat_seconds
            envelope = min(1.0, local_t / 0.025) * max(
                0.0, min(1.0, (beat_seconds - local_t) / 0.12)
            )
            tone = math.sin(2 * math.pi * notes[note_index] * t)
            bass = math.sin(2 * math.pi * (notes[note_index] / 2) * t)
            value = int(32767 * 0.11 * envelope * (0.72 * tone + 0.28 * bass))
            samples.append(value)
        self._agent_progress(
            "MusicProducer", 70, "멜로디와 리듬을 만들었습니다. 배경음악 70%예요."
        )
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(samples.tobytes())
        self._agent_progress(
            "MusicProducer", 100, "자체 제작 BGM 출력 완료. 배경음악 100%예요."
        )
        self._agent_state("MusicProducer", "idle")
        return path

    @staticmethod
    def _wav_duration(path: Path) -> float:
        with wave.open(str(path), "rb") as wav:
            header_duration = wav.getnframes() / float(wav.getframerate())
            bytes_per_second = (
                wav.getframerate() * wav.getnchannels() * wav.getsampwidth()
            )
        # Streaming WAV responses can leave a 0x7fffffff/0xffffffff data length
        # in the header. In that case the physical file size is authoritative.
        physical_duration = max(0, path.stat().st_size - 44) / bytes_per_second
        if header_duration > physical_duration * 2 or header_duration > 3600:
            return physical_duration
        return header_duration

    @staticmethod
    def _timestamp(seconds: float, srt: bool = True) -> str:
        millis = round(seconds * 1000)
        hours, millis = divmod(millis, 3_600_000)
        minutes, millis = divmod(millis, 60_000)
        secs, millis = divmod(millis, 1000)
        separator = "," if srt else "."
        return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"

    def write_subtitles(self, final_dir: Path, episode: FinalEpisode) -> Path:
        path = final_dir / "subtitles.srt"
        current = 0.0
        blocks: list[str] = []
        for index, beat in enumerate(episode.shorts_editing_guide.beats, start=1):
            start = current + beat.subtitle_in_seconds
            end = current + beat.duration_seconds
            blocks.append(
                f"{index}\n{self._timestamp(start)} --> {self._timestamp(end)}\n"
                f"{self._viewer_caption(episode, beat.panel_number)}\n"
            )
            current = end
        path.write_text("\n".join(blocks), encoding="utf-8-sig")
        return path

    @staticmethod
    def _atempo_chain(ratio: float) -> str:
        filters: list[str] = []
        while ratio > 2.0:
            filters.append("atempo=2.0")
            ratio /= 2.0
        filters.append(f"atempo={max(0.5, ratio):.5f}")
        return ",".join(filters)

    def _run_ffmpeg(self, args: list[str]) -> None:
        completed = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args],
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"FFmpeg 오류:\n{completed.stderr.strip()}")

    def render_video(
        self,
        final_dir: Path,
        episode: FinalEpisode,
        frames: list[Path],
        audio_files: list[Path],
        background_music: Path,
    ) -> Path:
        clips_dir = final_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        clip_paths: list[Path] = []
        fps = int(self.config["fps"])
        panel_count = len(episode.shorts_editing_guide.beats)
        for index, (frame, audio, beat) in enumerate(zip(
            frames, audio_files, episode.shorts_editing_guide.beats
        ), start=1):
            duration = float(beat.duration_seconds)
            audio_duration = self._wav_duration(audio)
            if audio_duration > duration - 0.35:
                self._say(
                    f"{beat.panel_number}컷 음성이 컷보다 깁니다. "
                    "속도를 억지로 올리지 않고 끝부분을 자연스럽게 정리합니다."
                )
            audio_filter = "volume=1.12"
            clip_path = clips_dir / f"clip_{beat.panel_number:02d}.mp4"
            frame_count = max(1, math.ceil(duration * fps))
            self._say(f"{beat.panel_number}컷 영상 합성 중")
            percent = 62 + round(index / panel_count * 30)
            self._agent_progress(
                "VideoRenderer",
                percent,
                f"{beat.panel_number}컷 영상과 목소리를 합성 중입니다. 영상 작업 {percent}%예요.",
            )
            self._run_ffmpeg(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(fps),
                    "-i",
                    str(frame),
                    "-i",
                    str(audio),
                    "-filter_complex",
                    (
                        f"[0:v]zoompan=z='min(zoom+0.00035,1.04)':"
                        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                        f"d={frame_count}:s={self.config['width']}x{self.config['height']}:"
                        f"fps={fps},format=yuv420p[v];"
                        f"[1:a]{audio_filter},apad,atrim=0:{duration:.3f}[a]"
                    ),
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-t",
                    f"{duration:.3f}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "19",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    str(clip_path),
                ]
            )
            clip_paths.append(clip_path)

        concat_file = clips_dir / "concat.txt"
        concat_file.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in clip_paths),
            encoding="utf-8",
        )
        final_video = final_dir / "final_short.mp4"
        narration_video = final_dir / "narration_short.mp4"
        self._say(f"{panel_count}개 컷을 최종 쇼츠로 연결 중")
        self._run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(narration_video),
            ]
        )
        self._agent_state("MusicProducer", "working")
        self._agent_progress(
            "MusicProducer", 90, "완성된 영상에 BGM 음량을 맞춰 섞고 있어요. 믹싱 90%예요."
        )
        self._run_ffmpeg(
            [
                "-i",
                str(narration_video),
                "-i",
                str(background_music),
                "-filter_complex",
                "[0:a]volume=1.0[voice];[1:a]volume=0.24[bgm];"
                "[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(final_video),
            ]
        )
        self._agent_progress(
            "MusicProducer", 100, "목소리를 방해하지 않게 BGM 믹싱 완료. 100%입니다."
        )
        self._agent_state("MusicProducer", "idle")
        self._agent_progress(
            "VideoRenderer", 100, "최종 쇼츠 출력 완료. 영상 작업 100%입니다."
        )
        return final_video

    def create_thumbnail(
        self, final_dir: Path, episode: FinalEpisode, image_path: Path
    ) -> Path:
        canvas = self._fit_image(Image.open(image_path), (1080, 1920))
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, 1080, 1920), fill=(0, 0, 0, 60))
        draw.rounded_rectangle((50, 1250, 1030, 1810), radius=50, fill=(0, 0, 0, 210))
        text = episode.youtube_package.thumbnail_text_candidates[0]
        self._draw_centered_lines(
            draw,
            text,
            1360,
            self._font(True, 105),
            max_chars=9,
            fill="#ffffff",
            stroke_width=5,
        )
        output = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        path = final_dir / "thumbnail.png"
        output.save(path, quality=95)
        return path

    def render(self, run_id: str, force: bool = False) -> Path:
        final_dir, episode = self._load_episode(run_id)
        manifest_path = final_dir / "render_manifest.json"
        self._agent_state("VideoRenderer", "working")
        self._agent_progress("VideoRenderer", 3, "콘티를 받았습니다. 영상 작업 3%에서 시작해요.")
        try:
            images = self.generate_panel_images(final_dir, episode, force=force)
            frames = self.compose_frames(final_dir, episode, images)
            audio = self.generate_narration(final_dir, episode, force=force)
            background_music = self.generate_background_music(
                final_dir, episode, force=force
            )
            subtitles = self.write_subtitles(final_dir, episode)
            thumbnail = self.create_thumbnail(final_dir, episode, images[-1])
            final_video = self.render_video(
                final_dir, episode, frames, audio, background_music
            )
            manifest = {
                "status": "rendered",
                "run_id": run_id,
                "panel_images": [str(path.relative_to(final_dir)) for path in images],
                "panel_frames": [str(path.relative_to(final_dir)) for path in frames],
                "narration_files": [str(path.relative_to(final_dir)) for path in audio],
                "voice_cast_file": "audio/voice_cast.json",
                "background_music_file": str(background_music.relative_to(final_dir)),
                "subtitles_file": subtitles.name,
                "thumbnail_file": thumbnail.name,
                "final_video_file": final_video.name,
                "human_approval_required": True,
                "completion_status": episode.completion_status,
                "unresolved_review_items": episode.unresolved_review_items,
                "upload_performed": False,
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            episode.video_assets = VideoAssets(
                status="rendered",
                panel_images=manifest["panel_images"],
                panel_frames=manifest["panel_frames"],
                narration_files=manifest["narration_files"],
                subtitles_file=subtitles.name,
                thumbnail_file=thumbnail.name,
                final_video_file=final_video.name,
                render_manifest_file=manifest_path.name,
            )
            disclosure = episode.video_assets.ai_voice_disclosure
            if disclosure not in episode.youtube_package.description:
                episode.youtube_package.description = (
                    episode.youtube_package.description.rstrip() + f"\n\n{disclosure}"
                )
            episode.upload_ready = False
            (final_dir / "final_episode.json").write_text(
                json.dumps(episode.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._say(f"완료: {final_video}")
            return final_video
        except Exception as exc:
            manifest_path.write_text(
                json.dumps(
                    {"status": "failed", "run_id": run_id, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise
        finally:
            for role in ("VideoRenderer", "VoiceProducer", "MusicProducer"):
                self._agent_state(role, "idle")
