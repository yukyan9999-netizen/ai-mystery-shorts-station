from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.knowledge_models import KnowledgeProductionPackage, KnowledgeScene


@dataclass
class MediaClipCandidate:
    scene_number: int
    provider: str
    source_id: str
    title: str
    page_url: str
    media_url: str
    preview_url: str
    original_duration: float
    width: int
    height: int
    license_status: str
    license_url: str
    creator: str
    nasa_id: str
    query: str
    relevance_score: float
    usable_in_final: bool
    rejection_reason: str = ""
    svs_id: str = ""
    source_audio_removed: bool = True
    rights_note: str = ""


class MediaClipSelector:
    APPROVED_LICENSES = {
        "nasa_media_usage_guidelines",
        "nasa_svs_public_domain_visuals_audio_removed",
        "pexels_license",
        "pixabay_content_license",
    }
    VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
    STOP_WORDS = {
        "with",
        "from",
        "into",
        "showing",
        "scene",
        "vertical",
        "cinematic",
        "documentary",
        "dark",
        "realistic",
        "image",
        "visual",
        "background",
        "close",
        "view",
        "shot",
        "high",
        "quality",
        "text",
        "caption",
        "logo",
        "watermark",
    }
    KOREAN_SEARCH_MAP = {
        # 우주/천문
        "블랙홀": ["black hole", "space dark"],
        "우주": ["space", "cosmos stars"],
        "태양": ["sun", "solar flare"],
        "오로라": ["aurora", "northern lights"],
        "달": ["moon", "lunar surface"],
        "화성": ["mars", "mars surface"],
        "지구": ["earth", "planet earth"],
        "로켓": ["rocket launch"],
        "우주선": ["spacecraft", "space station"],
        "우주비행사": ["astronaut", "spacewalk"],
        "행성": ["planet", "solar system"],
        "별": ["stars", "night sky"],
        "은하": ["galaxy", "milky way"],
        "망원경": ["telescope", "observatory"],
        "위성": ["satellite", "orbit"],
        "소행성": ["asteroid", "meteor"],
        "혜성": ["comet", "tail comet"],
        "성운": ["nebula", "cosmic cloud"],
        "폭발": ["explosion", "supernova"],
        "섬광": ["bright flash", "light flash"],
        "충돌": ["impact", "collision"],
        # 자연/지구
        "바다": ["ocean", "deep ocean"],
        "심해": ["deep sea", "ocean abyss"],
        "폭풍": ["storm", "hurricane"],
        "번개": ["lightning", "thunderstorm"],
        "화산": ["volcano", "lava eruption"],
        "빙하": ["glacier", "ice arctic"],
        "지진": ["earthquake", "seismic"],
        "쓰나미": ["tsunami", "giant wave"],
        "사막": ["desert", "sand dunes"],
        "산": ["mountain", "peaks"],
        "숲": ["forest", "dense jungle"],
        "강": ["river", "waterfall"],
        "구름": ["clouds", "dramatic sky"],
        "비": ["rain", "heavy rain"],
        "눈": ["snow", "blizzard"],
        "불": ["fire", "flames burning"],
        "물": ["water", "water droplet"],
        "빛": ["light beam", "rays light"],
        # 역사
        "로마": ["ancient rome", "colosseum ruins"],
        "이집트": ["ancient egypt", "pyramid giza"],
        "피라미드": ["pyramid", "egyptian temple"],
        "중세": ["medieval", "castle fortress"],
        "유적": ["ancient ruins", "archaeological site"],
        "문서": ["ancient manuscript", "old scroll"],
        "전쟁": ["war", "battle field"],
        "무덤": ["tomb", "ancient burial"],
        "황제": ["emperor", "throne palace"],
        "칼": ["sword", "ancient weapon"],
        "갑옷": ["armor", "knight medieval"],
        "성벽": ["fortress wall", "castle wall"],
        "삼국지": ["ancient china", "chinese warrior"],
        "적벽": ["ancient battle", "fire ships war"],
        "제갈량": ["ancient china strategy", "war tactics"],
        "몽골": ["mongol", "steppe horse"],
        "칭기즈칸": ["mongol empire", "ancient warrior"],
        "고대": ["ancient civilization", "ruins temple"],
        # 과학/기술
        "공룡": ["dinosaur", "fossil museum"],
        "실험실": ["science laboratory", "research"],
        "뇌": ["brain scan", "neuroscience"],
        "DNA": ["dna helix", "genetics"],
        "세포": ["cell biology", "microscope"],
        "로봇": ["robot", "artificial intelligence"],
        "AI": ["artificial intelligence", "computer"],
        "핵": ["nuclear", "atomic energy"],
        "중력": ["gravity", "weightless floating"],
        "속도": ["speed", "motion fast"],
        "온도": ["temperature", "thermometer extreme"],
        # 인간/일상
        "수면": ["sleeping", "night bedroom"],
        "꿈": ["dreaming", "surreal"],
        "도시": ["city", "urban night"],
        "정전": ["blackout", "dark city"],
        "전력": ["power grid", "electricity"],
        "사람": ["crowd", "aerial city"],
        "군대": ["military", "soldiers march"],
        "배": ["ship", "sailing ocean"],
        "비행기": ["airplane", "aircraft flying"],
    }

    def __init__(
        self,
        root: Path,
        ffmpeg_path: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.ffmpeg = ffmpeg_path
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.max_total_seconds = float(self.config.get("max_total_seconds", 20))
        self.min_clip_seconds = float(self.config.get("min_clip_seconds", 1))
        self.max_clip_seconds = float(self.config.get("max_clip_seconds", 4))
        self.preferred_clip_seconds = float(
            self.config.get("preferred_clip_seconds", 3)
        )
        self.minimum_candidates = int(self.config.get("minimum_candidates", 3))
        self.max_source_reuse = int(self.config.get("max_source_reuse", 2))
        self.max_download_bytes = int(
            self.config.get("max_download_megabytes", 120) * 1024 * 1024
        )
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 18))
        # 전체 클립 선택에 쓸 최대 시간(초). 초과하면 나머지 장면은 이미지로 폴백.
        self.total_time_budget = float(self.config.get("total_time_budget_seconds", 90))
        # ffmpeg 다운로드/추출 1회당 최대 대기 시간(초).
        self.ffmpeg_timeout = int(self.config.get("ffmpeg_timeout_seconds", 45))
        providers = self.config.get("providers", {})
        self.svs_enabled = bool(providers.get("svs", {}).get("enabled", True))
        self.nasa_enabled = bool(providers.get("nasa", {}).get("enabled", True))
        self.pexels_enabled = bool(providers.get("pexels", {}).get("enabled", True))
        self.pixabay_enabled = bool(providers.get("pixabay", {}).get("enabled", True))
        self.pexels_key = os.getenv("PEXELS_API_KEY", "").strip()
        self.pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()

    def prepare(
        self,
        run_dir: Path,
        package: KnowledgeProductionPackage,
        durations: list[float],
        fallback_media: list[dict[str, Any]],
        width: int,
        height: int,
        fps: int,
    ) -> dict[str, Any]:
        scenes = package.visual_package.scenes
        stock_root = run_dir / "media" / "stock"
        candidates_dir = stock_root / "candidates"
        candidates_only_dir = stock_root / "candidates_only"
        originals_dir = stock_root / "originals"
        clips_dir = stock_root / "clips"
        for directory in (
            candidates_dir,
            candidates_only_dir,
            originals_dir,
            clips_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        fallback_by_scene = {
            int(item.get("scene_number", 0)): item for item in fallback_media
        }
        selected_by_scene: dict[int, dict[str, Any]] = {}
        timeline: list[dict[str, Any]] = []
        selected_sources: list[dict[str, Any]] = []
        search_errors: list[str] = []
        total_used = 0.0
        source_use_count: dict[str, int] = {}

        if not self.enabled:
            for scene, duration in zip(scenes, durations):
                timeline.append(
                    self._fallback_timeline_entry(
                        scene,
                        duration,
                        fallback_by_scene.get(scene.scene_number, {}),
                    )
                )
            result = self._result(
                selected_by_scene,
                timeline,
                selected_sources,
                search_errors,
                total_used,
            )
            self._write_outputs(run_dir, result)
            return result

        start_time = time.monotonic()
        budget_exceeded = False
        for scene, scene_duration in zip(scenes, durations):
            if budget_exceeded or (
                time.monotonic() - start_time > self.total_time_budget
            ):
                budget_exceeded = True
                timeline.append(
                    self._fallback_timeline_entry(
                        scene,
                        scene_duration,
                        fallback_by_scene.get(scene.scene_number, {}),
                    )
                )
                continue
            query = self._build_query(scene, package)
            candidates: list[MediaClipCandidate] = []
            provider_errors: list[str] = []
            for search in (
                self._search_nasa_svs,
                self._search_nasa,
                self._search_pexels,
                self._search_pixabay,
            ):
                try:
                    candidates.extend(search(scene.scene_number, query))
                except Exception as exc:
                    provider_errors.append(f"{search.__name__}: {exc}")
            if provider_errors:
                search_errors.extend(
                    f"scene {scene.scene_number}: {message}"
                    for message in provider_errors
                )

            candidates = self._deduplicate_and_rank(candidates)
            usable = [
                item
                for item in candidates
                if item.usable_in_final
                and item.license_status in self.APPROVED_LICENSES
                and item.page_url not in set(scene.excluded_source_urls)
            ]
            unclear_candidates = [
                item
                for item in candidates
                if not item.usable_in_final
                or item.license_status not in self.APPROVED_LICENSES
            ]
            candidate_payload = {
                "scene_number": scene.scene_number,
                "query": query,
                "candidate_count": len(usable),
                "candidates": [asdict(item) for item in usable],
                "minimum_candidates_required": self.minimum_candidates,
            }
            self._write_json(
                candidates_dir / f"scene_{scene.scene_number:02d}.json",
                candidate_payload,
            )
            unclear = [asdict(item) for item in unclear_candidates]
            if unclear:
                self._write_json(
                    candidates_only_dir / f"scene_{scene.scene_number:02d}.json",
                    {
                        "scene_number": scene.scene_number,
                        "reason": "라이선스 또는 권리 상태가 자동 사용 기준을 통과하지 못함",
                        "candidates": unclear,
                    },
                )

            selected: dict[str, Any] | None = None
            if len(usable) >= self.minimum_candidates:
                for candidate in usable:
                    reuse_key = f"{candidate.provider}:{candidate.source_id}"
                    if source_use_count.get(reuse_key, 0) >= self.max_source_reuse:
                        continue
                    remaining_budget = self.max_total_seconds - total_used
                    if remaining_budget < self.min_clip_seconds:
                        break
                    desired = min(
                        self.preferred_clip_seconds,
                        self.max_clip_seconds,
                        float(scene_duration),
                        remaining_budget,
                    )
                    if desired < self.min_clip_seconds:
                        continue
                    try:
                        prepared = self._prepare_candidate_clip(
                            candidate,
                            clips_dir,
                            originals_dir,
                            desired,
                            width,
                            height,
                            fps,
                        )
                    except Exception as exc:
                        search_errors.append(
                            f"scene {scene.scene_number} {reuse_key}: {exc}"
                        )
                        continue
                    if prepared is None:
                        continue
                    selected = prepared
                    source_use_count[reuse_key] = source_use_count.get(reuse_key, 0) + 1
                    total_used += float(prepared["used_duration"])
                    selected_by_scene[scene.scene_number] = prepared
                    selected_sources.append(prepared)
                    break

            fallback = fallback_by_scene.get(scene.scene_number, {})
            if selected:
                timeline.append(
                    {
                        "scene_number": scene.scene_number,
                        "narration": scene.narration,
                        "visual_type": "external_video_clip_then_fallback",
                        "media_source": selected["provider"],
                        "source_title": selected["title"],
                        "source_url": selected["page_url"],
                        "original_duration": selected["original_duration"],
                        "used_start_time": selected["used_start_time"],
                        "used_duration": selected["used_duration"],
                        "license_status": selected["license_status"],
                        "nasa_id": selected.get("nasa_id", ""),
                        "svs_id": selected.get("svs_id", ""),
                        "source_audio_removed": selected.get(
                            "source_audio_removed",
                            True,
                        ),
                        "fallback_visual": fallback.get(
                            "file",
                            scene.image_prompt,
                        ),
                    }
                )
            else:
                timeline.append(
                    self._fallback_timeline_entry(scene, scene_duration, fallback)
                )

        result = self._result(
            selected_by_scene,
            timeline,
            selected_sources,
            search_errors,
            total_used,
        )
        self._write_outputs(run_dir, result)
        return result

    def _result(
        self,
        selected_by_scene: dict[int, dict[str, Any]],
        timeline: list[dict[str, Any]],
        selected_sources: list[dict[str, Any]],
        search_errors: list[str],
        total_used: float,
    ) -> dict[str, Any]:
        return {
            "selected_by_scene": selected_by_scene,
            "timeline": timeline,
            "selected_sources": selected_sources,
            "search_errors": search_errors,
            "external_clip_total_seconds": round(total_used, 3),
            "external_clip_limit_seconds": self.max_total_seconds,
            "max_source_reuse": self.max_source_reuse,
        }

    def _write_outputs(self, run_dir: Path, result: dict[str, Any]) -> None:
        timeline_payload = {
            "external_clip_total_seconds": result["external_clip_total_seconds"],
            "external_clip_limit_seconds": result["external_clip_limit_seconds"],
            "max_source_reuse": result["max_source_reuse"],
            "scenes": result["timeline"],
        }
        self._write_json(run_dir / "timeline.json", timeline_payload)
        lines = [
            "# External Video Sources",
            "",
            (
                f"- 외부 스톡/NASA 클립 총 사용 시간: "
                f"{result['external_clip_total_seconds']:.3f}초 / "
                f"{result['external_clip_limit_seconds']:.0f}초"
            ),
            "- 사용하지 않은 후보는 `media/stock/candidates/`에 저장됩니다.",
            "- 권리가 불명확한 후보는 `media/stock/candidates_only/`에만 저장됩니다.",
            "",
        ]
        if not result["selected_sources"]:
            lines.append("외부 영상 클립을 사용하지 않았습니다. 기존 시각 자료로 폴백했습니다.")
        for index, source in enumerate(result["selected_sources"], start=1):
            lines.extend(
                [
                    f"## {index}. Scene {source['scene_number']} · {source['title']}",
                    "",
                    f"- Provider: {source['provider']}",
                    f"- Source URL: {source['page_url']}",
                    f"- Source ID: {source['source_id']}",
                    f"- NASA ID: {source.get('nasa_id') or '-'}",
                    f"- NASA SVS ID: {source.get('svs_id') or '-'}",
                    f"- Creator: {source.get('creator') or '-'}",
                    f"- License status: {source['license_status']}",
                    f"- License/usage URL: {source['license_url']}",
                    (
                        "- Source audio: Removed before editing"
                        if source.get("source_audio_removed", True)
                        else "- Source audio: Retained"
                    ),
                    f"- Rights note: {source.get('rights_note') or '-'}",
                    (
                        f"- Used segment: {source['used_start_time']:.3f}s ~ "
                        f"{source['used_start_time'] + source['used_duration']:.3f}s "
                        f"({source['used_duration']:.3f}s)"
                    ),
                    "",
                ]
            )
        (run_dir / "sources.md").write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )

    def _fallback_timeline_entry(
        self,
        scene: KnowledgeScene,
        duration: float,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "scene_number": scene.scene_number,
            "narration": scene.narration,
            "visual_type": fallback.get("used_mode", "existing_visual_pipeline"),
            "media_source": "existing_pipeline",
            "source_url": fallback.get("source_page_url", ""),
            "original_duration": 0,
            "used_start_time": 0,
            "used_duration": 0,
            "license_status": fallback.get("license_status", ""),
            "fallback_visual": fallback.get("file", scene.image_prompt),
            "scene_duration": round(float(duration), 3),
        }

    def _build_query(
        self,
        scene: KnowledgeScene,
        package: KnowledgeProductionPackage,
    ) -> str:
        combined = " ".join(
            [
                scene.visual_description,
                scene.image_prompt,
                scene.subtitle,
                scene.narration,
                package.selected_candidate.title,
            ]
        )
        mapped: list[str] = []
        for korean, english_terms in self.KOREAN_SEARCH_MAP.items():
            if korean in combined:
                mapped.extend(english_terms)
        ascii_words = [
            value.lower()
            for value in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", combined)
            if value.lower() not in self.STOP_WORDS
        ]
        ordered: list[str] = []
        for value in [*mapped, *ascii_words]:
            for token in value.split():
                if token not in ordered and token not in self.STOP_WORDS:
                    ordered.append(token)
        if not ordered:
            ordered = ["mystery", "science"]
        return " ".join(ordered[:6])

    def _search_nasa_svs(
        self,
        scene_number: int,
        query: str,
    ) -> list[MediaClipCandidate]:
        if not self.svs_enabled:
            return []
        search_url = "https://svs.gsfc.nasa.gov/api/search/?" + urllib.parse.urlencode(
            {
                "search": query,
                "limit": 5,
            }
        )
        payload = self._json_request(search_url)
        candidates: list[MediaClipCandidate] = []
        for result in payload.get("results", [])[:5]:
            svs_id = str(result.get("id", "")).strip()
            if not svs_id:
                continue
            try:
                page = self._json_request(
                    f"https://svs.gsfc.nasa.gov/api/{urllib.parse.quote(svs_id)}/"
                )
            except Exception:
                continue
            selected_video = self._select_svs_video(page)
            if not selected_video:
                continue
            title = str(
                page.get("title")
                or result.get("title")
                or f"NASA SVS visualization {svs_id}"
            ).strip()
            rights_text = self._svs_rights_text(page)
            uncertain, rights_note = self._svs_rights_status(rights_text)
            width = int(selected_video.get("width", 0) or 0)
            height = int(selected_video.get("height", 0) or 0)
            candidates.append(
                MediaClipCandidate(
                    scene_number=scene_number,
                    provider="NASA_SVS",
                    source_id=svs_id,
                    title=title,
                    page_url=str(
                        page.get("url")
                        or result.get("url")
                        or f"https://svs.gsfc.nasa.gov/{svs_id}/"
                    ),
                    media_url=str(selected_video.get("url", "")),
                    preview_url=str(
                        (page.get("main_image") or {}).get("url", "")
                    ),
                    original_duration=float(
                        selected_video.get("duration", 0) or 0
                    ),
                    width=width,
                    height=height,
                    license_status=(
                        "license_unclear"
                        if uncertain
                        else "nasa_svs_public_domain_visuals_audio_removed"
                    ),
                    license_url="https://svs.gsfc.nasa.gov/help/#frequently-asked-questions",
                    creator=self._svs_creator(page),
                    nasa_id="",
                    query=query,
                    relevance_score=self._score(
                        query,
                        f"{title} {result.get('description', '')}",
                        "NASA_SVS",
                        width,
                        height,
                    ),
                    usable_in_final=not uncertain,
                    rejection_reason=rights_note if uncertain else "",
                    svs_id=svs_id,
                    source_audio_removed=True,
                    rights_note=(
                        rights_note
                        or "SVS visual content is public domain unless noted otherwise; source audio is removed."
                    ),
                )
            )
        return candidates

    def _select_svs_video(self, page: dict[str, Any]) -> dict[str, Any] | None:
        videos: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                url = str(value.get("url", "")).strip()
                suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
                media_type = str(value.get("media_type", "")).lower()
                if url and suffix in self.VIDEO_SUFFIXES and media_type in {
                    "",
                    "movie",
                    "video",
                }:
                    videos.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(page.get("main_video"))
        visit(page.get("media_groups", []))
        unique: dict[str, dict[str, Any]] = {}
        for video in videos:
            url = str(video.get("url", "")).strip()
            if url:
                unique[url] = video
        if not unique:
            return None
        return sorted(unique.values(), key=self._svs_video_rank)[0]

    @staticmethod
    def _svs_video_rank(video: dict[str, Any]) -> tuple[int, int, int, int]:
        url = str(video.get("url", ""))
        suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
        width = int(video.get("width", 0) or 0)
        height = int(video.get("height", 0) or 0)
        pixels = width * height
        target_pixels = 1920 * 1080
        format_rank = {
            ".mp4": 0,
            ".m4v": 1,
            ".mov": 2,
            ".webm": 3,
        }.get(suffix, 4)
        too_small = int(max(width, height) < 720)
        too_large = int(pixels > 2560 * 1440)
        size_distance = abs(pixels - target_pixels) if pixels else target_pixels
        return format_rank, too_small, too_large, size_distance

    @staticmethod
    def _svs_creator(page: dict[str, Any]) -> str:
        people: list[str] = []
        for credit in page.get("credits", []) or []:
            role = str(credit.get("role", "")).strip()
            for person in credit.get("people", []) or []:
                name = str(person.get("name", "")).strip()
                employer = str(person.get("employer", "")).strip()
                if not name:
                    continue
                label = name
                if employer:
                    label += f" ({employer})"
                if role:
                    label = f"{role}: {label}"
                if label not in people:
                    people.append(label)
        return "; ".join(people[:4]) or "NASA Scientific Visualization Studio"

    @staticmethod
    def _svs_rights_text(page: dict[str, Any]) -> str:
        parts: list[str] = [
            str(page.get("title", "")),
            str(page.get("description", "")),
        ]
        for group in page.get("media_groups", []) or []:
            parts.extend(
                [
                    str(group.get("title", "")),
                    str(group.get("caption", "")),
                    str(group.get("description", "")),
                ]
            )
        return " ".join(parts)

    @staticmethod
    def _svs_rights_status(text: str) -> tuple[bool, str]:
        lower = " ".join(text.lower().split())
        markers = {
            "©": "페이지에 저작권 기호가 표시됨",
            "copyright": "페이지에 copyright 문구가 표시됨",
            "all rights reserved": "페이지에 all rights reserved 문구가 표시됨",
            "used with permission": "허가를 받아 사용한 제3자 자료가 포함됨",
            "rights managed": "권리 관리 자료가 포함됨",
            "not in the public domain": "퍼블릭 도메인이 아니라는 문구가 표시됨",
            "licensed footage": "별도 라이선스 영상이 포함됨",
            "licensed imagery": "별도 라이선스 이미지가 포함됨",
            "third-party footage": "제3자 영상이 포함됨",
            "third party footage": "제3자 영상이 포함됨",
        }
        for marker, reason in markers.items():
            if marker in lower:
                return True, reason
        return False, ""

    def _search_nasa(
        self,
        scene_number: int,
        query: str,
    ) -> list[MediaClipCandidate]:
        if not self.nasa_enabled:
            return []
        url = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode(
            {
                "q": query,
                "media_type": "video",
                "page_size": 5,
            }
        )
        payload = self._json_request(url)
        candidates: list[MediaClipCandidate] = []
        for item in payload.get("collection", {}).get("items", [])[:5]:
            data = (item.get("data") or [{}])[0]
            nasa_id = str(data.get("nasa_id", "")).strip()
            if not nasa_id:
                continue
            asset_url = f"https://images-api.nasa.gov/asset/{urllib.parse.quote(nasa_id)}"
            try:
                asset = self._json_request(asset_url)
            except Exception:
                continue
            hrefs = [
                str(entry.get("href", ""))
                for entry in asset.get("collection", {}).get("items", [])
                if str(entry.get("href", "")).lower().split("?")[0].endswith(
                    tuple(self.VIDEO_SUFFIXES)
                )
            ]
            if not hrefs:
                continue
            media_url = sorted(hrefs, key=self._nasa_variant_rank)[0]
            title = str(data.get("title", nasa_id))
            description = str(data.get("description", ""))
            rights_text = f"{title} {description}".lower()
            uncertain = any(
                marker in rights_text
                for marker in (
                    "copyright",
                    "courtesy of",
                    "all rights reserved",
                    "third party",
                )
            )
            candidates.append(
                MediaClipCandidate(
                    scene_number=scene_number,
                    provider="NASA",
                    source_id=nasa_id,
                    title=title,
                    page_url=f"https://images.nasa.gov/details/{urllib.parse.quote(nasa_id)}",
                    media_url=media_url,
                    preview_url=str((item.get("links") or [{}])[0].get("href", "")),
                    original_duration=0,
                    width=0,
                    height=0,
                    license_status=(
                        "license_unclear"
                        if uncertain
                        else "nasa_media_usage_guidelines"
                    ),
                    license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
                    creator=str(data.get("secondary_creator", "")),
                    nasa_id=nasa_id,
                    query=query,
                    relevance_score=self._score(query, title, "NASA", 0, 0),
                    usable_in_final=not uncertain,
                    rejection_reason=(
                        "NASA 설명에 제3자 저작권 가능성을 나타내는 표현이 있음"
                        if uncertain
                        else ""
                    ),
                )
            )
        return candidates

    def _search_pexels(
        self,
        scene_number: int,
        query: str,
    ) -> list[MediaClipCandidate]:
        if not self.pexels_enabled or not self.pexels_key:
            return []
        url = "https://api.pexels.com/v1/videos/search?" + urllib.parse.urlencode(
            {
                "query": query,
                "orientation": "portrait",
                "size": "medium",
                "per_page": 12,
            }
        )
        payload = self._json_request(
            url,
            headers={"Authorization": self.pexels_key},
        )
        candidates: list[MediaClipCandidate] = []
        for video in payload.get("videos", [])[:12]:
            files = [
                item
                for item in video.get("video_files", [])
                if item.get("link")
                and str(item.get("file_type", "")).lower() == "video/mp4"
            ]
            if not files:
                continue
            selected_file = sorted(
                files,
                key=lambda item: (
                    int(item.get("height", 0)) < int(item.get("width", 0)),
                    abs(int(item.get("height", 0)) - 1920)
                    + abs(int(item.get("width", 0)) - 1080),
                ),
            )[0]
            title = str(video.get("url", "")).rstrip("/").split("/")[-1]
            user = video.get("user") or {}
            candidates.append(
                MediaClipCandidate(
                    scene_number=scene_number,
                    provider="Pexels",
                    source_id=str(video.get("id", "")),
                    title=title or f"Pexels video {video.get('id', '')}",
                    page_url=str(video.get("url", "")),
                    media_url=str(selected_file.get("link", "")),
                    preview_url=str(video.get("image", "")),
                    original_duration=float(video.get("duration", 0) or 0),
                    width=int(selected_file.get("width", 0) or 0),
                    height=int(selected_file.get("height", 0) or 0),
                    license_status="pexels_license",
                    license_url="https://www.pexels.com/license/",
                    creator=str(user.get("name", "")),
                    nasa_id="",
                    query=query,
                    relevance_score=self._score(
                        query,
                        title,
                        "Pexels",
                        int(selected_file.get("width", 0) or 0),
                        int(selected_file.get("height", 0) or 0),
                    ),
                    usable_in_final=True,
                )
            )
        return candidates

    def _search_pixabay(
        self,
        scene_number: int,
        query: str,
    ) -> list[MediaClipCandidate]:
        if not self.pixabay_enabled or not self.pixabay_key:
            return []
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
            {
                "key": self.pixabay_key,
                "q": query[:100],
                "lang": "en",
                "video_type": "film",
                "safesearch": "true",
                "per_page": 12,
            }
        )
        payload = self._json_request(url)
        candidates: list[MediaClipCandidate] = []
        for video in payload.get("hits", [])[:12]:
            renditions = video.get("videos") or {}
            selected_file = next(
                (
                    renditions[name]
                    for name in ("medium", "small", "large", "tiny")
                    if (renditions.get(name) or {}).get("url")
                ),
                None,
            )
            if not selected_file:
                continue
            title = str(video.get("tags", "") or f"Pixabay video {video.get('id', '')}")
            candidates.append(
                MediaClipCandidate(
                    scene_number=scene_number,
                    provider="Pixabay",
                    source_id=str(video.get("id", "")),
                    title=title,
                    page_url=str(video.get("pageURL", "")),
                    media_url=str(selected_file.get("url", "")),
                    preview_url=str(selected_file.get("thumbnail", "")),
                    original_duration=float(video.get("duration", 0) or 0),
                    width=int(selected_file.get("width", 0) or 0),
                    height=int(selected_file.get("height", 0) or 0),
                    license_status="pixabay_content_license",
                    license_url="https://pixabay.com/service/license-summary/",
                    creator=str(video.get("user", "")),
                    nasa_id="",
                    query=query,
                    relevance_score=self._score(
                        query,
                        title,
                        "Pixabay",
                        int(selected_file.get("width", 0) or 0),
                        int(selected_file.get("height", 0) or 0),
                    ),
                    usable_in_final=True,
                )
            )
        return candidates

    def _prepare_candidate_clip(
        self,
        candidate: MediaClipCandidate,
        clips_dir: Path,
        originals_dir: Path,
        desired_duration: float,
        width: int,
        height: int,
        fps: int,
    ) -> dict[str, Any] | None:
        safe_id = re.sub(r"[^0-9A-Za-z_-]+", "_", candidate.source_id)[:80]
        provider_slug = re.sub(
            r"[^0-9A-Za-z_-]+",
            "_",
            candidate.provider.lower(),
        )
        original = originals_dir / f"{provider_slug}_{safe_id}.mp4"
        if not original.exists():
            self._download_file(candidate.media_url, original)
        original_duration = candidate.original_duration or self._probe_duration(original)
        if original_duration <= 0:
            return None
        used_duration = min(
            max(self.min_clip_seconds, desired_duration),
            self.max_clip_seconds,
            original_duration,
        )
        if used_duration < self.min_clip_seconds:
            return None
        start_time = self._deterministic_start(
            candidate.source_id,
            original_duration,
            used_duration,
        )
        clip = clips_dir / (
            f"scene_{candidate.scene_number:02d}_"
            f"{provider_slug}_{safe_id}.mp4"
        )
        self._extract_vertical_clip(
            original,
            clip,
            start_time,
            used_duration,
            width,
            height,
            fps,
        )
        result = asdict(candidate)
        result.update(
            {
                "original_duration": round(original_duration, 3),
                "used_start_time": round(start_time, 3),
                "used_duration": round(used_duration, 3),
                "local_original": str(original),
                "local_clip": str(clip),
            }
        )
        return result

    def _extract_vertical_clip(
        self,
        original: Path,
        clip: Path,
        start_time: float,
        duration: float,
        width: int,
        height: int,
        fps: int,
    ) -> None:
        completed = subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{start_time:.3f}",
                "-i",
                str(original),
                "-t",
                f"{duration:.3f}",
                "-an",
                "-vf",
                (
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p"
                ),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                str(clip),
            ],
            capture_output=True,
            text=True,
            timeout=self.ffmpeg_timeout,
        )
        if completed.returncode != 0 or not clip.exists():
            raise RuntimeError(completed.stderr.strip() or "외부 클립 추출 실패")

    def _download_file(self, url: str, destination: Path) -> None:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "KnowledgeShortsStudio/1.0"},
        )
        temp = destination.with_suffix(".download")
        total = 0
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response, temp.open("wb") as output:
                content_length = int(response.headers.get("Content-Length", "0") or 0)
                if content_length > self.max_download_bytes:
                    raise RuntimeError("원본 영상 파일이 다운로드 제한을 초과함")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_download_bytes:
                        raise RuntimeError("원본 영상 파일이 다운로드 제한을 초과함")
                    output.write(chunk)
            temp.replace(destination)
        finally:
            if temp.exists():
                temp.unlink()

    def _probe_duration(self, path: Path) -> float:
        completed = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=self.ffmpeg_timeout,
        )
        match = re.search(
            r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
            completed.stderr,
        )
        if not match:
            return 0
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    @staticmethod
    def _deterministic_start(
        source_id: str,
        original_duration: float,
        used_duration: float,
    ) -> float:
        available = max(0.0, original_duration - used_duration)
        if available <= 0:
            return 0.0
        digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
        ratio = int(digest[:8], 16) / 0xFFFFFFFF
        return min(available, available * ratio)

    @staticmethod
    def _nasa_variant_rank(url: str) -> tuple[int, int]:
        lower = url.lower()
        if "~small" in lower:
            return (0, len(url))
        if "~medium" in lower:
            return (1, len(url))
        if "~mobile" in lower:
            return (2, len(url))
        if "~orig" in lower:
            return (4, len(url))
        return (3, len(url))

    def _deduplicate_and_rank(
        self,
        candidates: list[MediaClipCandidate],
    ) -> list[MediaClipCandidate]:
        unique: dict[str, MediaClipCandidate] = {}
        for candidate in candidates:
            key = f"{candidate.provider}:{candidate.source_id}"
            current = unique.get(key)
            if current is None or candidate.relevance_score > current.relevance_score:
                unique[key] = candidate
        return sorted(
            unique.values(),
            key=lambda item: (
                item.usable_in_final,
                item.relevance_score,
                item.height >= item.width,
            ),
            reverse=True,
        )[:18]

    @staticmethod
    def _score(
        query: str,
        title: str,
        provider: str,
        width: int,
        height: int,
    ) -> float:
        query_tokens = {
            token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 2
        }
        title_tokens = set(re.findall(r"[a-z0-9]+", title.lower()))
        overlap = len(query_tokens & title_tokens)
        provider_bonus = {
            "NASA_SVS": 3.0,
            "NASA": 2.5,
            "Pexels": 1.5,
            "Pixabay": 1.0,
        }.get(provider, 0)
        portrait_bonus = 2.0 if height > width > 0 else 0.0
        resolution_bonus = 1.0 if max(width, height) >= 1080 else 0.0
        return round(overlap * 4 + provider_bonus + portrait_bonus + resolution_bonus, 3)

    def _json_request(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "KnowledgeShortsStudio/1.0",
                **(headers or {}),
            },
        )
        with urllib.request.urlopen(
            request,
            timeout=self.timeout_seconds,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
