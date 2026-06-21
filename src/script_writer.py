from __future__ import annotations

from pathlib import Path

from src.knowledge_models import (
    ConsequenceReport,
    CuriosityReport,
    GihwanReport,
    KnowledgeCandidate,
    KnowledgeScript,
    NarrativeArchitecture,
    ResearchDossier,
)
from src.knowledge_runtime import KnowledgeRuntime


class ScriptWriter:
    def __init__(self, root: Path) -> None:
        self.runtime = KnowledgeRuntime(root)

    def write(
        self,
        candidate: KnowledgeCandidate,
        scientific: ResearchDossier,
        historical: ResearchDossier,
        curiosity: CuriosityReport,
        consequences: ConsequenceReport,
        gihwan: GihwanReport,
        architecture: NarrativeArchitecture,
    ) -> KnowledgeScript:
        payload = {
            "candidate": candidate.model_dump(mode="json"),
            "scientific_research": scientific.model_dump(mode="json"),
            "historical_research": historical.model_dump(mode="json"),
            "curiosity_report": curiosity.model_dump(mode="json"),
            "consequence_report": consequences.model_dump(mode="json"),
            "gihwan_report": gihwan.model_dump(mode="json"),
            "narrative_architecture": architecture.model_dump(mode="json"),
            "studio_reference": self.runtime.reference_context(),
        }
        return self.runtime.run_structured(
            "KnowledgeScriptWriter",
            KnowledgeScript,
            payload,
            web=False,
            max_tokens=5000,
            max_turns=4,
        )

    def revise(
        self,
        candidate: KnowledgeCandidate,
        scientific: ResearchDossier,
        historical: ResearchDossier,
        curiosity: CuriosityReport,
        consequences: ConsequenceReport,
        gihwan: GihwanReport,
        architecture: NarrativeArchitecture,
        current_script: KnowledgeScript,
        user_feedback: str,
        feedback_history: list[str] | None = None,
    ) -> KnowledgeScript:
        previous_feedback = [
            item.strip()
            for item in (feedback_history or [])
            if item.strip() and item.strip() != user_feedback.strip()
        ]
        payload = {
            "task": "사람 검토자의 피드백을 반영해 최종 대본을 수정한다.",
            "current_user_feedback": user_feedback,
            "previous_applied_feedback": previous_feedback,
            "current_script": current_script.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "scientific_research": scientific.model_dump(mode="json"),
            "historical_research": historical.model_dump(mode="json"),
            "curiosity_report": curiosity.model_dump(mode="json"),
            "consequence_report": consequences.model_dump(mode="json"),
            "gihwan_report": gihwan.model_dump(mode="json"),
            "narrative_architecture": architecture.model_dump(mode="json"),
            "studio_reference": self.runtime.reference_context(),
            "revision_rules": [
                "current_user_feedback의 실행 가능한 요구를 빠짐없이 직접 반영한다.",
                "현재 피드백과 충돌하지 않는 previous_applied_feedback의 요구는 유지한다.",
                "현재 피드백과 이전 피드백이 충돌하면 현재 피드백을 우선한다.",
                "사용자가 요구하지 않은 새 행동, 소품, 경고 문구, 엉뚱한 사례를 임의로 추가하지 않는다.",
                "요구가 도입부 수정이면 실제 hook_0_3과 full_narration 첫 문장을 모두 바꾼다.",
                "요구가 삭제 또는 축약이면 비슷한 표현으로 되살리지 않는다.",
                "검증된 근거와 사실·가설 구분은 유지한다.",
                "피드백과 무관한 장점을 불필요하게 전부 바꾸지 않는다.",
                "full_narration에는 TTS가 읽을 문장만 넣는다.",
                "character_comment에 이번 피드백을 어느 문장에 어떻게 반영했는지 구체적으로 적는다.",
            ],
        }
        return self.runtime.run_structured(
            "KnowledgeScriptWriter",
            KnowledgeScript,
            payload,
            web=False,
            max_tokens=5000,
            max_turns=4,
        )
