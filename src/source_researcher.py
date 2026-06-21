from __future__ import annotations

from pathlib import Path

from src.knowledge_models import (
    FactCheckReport,
    KnowledgeCandidate,
    SourceResearchReport,
)
from src.knowledge_runtime import KnowledgeRuntime


class SourceResearcher:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime = KnowledgeRuntime(self.root)

    def research(
        self,
        candidate: KnowledgeCandidate,
        fact_check: FactCheckReport,
    ) -> SourceResearchReport:
        reference_context = self.runtime.reference_context()
        payload = {
            "candidate": candidate.model_dump(mode="json"),
            "fact_check": fact_check.model_dump(mode="json"),
            "studio_reference": reference_context,
            "media_mix_rules": self.runtime.config.get("media_mix", {}),
        }
        return self.runtime.run_structured(
            "SourceResearcher",
            SourceResearchReport,
            payload,
            web=True,
            max_tokens=7000,
            max_turns=8,
        )
