from __future__ import annotations

from pathlib import Path

from src.knowledge_models import (
    FactCheckReport,
    KnowledgeScript,
    NarrativeArchitecture,
    SourceResearchReport,
    VisualPackage,
)
from src.knowledge_runtime import KnowledgeRuntime


class VisualPromptGenerator:
    def __init__(self, root: Path) -> None:
        self.runtime = KnowledgeRuntime(root)

    def generate(
        self,
        script: KnowledgeScript,
        fact_check: FactCheckReport,
        architecture: NarrativeArchitecture | None,
        source_research: SourceResearchReport,
    ) -> VisualPackage:
        payload = {
            "script": script.model_dump(mode="json"),
            "fact_check": fact_check.model_dump(mode="json"),
            "source_research": source_research.model_dump(mode="json"),
            "studio_reference": self.runtime.reference_context(),
        }
        if architecture is not None:
            payload["narrative_architecture"] = architecture.model_dump(mode="json")
        return self.runtime.run_structured(
            "VisualPromptGenerator",
            VisualPackage,
            payload,
            web=False,
            max_tokens=6500,
            max_turns=4,
        )
