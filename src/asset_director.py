from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.knowledge_models import KnowledgeScene, KnowledgeScript
from src.knowledge_runtime import KnowledgeRuntime

logger = logging.getLogger(__name__)


class SceneAssetDirective(BaseModel):
    scene_number: int
    asset_type: str = Field(
        description="One of: search_image, search_video, generate_image, hybrid"
    )
    search_keywords_en: list[str] = Field(default_factory=list)
    generation_needed: bool = False
    reason: str = ""


class AssetDirectorOutput(BaseModel):
    scene_directives: list[SceneAssetDirective] = Field(default_factory=list)
    search_ratio: float = 0.0
    generate_ratio: float = 0.0


class AssetDirector:
    """Asset Director AI -- decides per-scene whether to search or generate images."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime = KnowledgeRuntime(root)
        self._prompt_template: str | None = None

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            self._prompt_template = (
                self.root / "agents" / "AssetDirector.md"
            ).read_text(encoding="utf-8")
        return self._prompt_template

    def plan(
        self,
        script: KnowledgeScript,
        scenes: list[KnowledgeScene],
        run_dir: Path,
    ) -> dict[int, dict]:
        """Return a mapping of scene_number -> asset plan dict.

        Calls gpt-4o-mini with the AssetDirector prompt. Results are cached
        in ``asset_director_plan.json`` under *run_dir*.
        """
        cache_path = run_dir / "asset_director_plan.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached:
                    return {int(k): v for k, v in cached.items()}
            except Exception:
                pass

        try:
            return self._call_director(script, scenes, run_dir, cache_path)
        except Exception:
            logger.warning(
                "AssetDirector failed -- falling back to default strategy",
                exc_info=True,
            )
            return {}

    def _call_director(
        self,
        script: KnowledgeScript,
        scenes: list[KnowledgeScene],
        run_dir: Path,
        cache_path: Path,
    ) -> dict[int, dict]:
        system_prompt = self._load_prompt()

        scene_data = []
        for s in scenes:
            scene_data.append({
                "scene_number": s.scene_number,
                "narration_text": s.narration,
                "visual_goal": s.visual_description or s.image_prompt,
            })

        user_payload = {
            "title": script.title,
            "category": script.category,
            "full_narration": script.full_narration,
            "scenes": scene_data,
            "total_scene_count": len(scenes),
            "output_format": (
                "Return a JSON object with keys: scene_directives (array), "
                "search_ratio (float), generate_ratio (float). "
                "Each scene_directive has: scene_number, asset_type, "
                "search_keywords_en, generation_needed, reason."
            ),
        }

        raw: AssetDirectorOutput = self.runtime.run_structured(
            "AssetDirector",
            AssetDirectorOutput,
            user_payload,
            web=False,
            max_tokens=4000,
            max_turns=3,
        )

        # Build result dict
        result: dict[int, dict[str, Any]] = {}
        for directive in raw.scene_directives:
            result[directive.scene_number] = {
                "asset_type": directive.asset_type,
                "search_keywords_en": directive.search_keywords_en,
                "generation_needed": directive.generation_needed,
                "reason": directive.reason,
            }

        # Save cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {str(k): v for k, v in result.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        logger.info(
            "AssetDirector plan: search_ratio=%.0f%% generate_ratio=%.0f%%",
            raw.search_ratio * 100,
            raw.generate_ratio * 100,
        )
        return result
