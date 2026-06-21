from __future__ import annotations

import re
from pathlib import Path

from src.knowledge_models import (
    KnowledgeProductionPackage,
    VideoRevisionPlan,
    VideoSceneRevision,
)
from src.knowledge_runtime import KnowledgeRuntime


class VideoRevisionDirector:
    def __init__(self, root: Path) -> None:
        self.runtime = KnowledgeRuntime(root)

    def plan(
        self,
        package: KnowledgeProductionPackage,
        feedback: str,
    ) -> VideoRevisionPlan:
        direct_changes: list[VideoSceneRevision] = []
        valid_numbers = {
            scene.scene_number for scene in package.visual_package.scenes
        }
        for part in re.split(r"(?=(?<!\d)\d+\s*번)", feedback):
            match = re.search(r"(?<!\d)(\d+)\s*번", part)
            if not match:
                continue
            number = int(match.group(1))
            if number not in valid_numbers:
                continue
            lower = part.lower()
            if any(word in part for word in ("생성되지", "안 나", "비어", "누락")):
                action = "recover_missing"
            elif "영상" in part and any(
                word in part for word in ("교체", "바꿔", "다른")
            ):
                action = "prefer_video"
            elif any(word in part for word in ("사진", "그림", "이미지")):
                action = "prefer_image"
            else:
                action = "replace_visual"

            if "nasa" in lower or "공식" in part:
                preferred = "official_media"
            elif "영상" in part:
                preferred = "external_video"
            elif "ai" in lower or any(
                word in part for word in ("그림", "이미지")
            ):
                preferred = "ai_image"
            else:
                preferred = "any"
            direct_changes.append(
                VideoSceneRevision(
                    scene_number=number,
                    action=action,
                    instruction=part.strip(" ,./"),
                    preferred_media=preferred,
                )
            )

        if direct_changes:
            numbers = ", ".join(str(item.scene_number) for item in direct_changes)
            return VideoRevisionPlan(
                character_comment=f"{numbers}번 장면의 화면 자료만 교체하겠습니다.",
                summary=feedback,
                scene_changes=direct_changes,
            )

        scenes = [
            {
                "scene_number": scene.scene_number,
                "time_range": scene.time_range,
                "subtitle": scene.subtitle,
                "narration": scene.narration,
                "visual_description": scene.visual_description,
            }
            for scene in package.visual_package.scenes
        ]
        return self.runtime.run_structured(
            "VideoRevisionDirector",
            VideoRevisionPlan,
            {
                "task": "완성 영상 피드백을 장면별 영상 수정 계획으로 변환한다.",
                "user_feedback": feedback,
                "available_scenes": scenes,
                "instruction": (
                    "대본과 음성은 유지하고 화면 자료만 수정하세요. "
                    "지목한 장면 번호를 정확히 사용하세요."
                ),
            },
            web=False,
            max_tokens=3000,
            max_turns=3,
        )
