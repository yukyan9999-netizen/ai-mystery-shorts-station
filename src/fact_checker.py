from __future__ import annotations

from pathlib import Path

from src.knowledge_models import (
    FactCheckReport,
    KnowledgeCandidate,
    KnowledgeScript,
    ResearchDossier,
)
from src.knowledge_runtime import KnowledgeRuntime


class FactChecker:
    def __init__(self, root: Path) -> None:
        self.runtime = KnowledgeRuntime(root)

    def check(
        self,
        candidate: KnowledgeCandidate,
        scientific: ResearchDossier,
        historical: ResearchDossier,
        script: KnowledgeScript,
    ) -> FactCheckReport:
        payload = {
            "candidate": candidate.model_dump(mode="json"),
            "scientific_evidence": scientific.model_dump(mode="json"),
            "historical_evidence": historical.model_dump(mode="json"),
            "script": script.model_dump(mode="json"),
            "instruction": (
                "가짜뉴스·혐오·실존 인물 비방·개인정보·직접적인 위험 유도만 검사하세요. "
                "그 밖의 가설, 상상, 미스터리 연출, 과장, 문체에는 개입하지 마세요."
            ),
        }
        report = self.runtime.run_structured(
            "FactChecker",
            FactCheckReport,
            payload,
            web=False,
            max_tokens=3500,
            max_turns=4,
        )
        if report.blocking_safety_issue:
            return report
        return report.model_copy(
            update={
                "verdict": "pass",
                "prohibited_or_removed_claims": [],
                "required_caveats": [],
                "required_on_screen_labels": [],
                "dramatization_allowed": True,
                "character_comment": (
                    "가짜뉴스·혐오·비방·위험 유도 여부만 확인했습니다. "
                    "중대한 문제가 없어 대본 표현에는 개입하지 않습니다."
                ),
            }
        )
