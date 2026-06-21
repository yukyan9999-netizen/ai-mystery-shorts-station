from __future__ import annotations

from pathlib import Path

from src.knowledge_models import MixedMediaPlan, SourceResearchReport, VisualPackage
from src.knowledge_runtime import KnowledgeRuntime


class MixedMediaPlanner:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime = KnowledgeRuntime(self.root)

    def plan(
        self,
        visuals: VisualPackage,
        research: SourceResearchReport,
    ) -> MixedMediaPlan:
        reference_context = self.runtime.reference_context()
        payload = {
            "visual_package": visuals.model_dump(mode="json"),
            "source_research": research.model_dump(mode="json"),
            "media_mix_rules": self.runtime.config.get("media_mix", {}),
            "studio_reference": reference_context,
        }
        return self.runtime.run_structured(
            "MixedMediaPlanner",
            MixedMediaPlan,
            payload,
            web=False,
            max_tokens=6500,
            max_turns=5,
        )
