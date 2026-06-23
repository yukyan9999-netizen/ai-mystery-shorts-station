from __future__ import annotations

import base64
import concurrent.futures
import html
import json
import math
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from textwrap import wrap
from typing import Any

import imageio_ffmpeg
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from src.knowledge_models import (
    KnowledgeProductionPackage,
    KnowledgeScene,
    ResearchSource,
    SceneAssetPlan,
)
from src.media_clip_selector import MediaClipSelector


class KnowledgeVideoStudio:
    ALLOWED_LICENSES = {
        "public_domain",
        "cc0",
        "cc_by",
        "cc_by_sa",
        "official_reuse_allowed",
    }

    def __init__(self, root: Path, live: bool = False) -> None:
        self.root = root.resolve()
        self.live = live
        load_dotenv(self.root / ".env")
        load_dotenv(self.root / ".env.local", override=True)
        config = yaml.safe_load((self.root / "config.yaml").read_text(encoding="utf-8"))
        self.config: dict[str, Any] = config["video_studio"]
        self.shorts_config: dict[str, Any] = config.get("shorts", {})
        self.client = OpenAI()
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.width = int(self.config["width"])
        self.height = int(self.config["height"])
        self.fps = int(self.config["fps"])
        self.visual_style: dict[str, Any] = self.config.get(
            "knowledge_visual_style",
            {},
        )

    def _state(self, role: str, state: str) -> None:
        if self.live:
            try:
                print(
                    "@@AGENT_STATE@@"
                    + json.dumps({"role": role, "state": state}, ensure_ascii=False),
                    flush=True,
                )
            except OSError:
                self.live = False

    def _progress(self, role: str, percent: int, message: str) -> None:
        if self.live:
            try:
                print(
                    "@@AGENT_PROGRESS@@"
                    + json.dumps(
                        {"role": role, "percent": percent, "message": message},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except OSError:
                self.live = False

    def _comment(self, role: str, comment: str) -> None:
        if self.live:
            try:
                print(
                    "@@AGENT_COMMENT@@"
                    + json.dumps({"role": role, "comment": comment}, ensure_ascii=False),
                    flush=True,
                )
            except OSError:
                self.live = False

    def _run_ffmpeg(self, args: list[str]) -> None:
        completed = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError(f"FFmpeg 오류: {completed.stderr.strip()}")

    def _font(self, bold: bool, size: int) -> ImageFont.FreeTypeFont:
        key = "bold_font_path" if bold else "font_path"
        return ImageFont.truetype(self.config[key], size=size)

    @staticmethod
    def _duration(scene: KnowledgeScene, fallback: float) -> float:
        timestamps = [
            int(minutes) * 60 + int(seconds)
            for minutes, seconds in re.findall(r"(\d+):(\d+)", scene.time_range)
        ]
        if len(timestamps) >= 2 and timestamps[1] > timestamps[0]:
            return float(timestamps[1] - timestamps[0])
        numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", scene.time_range)]
        if len(numbers) >= 2 and numbers[1] > numbers[0]:
            return numbers[1] - numbers[0]
        return fallback

    @staticmethod
    def _audio_duration(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as wav:
                frame_rate = wav.getframerate()
                if frame_rate <= 0:
                    raise ValueError("오디오 샘플레이트가 올바르지 않습니다.")
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                frame_count = wav.getnframes()
                header_duration = frame_count / frame_rate
            # OpenAI streaming WAV uses 0x7fffffff as an unknown frame count.
            # In that case calculate duration from the actual PCM bytes on disk.
            if frame_count < 2_000_000_000 and header_duration < 3600:
                return header_duration
            file_size = path.stat().st_size
            with path.open("rb") as raw:
                if raw.read(4) not in {b"RIFF", b"RF64"}:
                    raise wave.Error("RIFF/RF64 헤더가 아닙니다.")
                raw.seek(12)
                data_start = None
                while raw.tell() + 8 <= file_size:
                    chunk_id = raw.read(4)
                    chunk_size = int.from_bytes(raw.read(4), "little")
                    if chunk_id == b"data":
                        data_start = raw.tell()
                        break
                    next_position = raw.tell() + chunk_size + (chunk_size % 2)
                    if next_position > file_size:
                        break
                    raw.seek(next_position)
            if data_start is None:
                raise wave.Error("PCM data 청크를 찾을 수 없습니다.")
            bytes_per_second = channels * sample_width * frame_rate
            return max(0.0, (file_size - data_start) / bytes_per_second)
        except (wave.Error, EOFError) as exc:
            raise RuntimeError(f"내레이션 길이를 읽을 수 없습니다: {path.name}") from exc

    def _media_duration(self, path: Path) -> float:
        completed = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", str(path)],
            capture_output=True,
        )
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
        match = re.search(
            r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
            stderr,
        )
        if not match:
            return 0.0
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    @staticmethod
    def _compact_text(value: str) -> str:
        return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()

    def _meaningfully_covered(self, required: str, current: str) -> bool:
        compact_current = self._compact_text(current)
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?。！？])\s+", required)
            if sentence.strip()
        ]
        if not sentences:
            return True
        covered = sum(
            self._compact_text(sentence) in compact_current
            for sentence in sentences
        )
        return covered / len(sentences) >= 0.6

    def ensure_final_conclusion(
        self,
        package: KnowledgeProductionPackage,
    ) -> list[str]:
        return []

    def align_scene_durations(
        self,
        scenes: list[KnowledgeScene],
        audio_files: list[Path],
        planned_durations: list[float],
        tail_override: float | None = None,
    ) -> tuple[list[float], list[dict[str, Any]]]:
        timing = self.config.get("scene_timing", {})
        use_actual = bool(timing.get("use_actual_narration_length", True))
        tail = max(
            0.0,
            float(
                tail_override
                if tail_override is not None
                else timing.get("narration_tail_seconds", 0.35)
            ),
        )
        minimum = max(0.5, float(timing.get("minimum_scene_seconds", 1.8)))
        render_durations: list[float] = []
        timing_log: list[dict[str, Any]] = []
        extended_count = 0
        for scene, audio_path, planned in zip(
            scenes,
            audio_files,
            planned_durations,
        ):
            narration = self._audio_duration(audio_path)
            render_duration = (
                max(minimum, narration + tail)
                if use_actual
                else max(planned, narration + tail)
            )
            if render_duration > planned + 0.05:
                extended_count += 1
            render_durations.append(render_duration)
            timing_log.append(
                {
                    "scene_number": scene.scene_number,
                    "planned_seconds": round(planned, 3),
                    "narration_seconds": round(narration, 3),
                    "render_seconds": round(render_duration, 3),
                    "tail_seconds": round(max(0.0, render_duration - narration), 3),
                    "would_have_cut_seconds": round(max(0.0, narration - planned), 3),
                }
            )
        self._comment(
            "VideoRenderer",
            (
                f"실제 내레이션 길이에 맞춰 {len(render_durations)}개 장면의 전환점을 "
                f"다시 계산했습니다. 기존 계획보다 길어진 장면은 {extended_count}개입니다."
            ),
        )
        total_duration = sum(render_durations)
        max_seconds = float(self.shorts_config.get("max_seconds", 120))
        if total_duration > max_seconds:
            raise RuntimeError(
                f"자연스러운 내레이션 기준 영상 길이가 {total_duration:.1f}초로 "
                f"최대 {max_seconds:.0f}초를 초과합니다. 대본 검토에서 내용을 줄여주세요."
            )
        return render_durations, timing_log

    @staticmethod
    def _split_narration(text: str, count: int) -> list[str]:
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+|\n+", text)
            if item.strip()
        ]
        if not sentences:
            sentences = [text.strip()]
        chunks: list[str] = []
        target = max(1, math.ceil(sum(len(item) for item in sentences) / count))
        current = ""
        for sentence in sentences:
            if current and len(chunks) < count - 1 and len(current) + len(sentence) > target:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
        fallback = text.strip()
        while len(chunks) < count:
            longest = max(range(len(chunks)), key=lambda index: len(chunks[index]))
            words = chunks[longest].split()
            if len(words) < 2:
                chunks.append(fallback)
                continue
            middle = len(words) // 2
            chunks[longest : longest + 1] = [
                " ".join(words[:middle]),
                " ".join(words[middle:]),
            ]
        return (chunks[:count] or [fallback])

    def expand_long_scenes(
        self,
        package: KnowledgeProductionPackage,
    ) -> int:
        """Split long scenes by sentence boundaries.

        Rules:
        - Split narration on sentence-ending punctuation only (. ! ? 。)
        - Each sub-scene keeps at least one complete sentence
        - Maximum 2 splits per original scene (→ max 3 sub-scenes)
        - Scenes under 6 seconds estimated are never split
        - Total expanded scenes capped at 20
        - Time budget capped at 120 seconds
        - Sub-scenes reuse the parent's image_prompt (no suffix)
        """
        scenes = list(package.visual_package.scenes)
        if len(scenes) >= 20:
            return 0
        plans = {
            plan.scene_number: plan
            for plan in package.mixed_media_plan.scene_assets
        }
        expanded_scenes: list[KnowledgeScene] = []
        expanded_plans: list[SceneAssetPlan] = []
        elapsed = 0.0
        timing_cfg = self.config.get("scene_timing", {})
        min_scene_sec = max(0.5, float(timing_cfg.get("minimum_scene_seconds", 1.8)))
        tail_sec = max(0.0, float(timing_cfg.get("narration_tail_seconds", 0.35)))
        max_total = float(self.shorts_config.get("max_seconds", 120))
        estimated_total = 0.0

        for scene in scenes:
            if len(expanded_scenes) >= 20:
                break
            planned = max(self._duration(scene, 5.0), len(scene.narration) / 6.0)

            # Don't split short scenes
            if planned < 6.0:
                number = len(expanded_scenes) + 1
                start = elapsed
                elapsed += planned
                estimated_total += max(min_scene_sec, planned + tail_sec)
                expanded_scenes.append(
                    scene.model_copy(update={
                        "scene_number": number,
                        "time_range": f"{start:.1f}-{elapsed:.1f}",
                    })
                )
                source_plan = plans.get(scene.scene_number)
                expanded_plans.append(
                    source_plan.model_copy(update={"scene_number": number})
                    if source_plan
                    else SceneAssetPlan(
                        scene_number=number,
                        asset_mode="ai_reconstruction",
                        license_status="not_applicable",
                        usage_instruction="AI 대체 장면",
                        crop_and_motion="slow zoom",
                        fallback_ai_prompt=scene.image_prompt,
                    )
                )
                continue

            # Split by sentences only
            sentences = [
                s.strip()
                for s in re.split(r'(?<=[.!?。])\s*', scene.narration)
                if s.strip()
            ]
            if not sentences:
                sentences = [scene.narration.strip()]

            # Determine how many parts (max 3, limited by sentence count and cap)
            available = 20 - len(expanded_scenes)
            max_parts = min(available, 3, len(sentences))
            part_count = min(max(1, math.ceil(planned / 6.0)), max_parts)

            # Check time budget
            while part_count > 1:
                per_part = planned / part_count
                extra = part_count * max(0.0, min_scene_sec + tail_sec - per_part)
                if estimated_total + planned + extra <= max_total:
                    break
                part_count -= 1

            # Distribute sentences evenly across parts
            narration_parts: list[str] = []
            if part_count <= 1 or len(sentences) <= 1:
                narration_parts = [scene.narration.strip()]
                part_count = 1
            else:
                base_per_part = len(sentences) // part_count
                remainder = len(sentences) % part_count
                idx = 0
                for p in range(part_count):
                    count = base_per_part + (1 if p < remainder else 0)
                    chunk = " ".join(sentences[idx:idx + count])
                    if chunk:
                        narration_parts.append(chunk)
                    idx += count
                # Safety: merge any empty trailing parts
                narration_parts = [p for p in narration_parts if p]
                if not narration_parts:
                    narration_parts = [scene.narration.strip()]
                part_count = len(narration_parts)

            part_duration = planned / part_count
            estimated_total += sum(
                max(min_scene_sec, part_duration + tail_sec)
                for _ in range(part_count)
            )
            source_plan = plans.get(scene.scene_number)
            for _part_index, narration in enumerate(narration_parts):
                number = len(expanded_scenes) + 1
                if number > 20:
                    break
                start = elapsed
                elapsed += part_duration
                subtitle = self._clean_caption(narration)
                # Sub-scenes reuse parent's image_prompt exactly (no suffix)
                expanded_scenes.append(
                    scene.model_copy(
                        update={
                            "scene_number": number,
                            "time_range": f"{start:.1f}-{elapsed:.1f}",
                            "subtitle": subtitle or scene.subtitle,
                            "narration": narration,
                        }
                    )
                )
                if source_plan:
                    expanded_plans.append(
                        source_plan.model_copy(
                            update={
                                "scene_number": number,
                                "on_screen_source_label": "",
                            }
                        )
                    )
                else:
                    expanded_plans.append(
                        SceneAssetPlan(
                            scene_number=number,
                            asset_mode="ai_reconstruction",
                            license_status="not_applicable",
                            usage_instruction="추가 분할용 AI 재구성 이미지",
                            crop_and_motion="subtle cinematic motion",
                            on_screen_source_label="",
                            fallback_ai_prompt=scene.image_prompt,
                        )
                    )
        if len(expanded_scenes) > 20:
            expanded_scenes = expanded_scenes[:20]
            expanded_plans = expanded_plans[:20]
        if len(expanded_scenes) == len(scenes):
            return 0
        package.visual_package = package.visual_package.model_copy(
            update={"scenes": expanded_scenes}
        )
        package.mixed_media_plan = package.mixed_media_plan.model_copy(
            update={"scene_assets": expanded_plans}
        )
        return len(expanded_scenes) - len(scenes)

    def _load_package(self, run_id: str) -> tuple[Path, KnowledgeProductionPackage]:
        run_dir = self.root / "outputs" / "knowledge" / run_id
        package_path = run_dir / "final_knowledge_short.json"
        if not package_path.exists():
            raise FileNotFoundError(f"제작 패키지를 찾을 수 없습니다: {package_path}")
        raw = json.loads(package_path.read_text(encoding="utf-8"))
        if "visual_package" in raw and len(raw["visual_package"].get("scenes", [])) > 20:
            raw["visual_package"]["scenes"] = raw["visual_package"]["scenes"][:20]
        if "mixed_media_plan" in raw and len(raw["mixed_media_plan"].get("scene_assets", [])) > 20:
            raw["mixed_media_plan"]["scene_assets"] = raw["mixed_media_plan"]["scene_assets"][:20]
        package = KnowledgeProductionPackage.model_validate(raw)
        if not package.human_approval or not package.human_approval.get("approved"):
            raise RuntimeError("사람 승인 후에만 영상을 제작할 수 있습니다.")
        return run_dir, package

    @staticmethod
    def _find_source(
        package: KnowledgeProductionPackage,
        plan: SceneAssetPlan,
    ) -> ResearchSource | None:
        if not plan.source_page_url:
            return None
        return next(
            (
                source
                for source in package.source_research.sources
                if source.page_url == plan.source_page_url
            ),
            None,
        )

    @classmethod
    def _fallback_real_source(
        cls,
        package: KnowledgeProductionPackage,
    ) -> ResearchSource | None:
        return next(
            (
                source
                for source in package.source_research.sources
                if source.usable_in_final_video
                and source.license_status in cls.ALLOWED_LICENSES
                and (
                    source.direct_media_url
                    or "commons.wikimedia.org/wiki/" in source.page_url
                )
            ),
            None,
        )

    def _download_real_asset(
        self,
        run_dir: Path,
        scene_number: int,
        source: ResearchSource | None,
    ) -> Path | None:
        if (
            source is None
            or not source.usable_in_final_video
            or source.license_status not in self.ALLOWED_LICENSES
        ):
            return None
        media_url = source.direct_media_url or self._resolve_commons_media(
            source.page_url,
            scene_number,
        )
        if not media_url:
            media_url = self._resolve_page_media(source.page_url)
        if not media_url:
            return None
        raw_dir = run_dir / "media" / "downloaded"
        raw_dir.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            media_url,
            headers={"User-Agent": "Mozilla/5.0 KnowledgeShortsStudio/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                content_type = response.headers.get_content_type()
                payload = response.read(30 * 1024 * 1024 + 1)
            if len(payload) > 30 * 1024 * 1024:
                return None
            suffix = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
                "video/mp4": ".mp4",
                "video/webm": ".webm",
            }.get(content_type, Path(media_url.split("?")[0]).suffix.lower())
            if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm"}:
                return None
            raw_path = raw_dir / f"scene_{scene_number:02d}{suffix}"
            raw_path.write_bytes(payload)
            if suffix in {".mp4", ".webm"}:
                frame_path = raw_dir / f"scene_{scene_number:02d}_video_frame.png"
                self._run_ffmpeg(
                    [
                        "-ss",
                        "1",
                        "-i",
                        str(raw_path),
                        "-frames:v",
                        "1",
                        str(frame_path),
                    ]
                )
                return frame_path if frame_path.exists() else None
            Image.open(raw_path).verify()
            return raw_path
        except Exception:
            return None

    @staticmethod
    def _resolve_page_media(page_url: str) -> str:
        if not page_url.startswith(("http://", "https://")):
            return ""
        try:
            request = urllib.request.Request(
                page_url,
                headers={"User-Agent": "Mozilla/5.0 KnowledgeShortsStudio/1.0"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                content_type = response.headers.get_content_type()
                if content_type.startswith("image/"):
                    return page_url
                body = response.read(2_000_000).decode("utf-8", errors="ignore")
            patterns = [
                r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, body, flags=re.I)
                if match:
                    return urllib.parse.urljoin(page_url, html.unescape(match.group(1)))
        except Exception:
            return ""
        return ""

    @staticmethod
    def _resolve_commons_media(page_url: str, scene_number: int) -> str:
        if "commons.wikimedia.org/wiki/" not in page_url:
            return ""
        title = urllib.parse.unquote(page_url.split("/wiki/", 1)[1].split("#", 1)[0])
        if title.startswith("Category:"):
            params = {
                "action": "query",
                "generator": "categorymembers",
                "gcmtitle": title,
                "gcmtype": "file",
                "gcmlimit": "20",
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "format": "json",
            }
        elif title.startswith("File:"):
            params = {
                "action": "query",
                "titles": title,
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "format": "json",
            }
        else:
            return ""
        api_url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        try:
            request = urllib.request.Request(
                api_url,
                headers={"User-Agent": "KnowledgeShortsStudio/1.0"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            candidates = []
            for page in (data.get("query", {}).get("pages", {}) or {}).values():
                info = (page.get("imageinfo") or [{}])[0]
                if str(info.get("mime", "")).startswith("image/") and info.get("url"):
                    candidates.append(str(info["url"]))
            if not candidates:
                return ""
            return candidates[(scene_number - 1) % len(candidates)]
        except Exception:
            return ""

    _used_stock_urls: set[str] = set()

    def _search_stock_image(
        self,
        run_dir: Path,
        scene: KnowledgeScene,
        title: str = "",
    ) -> Path | None:
        stock_dir = run_dir / "media" / "downloaded"
        stock_dir.mkdir(parents=True, exist_ok=True)
        cached = sorted(stock_dir.glob(f"scene_{scene.scene_number:02d}_stock.*"))
        if cached:
            return cached[0]
        # image_prompt에서 영어 키워드를 추출 (가장 정확한 소스)
        # image_prompt는 AI가 장면을 묘사한 영어 텍스트
        stop = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "and", "or", "not", "no", "this", "that", "with", "for", "from",
            "but", "visual", "beat", "create", "distinctly", "different",
            "text", "labels", "badges", "captions", "watermarks", "letters",
            "words", "logos", "signs", "no", "absolutely", "anywhere",
            "image", "vertical", "documentary", "mystery", "cinematic",
        }
        prompt_words = [
            w.lower().strip(".,!?:;'\"()[]")
            for w in scene.image_prompt.split()
            if len(w) > 2 and w.lower().strip(".,!?:;'\"()[]") not in stop
        ][:5]
        # 제목에서도 한국어 매핑 추가
        from src.media_clip_selector import MediaClipSelector
        topic_map = MediaClipSelector.KOREAN_SEARCH_MAP
        title_kw: list[str] = []
        for ko, en_list in topic_map.items():
            if ko in title:
                title_kw.append(en_list[0].split()[0])
        all_kw = list(dict.fromkeys(title_kw + prompt_words))
        if not all_kw:
            all_kw = ["mystery", "science"]
        keywords = " ".join(all_kw[:4])
        import random
        page_offset = random.randint(1, 10)
        per_page = 8
        import os
        pexels_key = os.environ.get("PEXELS_API_KEY", "")
        pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
        for provider, url, headers, extract_all in [
            (
                "pexels",
                "https://api.pexels.com/v1/search?"
                + urllib.parse.urlencode({
                    "query": keywords, "orientation": "portrait",
                    "size": "medium", "per_page": per_page,
                    "page": page_offset,
                }),
                {"Authorization": pexels_key},
                lambda data: [
                    p.get("src", {}).get("large2x") or p.get("src", {}).get("original")
                    for p in data.get("photos", [])
                    if p.get("src")
                ],
            ),
            (
                "pixabay",
                "https://pixabay.com/api/?"
                + urllib.parse.urlencode({
                    "key": pixabay_key, "q": keywords,
                    "image_type": "photo", "orientation": "vertical",
                    "per_page": per_page, "page": page_offset,
                    "safesearch": "true",
                }),
                {},
                lambda data: [
                    h.get("largeImageURL")
                    for h in data.get("hits", [])
                    if h.get("largeImageURL")
                ],
            ),
        ]:
            api_key = pexels_key if provider == "pexels" else pixabay_key
            if not api_key:
                continue
            try:
                request = urllib.request.Request(url, headers={
                    "User-Agent": "KnowledgeShortsStudio/1.0",
                    **headers,
                })
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = json.loads(response.read().decode("utf-8"))
                candidates = extract_all(data)
                # 이미 사용한 URL은 건너뛰어 중복 방지
                image_url = None
                for candidate_url in candidates:
                    if candidate_url and candidate_url not in self._used_stock_urls:
                        image_url = candidate_url
                        break
                if not image_url:
                    continue
                img_request = urllib.request.Request(
                    image_url,
                    headers={"User-Agent": "KnowledgeShortsStudio/1.0"},
                )
                with urllib.request.urlopen(img_request, timeout=15) as img_response:
                    img_bytes = img_response.read(10 * 1024 * 1024)
                if len(img_bytes) < 1000:
                    continue
                suffix = ".jpg"
                content_type = img_response.headers.get_content_type() if hasattr(img_response, 'headers') else ""
                if "png" in str(content_type):
                    suffix = ".png"
                path = stock_dir / f"scene_{scene.scene_number:02d}_stock{suffix}"
                path.write_bytes(img_bytes)
                Image.open(path).verify()
                self._used_stock_urls.add(image_url)
                return path
            except Exception:
                continue
        return None

    def _generate_ai_image(
        self,
        run_dir: Path,
        scene: KnowledgeScene,
        plan: SceneAssetPlan,
    ) -> Path:
        image_dir = run_dir / "media" / "generated"
        image_dir.mkdir(parents=True, exist_ok=True)
        path = image_dir / f"scene_{scene.scene_number:02d}.png"
        if path.exists():
            return path
        prompt = plan.fallback_ai_prompt or scene.image_prompt
        response = self.client.images.generate(
            model=self.config["image_model"],
            prompt=(
                f"{prompt}\nVertical 9:16 documentary mystery visual. "
                "Absolutely no text anywhere in the image: no captions, labels, signs, "
                "letters, words, logos, UI, badges, or watermark. "
                "Do not visualize fact/hypothesis classifications as text. "
                "No copyrighted characters. "
                "If this depicts an unverified claim, make it clearly interpretive rather than photographic proof."
            ),
            size=self.config["image_size"],
            quality=self.config["image_quality"],
            output_format="png",
        )
        encoded = response.data[0].b64_json
        if not encoded:
            raise RuntimeError("이미지 API가 이미지 데이터를 반환하지 않았습니다.")
        path.write_bytes(base64.b64decode(encoded))
        return path

    def _motion_graphic(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        scene: KnowledgeScene,
    ) -> Path:
        image_dir = run_dir / "media" / "motion_graphics"
        image_dir.mkdir(parents=True, exist_ok=True)
        path = image_dir / f"scene_{scene.scene_number:02d}.png"
        if path.exists():
            return path
        canvas = Image.new("RGB", (1024, 1536), "#080808")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, 1024, 1536), fill="#080808")
        draw.ellipse((-250, 150, 650, 1050), fill="#1b1b1b")
        draw.ellipse((520, 650, 1320, 1450), fill="#240606")
        title_font = self._font(True, 82)
        small_font = self._font(True, 32)
        lines = wrap(self._clean_caption(scene.subtitle), width=11)[:3]
        total_height = len(lines) * 108
        y = (1536 - total_height) // 2
        for index, line in enumerate(lines):
            self._draw_centered_mixed_line(
                draw,
                line,
                y,
                title_font,
                "#ffffff",
                self.visual_style.get("accent_color", "#ef2b22"),
                6,
                index == len(lines) - 1,
                1024,
            )
            y += 108
        draw.text(
            (50, 1450),
            self._display_label("미스터리 재구성"),
            font=small_font,
            fill="#b8b8b8",
        )
        canvas.save(path)
        return path

    @staticmethod
    def _clean_caption(value: str) -> str:
        text = re.sub(r"\([^)]*\)", "", str(value or ""))
        text = re.sub(
            r"\b(?:historical_record|reported_claim|current_hypothesis|"
            r"not_proven_as_cause|verified_fact|uncertain|simulation)\b",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(r"[_]{2,}", " ", text)
        return " ".join(text.split()).strip() or "미스터리는 아직 끝나지 않았다"

    @staticmethod
    def _fit_caption_lines(
        caption: str,
        base_font_size: int,
        base_width: int,
        max_lines: int = 4,
        min_font_size: int = 38,
    ) -> tuple[list[str], int]:
        """긴 자막도 잘리지 않도록 폰트 크기를 줄여 전부 보이게 한다."""
        font_size = base_font_size
        while font_size >= min_font_size:
            width = max(8, int(base_width * base_font_size / font_size))
            lines = wrap(caption, width=width)
            if len(lines) <= max_lines:
                return lines, font_size
            font_size -= 4
        # 최소 폰트로도 안 맞으면 최소 폰트로 전부 표시 (자르지 않음)
        width = max(8, int(base_width * base_font_size / min_font_size))
        return wrap(caption, width=width), min_font_size

    @staticmethod
    def _display_label(value: str) -> str:
        raw = str(value or "").lower()
        mappings = [
            (("ai 재구성", "ai_reconstruction"), "AI 재구성"),
            (("미스터리 재구성",), "미스터리 재구성"),
            (("historical_record", "확인된 기록"), "기록에 남은 이야기"),
            (("reported_claim", "목격자 주장"), "목격자 주장"),
            (("current_hypothesis", "현재 학설"), "현재 가설"),
            (("not_proven", "진위 미확인", "uncertain"), "진위 미확인"),
            (("simulation", "가상 시나리오"), "가상 시나리오"),
        ]
        for needles, label in mappings:
            if any(needle in raw for needle in needles):
                return label
        return "미스터리 기록"

    @staticmethod
    def _draw_centered_mixed_line(
        draw: ImageDraw.ImageDraw,
        line: str,
        y: int,
        font: ImageFont.FreeTypeFont,
        normal_fill: str,
        accent_fill: str,
        stroke_width: int,
        accent_last_word: bool,
        canvas_width: int,
    ) -> None:
        words = line.split()
        if not accent_last_word:
            box = draw.textbbox(
                (0, 0),
                line,
                font=font,
                stroke_width=stroke_width,
            )
            draw.text(
                ((canvas_width - (box[2] - box[0])) // 2, y),
                line,
                font=font,
                fill=normal_fill,
                stroke_width=stroke_width,
                stroke_fill="black",
            )
            return
        if len(words) < 2:
            box = draw.textbbox(
                (0, 0),
                line,
                font=font,
                stroke_width=stroke_width,
            )
            draw.text(
                ((canvas_width - (box[2] - box[0])) // 2, y),
                line,
                font=font,
                fill=accent_fill,
                stroke_width=stroke_width,
                stroke_fill="black",
            )
            return
        normal = " ".join(words[:-1]) + " "
        accent = words[-1]
        normal_box = draw.textbbox(
            (0, 0),
            normal,
            font=font,
            stroke_width=stroke_width,
        )
        accent_box = draw.textbbox(
            (0, 0),
            accent,
            font=font,
            stroke_width=stroke_width,
        )
        normal_width = normal_box[2] - normal_box[0]
        accent_width = accent_box[2] - accent_box[0]
        x = (canvas_width - normal_width - accent_width) // 2
        draw.text(
            (x, y),
            normal,
            font=font,
            fill=normal_fill,
            stroke_width=stroke_width,
            stroke_fill="black",
        )
        draw.text(
            (x + normal_width, y),
            accent,
            font=font,
            fill=accent_fill,
            stroke_width=stroke_width,
            stroke_fill="black",
        )

    def _prepare_single_scene(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        scene: KnowledgeScene,
        plan: SceneAssetPlan,
        force_ai: bool = False,
    ) -> tuple[Path, dict[str, Any]]:
        # 재제작 시 기존 이미지를 최대한 재사용.
        # generated, downloaded 어디든 이미 있으면 새로 만들지 않는다.
        for cache_dir_name in ("generated", "downloaded"):
            cache_dir = run_dir / "media" / cache_dir_name
            if cache_dir.exists():
                cached = sorted(cache_dir.glob(f"scene_{scene.scene_number:02d}.*"))
                if cached:
                    mode = "ai_reconstruction_fallback" if cache_dir_name == "generated" else "stock_image"
                    return cached[0], {
                        "scene_number": scene.scene_number,
                        "planned_mode": plan.asset_mode,
                        "used_mode": mode,
                        "source_page_url": "",
                        "license_status": "not_applicable",
                        "file": str(cached[0].relative_to(run_dir)),
                    }
        source = self._find_source(package, plan)
        image = None
        used_mode = plan.asset_mode
        existing_by_type: dict[str, list[Path]] = {}
        for directory in ("downloaded", "generated", "motion_graphics"):
            target = run_dir / "media" / directory
            existing_by_type[directory] = (
                sorted(target.glob(f"scene_{scene.scene_number:02d}.*"))
                if target.exists()
                else []
            )
        existing_downloaded = existing_by_type["downloaded"]
        existing_generated = existing_by_type["generated"]
        existing_motion = existing_by_type["motion_graphics"]
        if existing_downloaded:
            image = existing_downloaded[0]
            used_mode = "licensed_real_media"
        elif plan.asset_mode == "motion_graphics" and existing_motion:
            image = existing_motion[0]
            used_mode = "motion_graphics"
        if image is not None:
            used_mode = {
                "downloaded": "licensed_real_media",
                "generated": "ai_reconstruction_fallback",
                "motion_graphics": "motion_graphics",
            }.get(image.parent.name, "reused_existing_asset")
        if plan.asset_mode in {"licensed_real_media", "official_media"}:
            if image is None:
                image = self._download_real_asset(
                    run_dir,
                    scene.scene_number,
                    source,
                )
        elif plan.asset_mode in {"community_reference_only", "motion_graphics"}:
            if image is None:
                source = self._fallback_real_source(package)
                image = self._download_real_asset(
                    run_dir,
                    scene.scene_number,
                    source,
                )
                if image is not None:
                    used_mode = "licensed_real_media"
        if image is None:
            if plan.asset_mode == "motion_graphics":
                image = self._motion_graphic(run_dir, package, scene)
                used_mode = "motion_graphics"
            else:
                if not force_ai:
                    image = self._search_stock_image(run_dir, scene, package.selected_candidate.title)
                if image is not None:
                    used_mode = "stock_image"
                elif existing_generated:
                    image = existing_generated[0]
                    used_mode = "ai_reconstruction_fallback"
                else:
                    image = self._generate_ai_image(run_dir, scene, plan)
                    used_mode = "ai_reconstruction_fallback"
        log_entry = {
            "scene_number": scene.scene_number,
            "planned_mode": plan.asset_mode,
            "used_mode": used_mode,
            "source_page_url": source.page_url if source else "",
            "license_status": source.license_status if source else plan.license_status,
            "file": str(image.relative_to(run_dir)),
        }
        return image, log_entry

    def prepare_scene_images(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
    ) -> tuple[list[Path], list[dict[str, Any]]]:
        """Prepare images for all scenes.

        Strategy:
        - Check cache first (generated/ or downloaded/)
        - If this scene's image_prompt matches a previous scene, reuse that image
        - First and last scene → AI image
        - Others → try stock image first, fallback to AI
        - Unique scenes that need new images are fetched in parallel
        """
        plans = {plan.scene_number: plan for plan in package.mixed_media_plan.scene_assets}
        scenes = package.visual_package.scenes
        self._state("VideoRenderer", "working")

        # Build per-scene plan: cache check and dedup by image_prompt
        prompt_to_image: dict[str, Path] = {}  # image_prompt → resolved image
        cached: dict[int, tuple[Path, str]] = {}  # scene index → (path, mode)
        needs_work: list[int] = []  # indices that need image generation

        for i, scene in enumerate(scenes):
            # Check cache
            found_cache = False
            for d in ("generated", "downloaded"):
                cd = run_dir / "media" / d
                if cd.exists():
                    hits = sorted(cd.glob(f"scene_{scene.scene_number:02d}.*"))
                    if hits:
                        mode = "ai_reconstruction_fallback" if d == "generated" else "stock_image"
                        cached[i] = (hits[0], mode)
                        prompt_to_image[scene.image_prompt] = hits[0]
                        found_cache = True
                        break
            if found_cache:
                continue

            # Check if same image_prompt was already seen (sub-scene reuse)
            if scene.image_prompt in prompt_to_image:
                cached[i] = (prompt_to_image[scene.image_prompt], "reuse_parent")
                continue

            # Mark as needing work; reserve the prompt key
            needs_work.append(i)

        def _prepare_one(idx: int) -> tuple[int, Path, str]:
            scene = scenes[idx]
            plan = plans.get(scene.scene_number) or SceneAssetPlan(
                scene_number=scene.scene_number,
                asset_mode="ai_reconstruction",
                license_status="not_applicable",
                usage_instruction="AI 대체 장면",
                crop_and_motion="slow zoom",
                fallback_ai_prompt=scene.image_prompt,
            )
            # First and last scene → AI; others → try stock first
            is_first_or_last = (idx == 0 or idx == len(scenes) - 1)
            if not is_first_or_last:
                image = self._search_stock_image(run_dir, scene, package.selected_candidate.title)
                if image:
                    return idx, image, "stock_image"
            image = self._generate_ai_image(run_dir, scene, plan)
            return idx, image, "ai_reconstruction_fallback"

        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_prepare_one, idx): idx
                for idx in needs_work
            }
            for future in concurrent.futures.as_completed(futures):
                idx, image, mode = future.result()
                cached[idx] = (image, mode)
                prompt_to_image[scenes[idx].image_prompt] = image
                completed += 1
                self._progress(
                    "VideoRenderer",
                    5 + round(completed / max(len(needs_work), 1) * 30),
                    f"이미지 {completed}/{len(needs_work)}개 준비 완료.",
                )

        # After parallel work, resolve any remaining sub-scenes that share a prompt
        # with a scene that was just generated
        for i, scene in enumerate(scenes):
            if i in cached:
                continue
            if scene.image_prompt in prompt_to_image:
                cached[i] = (prompt_to_image[scene.image_prompt], "reuse_parent")
            else:
                # Shouldn't happen, but safety fallback
                plan = plans.get(scene.scene_number) or SceneAssetPlan(
                    scene_number=scene.scene_number,
                    asset_mode="ai_reconstruction",
                    license_status="not_applicable",
                    usage_instruction="AI 대체 장면",
                    crop_and_motion="slow zoom",
                    fallback_ai_prompt=scene.image_prompt,
                )
                img = self._generate_ai_image(run_dir, scene, plan)
                cached[i] = (img, "ai_reconstruction_fallback")
                prompt_to_image[scene.image_prompt] = img

        # Assemble ordered results
        images: list[Path] = []
        log: list[dict[str, Any]] = []
        for i, scene in enumerate(scenes):
            image, mode = cached[i]
            images.append(image)
            log.append({
                "scene_number": scene.scene_number,
                "planned_mode": "ai_reconstruction",
                "used_mode": mode,
                "source_page_url": "",
                "license_status": "not_applicable",
                "file": str(image.relative_to(run_dir)),
            })
        self._progress("VideoRenderer", 40, f"{len(scenes)}개 장면 이미지 준비 완료.")
        return images, log

    def compose_frames(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        images: list[Path],
    ) -> list[Path]:
        frame_dir = run_dir / "frames"
        frame_dir.mkdir(exist_ok=True)
        plans = {plan.scene_number: plan for plan in package.mixed_media_plan.scene_assets}
        frames: list[Path] = []
        for scene, image_path in zip(package.visual_package.scenes, images):
            frame_path = frame_dir / f"scene_{scene.scene_number:02d}.jpg"
            if frame_path.exists():
                frames.append(frame_path)
                continue
            source_image = Image.open(image_path).convert("RGB")
            background = ImageOps.fit(
                source_image,
                (self.width, self.height),
                method=Image.Resampling.LANCZOS,
            )
            background = background.filter(ImageFilter.GaussianBlur(radius=22))
            background = ImageEnhance.Brightness(background).enhance(0.38)
            sharp = ImageOps.contain(
                source_image,
                (self.width, self.height),
                method=Image.Resampling.LANCZOS,
            )
            canvas = background
            canvas.paste(
                sharp,
                ((self.width - sharp.width) // 2, (self.height - sharp.height) // 2),
            )
            # Captions are rendered later as an independent movie-subtitle layer.
            canvas.save(frame_path, quality=94)
            frames.append(frame_path)
            continue
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle((0, 0, self.width, 370), fill=(0, 0, 0, 105))
            draw.rectangle((0, self.height - 500, self.width, self.height), fill=(0, 0, 0, 125))
            plan = plans.get(scene.scene_number)
            raw_label = (
                plan.on_screen_source_label
                if plan and plan.on_screen_source_label
                else (
                    package.fact_check.required_on_screen_labels[0]
                    if package.fact_check.required_on_screen_labels
                    else "미스터리 기록"
                )
            )
            label = self._display_label(raw_label)
            label_font = self._font(
                True,
                int(self.visual_style.get("truth_label_font_size", 25)),
            )
            label_box = draw.textbbox((0, 0), label, font=label_font)
            label_width = label_box[2] - label_box[0] + 34
            draw.rounded_rectangle(
                (38, self.height - 92, 38 + label_width, self.height - 42),
                13,
                fill=(0, 0, 0, 165),
            )
            draw.text(
                (55, self.height - 83),
                label,
                font=label_font,
                fill="#d6d6d6",
            )
            caption = self._clean_caption(scene.subtitle)
            font_size = int(
                self.visual_style.get(
                    "headline_font_size" if scene.scene_number == 1 else "subtitle_font_size",
                    76 if scene.scene_number == 1 else 66,
                )
            )
            lines, font_size = self._fit_caption_lines(
                caption, font_size, 12 if scene.scene_number == 1 else 15
            )
            subtitle_font = self._font(True, font_size)
            line_height = int(font_size * 1.28)
            if scene.scene_number == 1:
                y = 150
            else:
                y = self.height - 440
            outline = int(self.visual_style.get("outline_width", 6))
            for line_index, line in enumerate(lines):
                self._draw_centered_mixed_line(
                    draw,
                    line,
                    y,
                    subtitle_font,
                    self.visual_style.get("text_color", "#ffffff"),
                    self.visual_style.get("accent_color", "#ef2b22"),
                    outline,
                    scene.scene_number == 1 and line_index == len(lines) - 1,
                    self.width,
                )
                y += line_height
            frame = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
            frame.save(frame_path, quality=94)
            frames.append(frame_path)
        return frames

    def compose_caption_overlays(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        ai_scene_numbers: set[int] | None = None,
    ) -> dict[int, Path]:
        overlay_dir = run_dir / "frames" / "caption_overlays"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        plans = {plan.scene_number: plan for plan in package.mixed_media_plan.scene_assets}
        overlays: dict[int, Path] = {}
        for scene in package.visual_package.scenes:
            path = overlay_dir / f"scene_{scene.scene_number:02d}.png"
            overlays[scene.scene_number] = path
            if path.exists():
                continue
            overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            plan = plans.get(scene.scene_number)
            raw_label = (
                plan.on_screen_source_label
                if plan and plan.on_screen_source_label
                else (
                    package.fact_check.required_on_screen_labels[0]
                    if package.fact_check.required_on_screen_labels
                    else ""
                )
            )
            # Source/fact labels belong in metadata, not inside the movie subtitle.
            raw_label = ""
            if raw_label:
                label = self._display_label(raw_label)
                label_font = self._font(
                    True,
                    int(self.visual_style.get("truth_label_font_size", 25)),
                )
                label_box = draw.textbbox((0, 0), label, font=label_font)
                label_width = label_box[2] - label_box[0] + 34
                draw.rounded_rectangle(
                    (38, 52, 38 + label_width, 102),
                    13,
                    fill=(0, 0, 0, 150),
                )
                draw.text((55, 61), label, font=label_font, fill="#d6d6d6")

            caption = self._clean_caption(scene.subtitle)
            font_size = int(
                self.visual_style.get(
                    "headline_font_size" if scene.scene_number == 1 else "subtitle_font_size",
                    76 if scene.scene_number == 1 else 66,
                )
            )
            lines, font_size = self._fit_caption_lines(caption, font_size, 15)
            subtitle_font = self._font(True, font_size)
            line_height = int(font_size * 1.28)
            block_height = line_height * len(lines)
            bottom_margin = int(self.visual_style.get("caption_bottom_margin", 250))
            y = self.height - bottom_margin - block_height
            line_boxes = [draw.textbbox((0, 0), line, font=subtitle_font) for line in lines]
            widest = max((box[2] - box[0] for box in line_boxes), default=0)
            draw.rounded_rectangle(
                (
                    max(24, (self.width - widest) // 2 - 28),
                    y - 18,
                    min(self.width - 24, (self.width + widest) // 2 + 28),
                    y + block_height + 18,
                ),
                20,
                fill=(0, 0, 0, int(self.visual_style.get("caption_box_alpha", 115))),
            )
            outline = int(self.visual_style.get("outline_width", 6))
            for line_index, line in enumerate(lines):
                self._draw_centered_mixed_line(
                    draw,
                    line,
                    y,
                    subtitle_font,
                    self.visual_style.get("text_color", "#ffffff"),
                    self.visual_style.get("accent_color", "#ef2b22"),
                    outline,
                    scene.scene_number == 1 and line_index == len(lines) - 1,
                    self.width,
                )
                y += line_height
            is_ai_scene = (
                scene.scene_number in ai_scene_numbers
                if ai_scene_numbers is not None
                else bool(
                    plan
                    and plan.asset_mode in {"ai_reconstruction", "motion_graphics"}
                )
            )
            if is_ai_scene:
                marker = "AI 재구성"
                marker_font = self._font(
                    False,
                    int(self.visual_style.get("ai_marker_font_size", 18)),
                )
                marker_box = draw.textbbox((0, 0), marker, font=marker_font)
                marker_width = marker_box[2] - marker_box[0]
                marker_height = marker_box[3] - marker_box[1]
                right = self.width - 26
                bottom = self.height - 32
                draw.rounded_rectangle(
                    (
                        right - marker_width - 20,
                        bottom - marker_height - 12,
                        right + 8,
                        bottom + 7,
                    ),
                    8,
                    fill=(
                        0,
                        0,
                        0,
                        int(self.visual_style.get("ai_marker_alpha", 82)),
                    ),
                )
                draw.text(
                    (right - marker_width - 6, bottom - marker_height - 4),
                    marker,
                    font=marker_font,
                    fill=(210, 210, 210, 145),
                )
            overlay.save(path)
        return overlays

    def compose_stock_caption_overlays(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
    ) -> dict[int, Path]:
        overlay_dir = run_dir / "frames" / "stock_overlays"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        plans = {plan.scene_number: plan for plan in package.mixed_media_plan.scene_assets}
        overlays: dict[int, Path] = {}
        for scene in package.visual_package.scenes:
            path = overlay_dir / f"scene_{scene.scene_number:02d}.png"
            overlays[scene.scene_number] = path
            if path.exists():
                continue
            overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle((0, 0, self.width, 370), fill=(0, 0, 0, 105))
            draw.rectangle(
                (0, self.height - 500, self.width, self.height),
                fill=(0, 0, 0, 125),
            )
            plan = plans.get(scene.scene_number)
            raw_label = (
                plan.on_screen_source_label
                if plan and plan.on_screen_source_label
                else (
                    package.fact_check.required_on_screen_labels[0]
                    if package.fact_check.required_on_screen_labels
                    else "미스터리 기록"
                )
            )
            label = self._display_label(raw_label)
            label_font = self._font(
                True,
                int(self.visual_style.get("truth_label_font_size", 25)),
            )
            label_box = draw.textbbox((0, 0), label, font=label_font)
            label_width = label_box[2] - label_box[0] + 34
            draw.rounded_rectangle(
                (38, self.height - 92, 38 + label_width, self.height - 42),
                13,
                fill=(0, 0, 0, 165),
            )
            draw.text(
                (55, self.height - 83),
                label,
                font=label_font,
                fill="#d6d6d6",
            )
            caption = self._clean_caption(scene.subtitle)
            font_size = int(
                self.visual_style.get(
                    "headline_font_size"
                    if scene.scene_number == 1
                    else "subtitle_font_size",
                    76 if scene.scene_number == 1 else 66,
                )
            )
            lines, font_size = self._fit_caption_lines(
                caption, font_size, 12 if scene.scene_number == 1 else 15
            )
            subtitle_font = self._font(True, font_size)
            line_height = int(font_size * 1.28)
            y = 150 if scene.scene_number == 1 else self.height - 440
            outline = int(self.visual_style.get("outline_width", 6))
            for line_index, line in enumerate(lines):
                self._draw_centered_mixed_line(
                    draw,
                    line,
                    y,
                    subtitle_font,
                    self.visual_style.get("text_color", "#ffffff"),
                    self.visual_style.get("accent_color", "#ef2b22"),
                    outline,
                    scene.scene_number == 1 and line_index == len(lines) - 1,
                    self.width,
                )
                y += line_height
            overlay.save(path)
        return overlays

    @staticmethod
    def _scene_emotion(
        scene_index: int,
        total_scenes: int,
        narration: str,
    ) -> str:
        position = scene_index / max(total_scenes, 1)
        has_question = "?" in narration
        is_short = len(narration) < 20
        has_exclamation = "!" in narration
        keywords_surprise = any(
            w in narration for w in ("근데", "잠깐", "이상한", "문제는", "충격", "소름")
        )
        keywords_fear = any(
            w in narration for w in ("공포", "무섭", "죽", "사라", "멸망", "파괴")
        )
        if position < 0.15:
            return (
                "가볍고 호기심 가득한 톤. 친구한테 '야 이거 알아?' 하듯 편하게. "
                "약간 빠르게, 에너지 있게 시작한다."
            )
        if position > 0.85:
            return (
                "여운을 남기는 톤. 속도를 천천히 줄이고 마지막 문장은 "
                "살짝 낮은 목소리로 의미심장하게 끝낸다. 급하지 않게."
            )
        if keywords_surprise or (has_question and is_short):
            return (
                "놀란 듯 약간 높은 톤. '뭐?' 하는 반응처럼. "
                "짧게 끊고 다음 말 전에 0.3초 숨을 고른다."
            )
        if keywords_fear:
            return (
                "낮고 긴장된 톤. 속삭이듯 천천히. "
                "무서운 이야기를 들려주는 느낌으로."
            )
        if has_question:
            return (
                "궁금한 듯 살짝 올라가는 톤. 진심으로 궁금해하는 느낌. "
                "질문 끝을 자연스럽게 올린다."
            )
        if has_exclamation:
            return (
                "확신에 찬 톤. 중요한 사실을 강조하듯 또렷하게. "
                "핵심 단어에 힘을 준다."
            )
        if 0.4 < position < 0.7:
            return (
                "긴장이 쌓이는 톤. 조금씩 속도를 올리고 목소리를 낮춘다. "
                "반전 직전의 분위기를 만든다."
            )
        return (
            "사실을 전달하는 차분한 톤. 너무 빠르지 않게, "
            "자연스러운 대화 속도로 읽는다."
        )

    def generate_narration(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
    ) -> list[Path]:
        audio_dir = run_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        timing = self.config.get("scene_timing", {})
        base_speed = max(1.0, float(timing.get("base_speed_factor", 1.0)))
        base_instructions = self.config["speech_instructions"]
        paths: list[Path] = []
        scenes = package.visual_package.scenes
        self._state("VoiceProducer", "working")
        for index, scene in enumerate(scenes, start=1):
            path = audio_dir / f"scene_{scene.scene_number:02d}.wav"
            if path.exists():
                paths.append(path)
                self._progress(
                    "VoiceProducer",
                    round(index / len(scenes) * 100),
                    f"{scene.scene_number}번 기존 내레이션을 재사용합니다.",
                )
                continue
            percent = round(index / len(scenes) * 100)
            emotion = self._scene_emotion(index, len(scenes), scene.narration)
            self._progress(
                "VoiceProducer",
                percent,
                f"{scene.scene_number}번 장면 내레이션을 제작하고 있습니다.",
            )
            raw_path = audio_dir / f"scene_{scene.scene_number:02d}_raw.wav"
            scene_instructions = f"{base_instructions}\n\n이 장면의 감정: {emotion}"
            with self.client.audio.speech.with_streaming_response.create(
                model=self.config["speech_model"],
                voice=str(self.config.get("knowledge_narrator_voice", "cedar")),
                input=scene.narration,
                instructions=scene_instructions,
                response_format="wav",
            ) as response:
                response.stream_to_file(raw_path)
            if base_speed > 1.0:
                self._run_ffmpeg(
                    [
                        "-i", str(raw_path),
                        "-filter:a", f"atempo={base_speed:.6f}",
                        "-c:a", "pcm_s16le",
                        str(path),
                    ]
                )
                raw_path.unlink(missing_ok=True)
            else:
                raw_path.rename(path)
            paths.append(path)
        self._state("VoiceProducer", "idle")
        return paths

    def fit_narration_speed(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        audio_files: list[Path],
    ) -> tuple[list[Path], dict[str, Any]]:
        approval_options = (package.human_approval or {}).get(
            "render_options",
            {},
        )
        timing = self.config.get("scene_timing", {})
        fit_config = timing.get("duration_fit", {})
        requested = bool(approval_options.get("fit_to_60_seconds", False))
        target = float(
            approval_options.get(
                "target_seconds",
                fit_config.get("target_seconds", 60),
            )
        )
        max_speed = min(
            1.2,
            max(
                1.0,
                float(
                    approval_options.get(
                        "maximum_speed_factor",
                        fit_config.get("maximum_speed_factor", 1.2),
                    )
                ),
            ),
        )
        overrun_ratio = min(
            0.2,
            max(
                0.0,
                float(fit_config.get("eligible_overrun_ratio", 0.2)),
            ),
        )
        normal_tail = max(
            0.0,
            float(timing.get("narration_tail_seconds", 0.35)),
        )
        fitted_tail = max(
            0.0,
            float(fit_config.get("fitted_tail_seconds", 0.05)),
        )
        minimum = max(
            0.5,
            float(timing.get("minimum_scene_seconds", 1.8)),
        )
        narration_durations = [
            self._audio_duration(path) for path in audio_files
        ]

        def total_at(speed: float, tail: float) -> float:
            return sum(
                max(minimum, duration / speed + tail)
                for duration in narration_durations
            )

        natural_total = total_at(1.0, normal_tail)
        info: dict[str, Any] = {
            "requested": requested,
            "applied": False,
            "target_seconds": target,
            "natural_duration_seconds": round(natural_total, 3),
            "eligible_max_seconds": round(
                target * (1.0 + overrun_ratio),
                3,
            ),
            "maximum_speed_factor": max_speed,
            "speed_factor": 1.0,
            "estimated_duration_seconds": round(natural_total, 3),
            "tail_seconds": normal_tail,
            "reason": "natural_speed_selected",
        }
        if not requested:
            return audio_files, info
        if natural_total <= target + 0.05:
            info["reason"] = "already_within_target"
            return audio_files, info
        if natural_total > target * (1.0 + overrun_ratio) + 0.05:
            info["reason"] = "over_20_percent_limit"
            self._comment(
                "VoiceProducer",
                (
                    f"60초 자동 맞춤을 요청했지만 자연 길이가 {natural_total:.1f}초로 "
                    f"{target * (1.0 + overrun_ratio):.0f}초를 넘습니다. "
                    "말이 지나치게 빨라지지 않도록 자연 속도를 유지합니다."
                ),
            )
            return audio_files, info
        if total_at(max_speed, fitted_tail) > target + 0.05:
            info["reason"] = "maximum_speed_still_over_target"
            self._comment(
                "VoiceProducer",
                (
                    f"최대 {max_speed:.1f}배로도 60초에 자연스럽게 맞출 수 없어 "
                    "원래 속도를 유지합니다."
                ),
            )
            return audio_files, info

        low = 1.0
        high = max_speed
        for _ in range(40):
            middle = (low + high) / 2
            if total_at(middle, fitted_tail) > target:
                low = middle
            else:
                high = middle
        speed_factor = high
        fitted_dir = run_dir / "audio" / "duration_fitted"
        fitted_dir.mkdir(parents=True, exist_ok=True)
        fitted_files: list[Path] = []
        self._state("VoiceProducer", "working")
        for index, source in enumerate(audio_files, start=1):
            destination = fitted_dir / source.name
            self._run_ffmpeg(
                [
                    "-i",
                    str(source),
                    "-filter:a",
                    f"atempo={speed_factor:.6f}",
                    "-c:a",
                    "pcm_s16le",
                    str(destination),
                ]
            )
            fitted_files.append(destination)
            self._progress(
                "VoiceProducer",
                round(index / len(audio_files) * 100),
                (
                    f"60초 자동 맞춤을 위해 {index}/{len(audio_files)} 장면의 "
                    "말 속도를 조절하고 있습니다."
                ),
            )
        actual_total = sum(
            max(minimum, self._audio_duration(path) + fitted_tail)
            for path in fitted_files
        )
        info.update(
            {
                "applied": True,
                "speed_factor": round(speed_factor, 4),
                "estimated_duration_seconds": round(actual_total, 3),
                "tail_seconds": fitted_tail,
                "reason": "fitted_to_target",
            }
        )
        self._comment(
            "VoiceProducer",
            (
                f"자연 길이 {natural_total:.1f}초를 약 {actual_total:.1f}초로 맞추기 위해 "
                f"TTS를 {speed_factor:.2f}배로 조절했습니다."
            ),
        )
        self._state("VoiceProducer", "idle")
        return fitted_files, info

    def generate_background_music(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        duration: float,
    ) -> tuple[Path, dict[str, Any]]:
        selection_path = run_dir / "music_selection.json"
        source, selection = self._select_music_track(package)
        self._state("MusicProducer", "working")
        self._progress(
            "MusicProducer",
            40,
            f"로컬 원곡 ‘{source.stem}’을 변형 없이 연결하고 있습니다.",
        )
        selection.update(
            {
                "source_file": source.name,
                "source_path": str(source.relative_to(self.root)),
                "duration_seconds": round(duration, 3),
                "mix_volume": float(
                    self.config.get("music_library", {}).get("mix_volume", 0.20)
                ),
                "prepared_file": str(source.relative_to(self.root)),
                "preserve_original_track": True,
                "audio_processing": "원곡 편집 없음 · 최종 믹스에서 볼륨만 조절",
                "start_offset_seconds": 0,
            }
        )
        selection_path.write_text(
            json.dumps(selection, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._comment(
            "MusicProducer",
            (
                f"‘{source.stem}’ 원곡을 처음부터 그대로 사용합니다. "
                "정규화·페이드·음색 변형은 적용하지 않습니다."
            ),
        )
        self._progress("MusicProducer", 100, "원본 배경음악 연결을 완료했습니다.")
        self._state("MusicProducer", "idle")
        return source, selection

    def _select_music_track(
        self,
        package: KnowledgeProductionPackage,
    ) -> tuple[Path, dict[str, Any]]:
        library = self.config.get("music_library", {})
        music_dir = self.root / str(library.get("folder", "music"))
        tracks = list(library.get("tracks", []))
        available = {
            path.name: path
            for path in music_dir.glob("*")
            if path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}
        }
        if not available:
            raise FileNotFoundError(f"배경음악 파일이 없습니다: {music_dir}")
        searchable = " ".join(
            [
                package.selected_candidate.title,
                package.selected_candidate.category,
                package.selected_candidate.one_line_hook,
                package.script.full_narration,
            ]
        ).lower()
        best: tuple[int, int, dict[str, Any], list[str]] | None = None
        for index, track in enumerate(tracks):
            filename = str(track.get("file", ""))
            if filename not in available:
                continue
            matched = [
                str(keyword)
                for keyword in track.get("keywords", [])
                if str(keyword).lower() in searchable
            ]
            score = len(matched)
            candidate = (score, -index, track, matched)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        if best is None or best[0] == 0:
            fallback_name = str(library.get("fallback", ""))
            source = available.get(fallback_name) or next(iter(available.values()))
            mood = next(
                (
                    str(track.get("mood", "범용 미스터리"))
                    for track in tracks
                    if track.get("file") == source.name
                ),
                "범용 미스터리",
            )
            return source, {
                "track_title": source.stem,
                "mood": mood,
                "matched_keywords": [],
                "selection_reason": "특정 키워드가 없어 기본 미스터리 분위기의 곡을 선택했습니다.",
                "library_source": "project_music_folder",
            }
        _, _, track, matched = best
        source = available[str(track["file"])]
        return source, {
            "track_title": source.stem,
            "mood": str(track.get("mood", "미스터리")),
            "matched_keywords": matched,
            "selection_reason": (
                f"주제의 {', '.join(matched[:4])} 요소와 "
                f"‘{track.get('mood', '미스터리')}’ 분위기가 맞습니다."
            ),
            "library_source": "project_music_folder",
        }

    def render_video(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        frames: list[Path],
        audio_files: list[Path],
        durations: list[float],
        music: Path,
        stock_clips: dict[int, dict[str, Any]] | None = None,
        caption_overlays: dict[int, Path] | None = None,
    ) -> Path:
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        clips: list[Path] = []
        stock_clips = stock_clips or {}
        caption_overlays = caption_overlays or {}
        self._state("VideoRenderer", "working")
        for index, (scene, frame, audio, duration) in enumerate(
            zip(package.visual_package.scenes, frames, audio_files, durations),
            start=1,
        ):
            clip = clips_dir / f"clip_{index:02d}.mp4"
            percent = 45 + round(index / len(frames) * 45)
            self._progress(
                "VideoRenderer",
                percent,
                f"{index}번 장면과 음성을 합성하고 있습니다.",
            )
            overlay = caption_overlays.get(scene.scene_number)
            stock = stock_clips.get(scene.scene_number)
            stock_path = Path(str(stock.get("local_clip", ""))) if stock else None
            use_stock = (
                stock is not None
                and overlay is not None
                and stock_path is not None
                and stock_path.exists()
            )
            if use_stock:
                self._render_stock_scene_clip(
                    clip,
                    stock_path,
                    overlay,
                    frame,
                    audio,
                    duration,
                    min(float(stock.get("used_duration", 0)), duration),
                )
            else:
                if overlay is None:
                    # No overlay — render with image + audio only
                    sw = int(self.width * 1.15)
                    sh = int(self.height * 1.15)
                    mx = sw - self.width
                    my = sh - self.height
                    mt = index % 4
                    if mt == 0:
                        cx = f"trunc({mx}*(1-t/{duration:.3f}))"
                        cy = f"trunc({my}*(1-t/{duration:.3f}))"
                    elif mt == 1:
                        cx = f"trunc({mx}*t/{duration:.3f})"
                        cy = str(my // 2)
                    elif mt == 2:
                        cx = f"trunc({mx}*t/{duration:.3f}/2)"
                        cy = f"trunc({my}*t/{duration:.3f}/2)"
                    else:
                        cx = f"trunc({mx}*(1-t/{duration:.3f}))"
                        cy = str(my // 2)
                    self._run_ffmpeg(
                        [
                            "-loop", "1",
                            "-framerate", str(self.fps),
                            "-t", f"{duration:.3f}",
                            "-i", str(frame),
                            "-i", str(audio),
                            "-filter_complex",
                            (
                                f"[0:v]scale={sw}:{sh},"
                                f"crop={self.width}:{self.height}:{cx}:{cy},"
                                f"fps={self.fps},format=yuv420p[v];"
                                f"[1:a]volume=1.08,apad,atrim=0:{duration:.3f}[a]"
                            ),
                            "-map", "[v]",
                            "-map", "[a]",
                            "-t", f"{duration:.3f}",
                            "-r", str(self.fps), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                            "-c:a", "aac", "-b:a", "160k",
                            str(clip),
                        ]
                    )
                    clips.append(clip)
                    continue
                total_frames = max(2, int(math.ceil(duration * self.fps)))
                # 장면 번호에 따라 모션 방향을 번갈아 적용
                sw = int(self.width * 1.15)
                sh = int(self.height * 1.15)
                margin_x = sw - self.width
                margin_y = sh - self.height
                motion_type = index % 4
                if motion_type == 0:
                    # 줌인 (좌상→중앙)
                    crop_x = f"trunc({margin_x}*(1-t/{duration:.3f}))"
                    crop_y = f"trunc({margin_y}*(1-t/{duration:.3f}))"
                elif motion_type == 1:
                    # 좌→우 패닝
                    crop_x = f"trunc({margin_x}*t/{duration:.3f})"
                    crop_y = str(margin_y // 2)
                elif motion_type == 2:
                    # 줌아웃 (중앙→확대)
                    crop_x = f"trunc({margin_x}*t/{duration:.3f}/2)"
                    crop_y = f"trunc({margin_y}*t/{duration:.3f}/2)"
                else:
                    # 우→좌 패닝
                    crop_x = f"trunc({margin_x}*(1-t/{duration:.3f}))"
                    crop_y = str(margin_y // 2)
                self._run_ffmpeg(
                    [
                        "-loop",
                        "1",
                        "-framerate",
                        str(self.fps),
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        str(frame),
                        "-loop",
                        "1",
                        "-framerate",
                        str(self.fps),
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        str(overlay),
                        "-i",
                        str(audio),
                        "-filter_complex",
                        (
                            f"[0:v]scale={sw}:{sh},"
                            f"crop={self.width}:{self.height}:{crop_x}:{crop_y},"
                            f"fps={self.fps},format=yuv420p[base];"
                            f"[1:v]format=rgba,trim=duration={duration:.3f},"
                            "setpts=PTS-STARTPTS[ov];"
                            "[base][ov]overlay=0:0:shortest=1,format=yuv420p[v];"
                            f"[2:a]volume=1.08,apad,atrim=0:{duration:.3f}[a]"
                        ),
                        "-map",
                        "[v]",
                        "-map",
                        "[a]",
                        "-t",
                        f"{duration:.3f}",
                        "-r",
                        str(self.fps),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-crf",
                        "20",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "160k",
                        str(clip),
                    ]
                )
            clips.append(clip)
        concat = clips_dir / "concat.txt"
        concat.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in clips),
            encoding="utf-8",
        )
        narration_video = run_dir / "narration_short.mp4"
        self._run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-c",
                "copy",
                str(narration_video),
            ]
        )
        final_video = run_dir / "final_short.mp4"
        self._state("MusicProducer", "working")
        self._progress("MusicProducer", 90, "내레이션과 배경음악을 믹싱하고 있습니다.")
        self._run_ffmpeg(
            [
                "-i",
                str(narration_video),
                "-stream_loop",
                "-1",
                "-i",
                str(music),
                "-filter_complex",
                (
                    "[0:a]volume=1.0[v];"
                    f"[1:a]volume={float(self.config.get('music_library', {}).get('mix_volume', 0.20)):.3f}[m];"
                    "[v][m]amix=inputs=2:duration=first:dropout_transition=2[a]"
                ),
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-t",
                f"{sum(durations):.3f}",
                "-movflags",
                "+faststart",
                str(final_video),
            ]
        )
        expected_duration = sum(durations)
        actual_duration = self._media_duration(final_video)
        if actual_duration + 0.5 < expected_duration:
            raise RuntimeError(
                f"최종 영상이 {actual_duration:.2f}초에서 조기 종료되었습니다. "
                f"예상 길이는 {expected_duration:.2f}초입니다."
            )
        self._state("MusicProducer", "idle")
        self._progress("VideoRenderer", 100, "최종 MP4 쇼츠를 완성했습니다.")
        self._state("VideoRenderer", "idle")
        return final_video

    def _render_stock_scene_clip(
        self,
        output: Path,
        stock_clip: Path,
        caption_overlay: Path,
        fallback_frame: Path,
        audio: Path,
        scene_duration: float,
        stock_duration: float,
    ) -> None:
        remaining = max(0.0, scene_duration - stock_duration)
        if stock_duration <= 0:
            raise ValueError("스톡 클립 길이가 올바르지 않습니다.")
        if remaining > 0.05:
            self._run_ffmpeg(
                [
                    "-i",
                    str(stock_clip),
                    "-loop",
                    "1",
                    "-framerate",
                    str(self.fps),
                    "-i",
                    str(caption_overlay),
                    "-loop",
                    "1",
                    "-framerate",
                    str(self.fps),
                    "-i",
                    str(fallback_frame),
                    "-i",
                    str(audio),
                    "-filter_complex",
                    (
                        f"[0:v]scale={self.width}:{self.height}:"
                        "force_original_aspect_ratio=increase,"
                        f"crop={self.width}:{self.height},setsar=1,fps={self.fps},"
                        f"trim=duration={stock_duration:.3f},setpts=PTS-STARTPTS[sv];"
                        f"[1:v]format=rgba,trim=duration={scene_duration:.3f},"
                        "setpts=PTS-STARTPTS[ov];"
                        f"[2:v]scale={self.width}:{self.height},setsar=1,"
                        "zoompan=z='min(zoom+0.0006,1.12)':"
                        "x='iw/2-(iw/zoom/2)':y='trunc(ih/2-(ih/zoom/2))':"
                        f"d={max(2, int(math.ceil(remaining * self.fps)))}:"
                        f"s={self.width}x{self.height}:fps={self.fps},"
                        f"trim=duration={remaining:.3f},setpts=PTS-STARTPTS[still];"
                        "[sv][still]concat=n=2:v=1:a=0[base];"
                        "[base][ov]overlay=0:0:shortest=1,format=yuv420p[v];"
                        f"[3:a]volume=1.08,apad,atrim=0:{scene_duration:.3f}[a]"
                    ),
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-t",
                    f"{scene_duration:.3f}",
                    "-r",
                    str(self.fps),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    str(output),
                ]
            )
            return
        self._run_ffmpeg(
            [
                "-i",
                str(stock_clip),
                "-loop",
                "1",
                "-framerate",
                str(self.fps),
                "-i",
                str(caption_overlay),
                "-i",
                str(audio),
                "-filter_complex",
                (
                    f"[0:v]scale={self.width}:{self.height}:"
                    "force_original_aspect_ratio=increase,"
                    f"crop={self.width}:{self.height},setsar=1,fps={self.fps},"
                    f"trim=duration={scene_duration:.3f},setpts=PTS-STARTPTS[sv];"
                    f"[1:v]format=rgba,trim=duration={scene_duration:.3f},"
                    "setpts=PTS-STARTPTS[ov];"
                    "[sv][ov]overlay=0:0:shortest=1,format=yuv420p[v];"
                    f"[2:a]volume=1.08,apad,atrim=0:{scene_duration:.3f}[a]"
                ),
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-t",
                f"{scene_duration:.3f}",
                "-r",
                str(self.fps),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                str(output),
            ]
        )

    def create_thumbnail(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        image_path: Path,
    ) -> Path:
        canvas = ImageOps.fit(
            Image.open(image_path).convert("RGB"),
            (self.width, self.height),
            method=Image.Resampling.LANCZOS,
        )
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 65))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle(
            (45, 1180, self.width - 45, 1815),
            48,
            fill=(0, 0, 0, 205),
        )
        text = package.visual_package.thumbnail_text_candidates[0]
        font = self._font(True, 105)
        y = 1330
        for line in wrap(text, width=9)[:4]:
            box = draw.textbbox((0, 0), line, font=font, stroke_width=5)
            x = (self.width - (box[2] - box[0])) // 2
            draw.text(
                (x, y),
                line,
                font=font,
                fill="white",
                stroke_width=5,
                stroke_fill="black",
            )
            y += 135
        path = run_dir / "thumbnail.png"
        if path.exists():
            return path
        Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB").save(
            path,
            quality=95,
        )
        return path

    def _update_history(self, run_id: str, **changes: Any) -> None:
        path = self.root / "ideas" / "knowledge_items.json"
        history = json.loads(path.read_text(encoding="utf-8"))
        for item in history:
            if item.get("run_id") == run_id:
                item.update(changes)
                break
        path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _clear_render_derivatives(self, run_dir: Path) -> None:
        resolved = run_dir.resolve()
        expected_parent = (self.root / "outputs" / "knowledge").resolve()
        if expected_parent not in resolved.parents:
            raise RuntimeError("영상 재제작 경로가 올바르지 않습니다.")
        for directory in ("frames", "clips", "audio"):
            target = run_dir / directory
            if target.exists():
                shutil.rmtree(target)
        motion = run_dir / "media" / "motion_graphics"
        if motion.exists():
            shutil.rmtree(motion)
        if bool(
            self.visual_style.get(
                "regenerate_ai_images_on_style_rebuild",
                False,
            )
        ):
            generated = run_dir / "media" / "generated"
            if generated.exists():
                shutil.rmtree(generated)
        for filename in (
            "final_short.mp4",
            "narration_short.mp4",
            "thumbnail.png",
            "render_manifest.json",
        ):
            path = run_dir / filename
            if path.exists():
                path.unlink()

    def render(self, run_id: str, force_rebuild: bool = False) -> Path:
        run_dir, package = self._load_package(run_id)
        final_video = run_dir / "final_short.mp4"
        if force_rebuild:
            self._clear_render_derivatives(run_dir)
        if final_video.exists():
            self._comment("VideoRenderer", "이미 완성된 MP4가 있어 재사용합니다.")
            return final_video
        manifest_path = run_dir / "render_manifest.json"
        try:
            ending_additions = self.ensure_final_conclusion(package)
            if ending_additions:
                (run_dir / "final_knowledge_short.json").write_text(
                    package.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                (run_dir / "12_visual_package.json").write_text(
                    package.visual_package.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                self._comment(
                    "ProductionManager",
                    "마지막 결론 또는 질문이 장면 대사에서 빠져 있어 최종 장면에 복원했습니다.",
                )
            added_visual_beats = self.expand_long_scenes(package)
            if added_visual_beats:
                for media_directory in (
                    run_dir / "media" / "downloaded",
                    run_dir / "media" / "generated",
                    run_dir / "media" / "motion_graphics",
                    run_dir / "media" / "stock",
                ):
                    if media_directory.exists():
                        shutil.rmtree(media_directory)
                (run_dir / "final_knowledge_short.json").write_text(
                    package.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                (run_dir / "12_visual_package.json").write_text(
                    package.visual_package.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                (run_dir / "13_mixed_media_plan.json").write_text(
                    package.mixed_media_plan.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                self._comment(
                    "VideoRenderer",
                    f"긴 내레이션에 맞춰 화면을 {added_visual_beats}개 더 나눴습니다.",
                )
            scenes = package.visual_package.scenes
            fallback = 60.0 / len(scenes)
            planned_durations = [self._duration(scene, fallback) for scene in scenes]
            images, media_log = self.prepare_scene_images(run_dir, package)
            frames = self.compose_frames(run_dir, package, images)
            audio = self.generate_narration(run_dir, package)
            audio, duration_fit = self.fit_narration_speed(
                run_dir,
                package,
                audio,
            )
            durations, scene_timing = self.align_scene_durations(
                scenes,
                audio,
                planned_durations,
                tail_override=(
                    float(duration_fit["tail_seconds"])
                    if duration_fit["applied"]
                    else None
                ),
            )
            clip_selector = MediaClipSelector(
                self.root,
                self.ffmpeg,
                self.config.get("stock_clips", {}),
            )
            clip_plan = clip_selector.prepare(
                run_dir,
                package,
                durations,
                media_log,
                self.width,
                self.height,
                self.fps,
            )
            ai_scene_numbers = {
                int(item.get("scene_number", 0))
                for item in media_log
                if item.get("used_mode")
                in {"ai_reconstruction_fallback", "motion_graphics"}
            } - set(clip_plan["selected_by_scene"])
            caption_overlays = self.compose_caption_overlays(
                run_dir,
                package,
                ai_scene_numbers,
            )
            music, music_info = self.generate_background_music(
                run_dir,
                package,
                sum(durations),
            )
            thumbnail = self.create_thumbnail(run_dir, package, images[0])
            video = self.render_video(
                run_dir,
                package,
                frames,
                audio,
                durations,
                music,
                clip_plan["selected_by_scene"],
                caption_overlays,
            )
            stock_scene_numbers = set(clip_plan["selected_by_scene"])
            actual_count = sum(
                item["used_mode"] in {"licensed_real_media", "official_media"}
                or int(item.get("scene_number", 0)) in stock_scene_numbers
                for item in media_log
            )
            actual_percent = round(actual_count / len(media_log) * 100) if media_log else 0
            manifest = {
                "status": "rendered",
                "run_id": run_id,
                "style_version": int(self.visual_style.get("version", 2)),
                "final_video_file": video.name,
                "thumbnail_file": thumbnail.name,
                "scene_media": media_log,
                "actual_real_media_percent": actual_percent,
                "ai_voice_used": True,
                "background_music": music_info,
                "scene_timing": scene_timing,
                "duration_fit": duration_fit,
                "external_video_clips": {
                    "total_seconds": clip_plan["external_clip_total_seconds"],
                    "limit_seconds": clip_plan["external_clip_limit_seconds"],
                    "selected_scene_count": len(clip_plan["selected_by_scene"]),
                    "timeline_file": "timeline.json",
                    "sources_file": "sources.md",
                    "search_errors": clip_plan["search_errors"],
                },
                "planned_duration_seconds": round(sum(planned_durations), 3),
                "narration_aligned_duration_seconds": round(sum(durations), 3),
                "ending_guard": {
                    "applied": bool(ending_additions),
                    "added_lines": ending_additions,
                },
                "upload_performed": False,
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            package.video_assets = manifest
            package.upload_ready = False
            (run_dir / "final_knowledge_short.json").write_text(
                json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._update_history(
                run_id,
                production_status="video_ready",
                final_video=str(video.relative_to(self.root)),
                actual_real_media_percent=actual_percent,
                background_music_title=music_info.get("track_title", ""),
                background_music_file=music_info.get("source_file", ""),
                video_duration_seconds=round(sum(durations), 3),
                external_clip_seconds=clip_plan["external_clip_total_seconds"],
            )
            self._comment(
                "VideoRenderer",
                (
                    f"MP4 완성. 실제 허가 자료는 전체 장면의 {actual_percent}%에 사용했고, "
                    f"외부 영상 클립은 {clip_plan['external_clip_total_seconds']:.1f}초 사용했습니다."
                ),
            )
            return video
        except Exception as exc:
            manifest_path.write_text(
                json.dumps(
                    {"status": "failed", "run_id": run_id, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._update_history(
                run_id,
                production_status="video_failed",
                video_error=str(exc),
            )
            raise
        finally:
            for role in ("VideoRenderer", "VoiceProducer", "MusicProducer"):
                self._state(role, "idle")
