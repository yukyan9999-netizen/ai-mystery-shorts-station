from __future__ import annotations

import json
import logging
from pathlib import Path

from src.knowledge_models import (
    FactCheckReport,
    KnowledgeScene,
    KnowledgeScript,
    NarrativeArchitecture,
    SourceResearchReport,
    VisualPackage,
)
from src.knowledge_runtime import KnowledgeRuntime
from src.visual_prompt_generator import VisualPromptGenerator

logger = logging.getLogger(__name__)


class VisualDirector:
    """Visual Director AI — context-aware scene card generator.

    Drop-in replacement for VisualPromptGenerator with richer, full-script-aware
    image prompts.  Falls back to the old generator on parse failure.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime = KnowledgeRuntime(root)
        self._prompt_template: str | None = None

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            self._prompt_template = (
                self.root / "agents" / "VisualDirector.md"
            ).read_text(encoding="utf-8")
        return self._prompt_template

    # ------------------------------------------------------------------
    # Public API (same signature as VisualPromptGenerator.generate)
    # ------------------------------------------------------------------

    def generate(
        self,
        script: KnowledgeScript,
        fact_check: FactCheckReport,
        architecture: NarrativeArchitecture | None,
        source_research: SourceResearchReport,
        *,
        run_dir: Path | None = None,
        desired_scenes: int = 10,
    ) -> VisualPackage:
        try:
            return self._generate_via_director(
                script,
                fact_check,
                architecture,
                source_research,
                run_dir=run_dir,
                desired_scenes=desired_scenes,
            )
        except Exception:
            logger.warning(
                "VisualDirector failed — falling back to VisualPromptGenerator",
                exc_info=True,
            )
            return VisualPromptGenerator(self.root).generate(
                script, fact_check, architecture, source_research
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_via_director(
        self,
        script: KnowledgeScript,
        fact_check: FactCheckReport,
        architecture: NarrativeArchitecture | None,
        source_research: SourceResearchReport,
        *,
        run_dir: Path | None,
        desired_scenes: int,
    ) -> VisualPackage:
        system_prompt = self._load_prompt()

        # Build the user payload sent to the model
        user_payload = {
            "title": script.title,
            "category": script.category,
            "full_script": script.full_narration,
            "timed_script": script.timed_script.model_dump(mode="json"),
            "fact_check_verdict": fact_check.verdict,
            "verified_claims": [
                vc.model_dump(mode="json") for vc in fact_check.verified_claims
            ],
            "required_caveats": fact_check.required_caveats,
            "source_research_summary": source_research.research_summary,
            "desired_scene_count": desired_scenes,
            "genre": script.category,
            "tone": "mystery_documentary",
            "output_format": (
                "Return a JSON object with these top-level keys: "
                "visual_bible, scene_cards, continuity_rules, "
                "quality_checklist, thumbnail_suggestions."
            ),
        }
        if architecture is not None:
            user_payload["narrative_architecture"] = architecture.model_dump(
                mode="json"
            )

        # Use run_structured with the VisualDirector agent prompt.
        # We cannot use output_type=VisualPackage directly because the
        # Visual Director schema is richer.  Instead, parse the raw JSON
        # ourselves (via a plain-dict wrapper model).
        from pydantic import BaseModel, Field
        from typing import Any

        class _DirectorRawOutput(BaseModel):
            visual_bible: dict[str, Any] = Field(default_factory=dict)
            scene_cards: list[dict[str, Any]] = Field(default_factory=list)
            continuity_rules: list[str] = Field(default_factory=list)
            quality_checklist: list[str] = Field(default_factory=list)
            thumbnail_suggestions: list[str] = Field(default_factory=list)

        raw: _DirectorRawOutput = self.runtime.run_structured(
            "VisualDirector",
            _DirectorRawOutput,
            user_payload,
            web=False,
            max_tokens=8000,
            max_turns=4,
        )

        # Save full plan for debugging
        if run_dir is not None:
            plan_path = run_dir / "visual_director_plan.json"
            plan_path.write_text(
                json.dumps(raw.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # Convert scene_cards → KnowledgeScene list
        scenes: list[KnowledgeScene] = []
        for card in raw.scene_cards:
            narration = card.get("narration_text", "")
            # Estimate time_range from narration length (~4 chars/sec in Korean)
            duration = max(2, len(narration) // 4)
            start = sum(
                max(2, len(c.get("narration_text", "")) // 4)
                for c in raw.scene_cards[: raw.scene_cards.index(card)]
            )
            scenes.append(
                KnowledgeScene(
                    scene_number=card.get("scene_number", len(scenes) + 1),
                    narration=narration,
                    subtitle=narration,
                    image_prompt=card.get("image_prompt", ""),
                    visual_description=card.get("visual_goal", ""),
                    time_range=f"{start}-{start + duration}초",
                )
            )

        if not scenes:
            raise ValueError("VisualDirector returned 0 scene_cards")

        # Build VisualPackage
        thumbnail_candidates = raw.thumbnail_suggestions[:5]
        while len(thumbnail_candidates) < 5:
            thumbnail_candidates.append(script.title)

        return VisualPackage(
            character_comment=(
                "시각 감독 AI가 전체 대본의 맥락을 분석해 "
                f"{len(scenes)}개 장면을 설계했습니다."
            ),
            scenes=scenes,
            thumbnail_text_candidates=thumbnail_candidates,
            hashtags=[f"#{script.category}", f"#{script.title[:20]}"],
            fact_check_checklist=raw.quality_checklist or [
                "사실 확인 완료",
            ],
        )
