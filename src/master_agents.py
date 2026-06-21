from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.knowledge_models import (
    AudienceSimulation,
    ConsequenceReport,
    CuriosityReport,
    DailyTopicBatch,
    DirectTopicPlan,
    GihwanReport,
    KnowledgeCandidate,
    KnowledgeScript,
    NarrativeArchitecture,
    ResearchDossier,
    TrendReport,
)
from src.knowledge_runtime import KnowledgeRuntime
from src.topic_library import TopicLibrary


class MasterAgentRunner:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime = KnowledgeRuntime(self.root)

    def run(
        self,
        role: str,
        output_type: type[BaseModel],
        payload: dict[str, Any],
        *,
        web: bool = False,
        max_tokens: int = 6000,
        max_turns: int = 5,
    ) -> BaseModel:
        payload = {
            **payload,
            "studio_reference": self.runtime.reference_context(),
        }
        return self.runtime.run_structured(
            role,
            output_type,
            payload,
            web=web,
            max_tokens=max_tokens,
            max_turns=max_turns,
        )


class TrendAnalyst:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def analyze(
        self,
        target: date,
        schedule: dict[str, Any],
        requested_direction: str,
    ) -> TrendReport:
        return self.runner.run(
            "TrendAnalyst",
            TrendReport,
            {
                "production_date": target.isoformat(),
                "schedule": schedule,
                "requested_direction": requested_direction,
                "rule": (
                    "실제 검색에서 확인되는 흐름만 사용하고, 조회수나 유행 수치를 "
                    "확인할 수 없으면 수치를 만들어내지 않는다."
                ),
            },
            web=True,
            max_tokens=6000,
            max_turns=7,
        )


class TopicHunter:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runner = MasterAgentRunner(self.root)

    def hunt(
        self,
        target: date,
        schedule: dict[str, Any],
        trend_report: TrendReport,
        requested_direction: str,
    ) -> DailyTopicBatch:
        topic_policy = self.runner.runtime.config.get("topic_policy", {})
        payload = {
            "production_date": target.isoformat(),
            "schedule": schedule,
            "requested_direction": requested_direction,
            "trend_report": trend_report.model_dump(mode="json"),
            "previously_discovered_titles_to_avoid": TopicLibrary(
                self.root
            ).known_titles(),
            "required_candidate_count": 3,
            "minimum_score": 70,
            "priority_score": 85,
            "topic_policy": topic_policy,
            "required_categories": [
                "역사 미스터리",
                "우주 미스터리",
                "고대문명과 놀라운 기술",
                "과학·자연 미스터리",
                "가상 시나리오",
            ],
            "golden_rule": (
                "검증 가능한 현실 하나에서 출발하되, 초등학교 고학년도 "
                "한 문장만 듣고 자신을 그 장면에 넣어 상상할 수 있어야 한다."
            ),
        }
        batch = self.runner.run(
            "TopicHunter",
            DailyTopicBatch,
            payload,
            web=True,
            max_tokens=6500,
            max_turns=7,
        )
        if not isinstance(batch, DailyTopicBatch):
            batch = DailyTopicBatch.model_validate(batch)
        rejected = [
            candidate
            for candidate in batch.candidates
            if candidate.selection_status == "rejected"
        ]
        if rejected and topic_policy.get("retry_with_simpler_angle", True):
            retry_payload = {
                **payload,
                "strict_simplicity_retry": True,
                "previous_rejected_candidates": [
                    {
                        "title": candidate.title,
                        "reason": candidate.rejection_reason,
                        "difficulty": candidate.audience_difficulty,
                        "background_seconds": candidate.required_background_seconds,
                        "unfamiliar_terms": candidate.unfamiliar_terms,
                        "score": candidate.total_score,
                    }
                    for candidate in rejected
                ],
                "manager_instruction": {
                    "urgent_instructions": [
                        "이전 후보를 쉬운 말로 고치는 수준이 아니라 더 쉬운 상황 중심 후보 3개를 새로 고르세요.",
                        "제목 42자, 배경 10초, 전문용어 2개, 총점 70점 기준을 모두 지키세요.",
                    ]
                },
            }
            batch = self.runner.run(
                "TopicHunter",
                DailyTopicBatch,
                retry_payload,
                web=True,
                max_tokens=5000,
                max_turns=4,
            )
            if not isinstance(batch, DailyTopicBatch):
                batch = DailyTopicBatch.model_validate(batch)
        remaining_rejected = [
            candidate.rejection_reason
            for candidate in batch.candidates
            if candidate.selection_status == "rejected"
        ]
        if remaining_rejected:
            raise RuntimeError(
                "쉬운 주제 기준을 통과한 후보 3개를 만들지 못했습니다: "
                + " / ".join(remaining_rejected)
            )
        return batch

    def refine_direct(
        self,
        target: date,
        schedule: dict[str, Any],
        user_topic: str,
    ) -> DirectTopicPlan:
        topic_policy = self.runner.runtime.config.get("topic_policy", {})
        payload = {
            "mode": "direct_topic_conversation",
            "production_date": target.isoformat(),
            "schedule": schedule,
            "user_topic": user_topic,
            "topic_policy": topic_policy,
            "instruction": (
                "사용자가 준 핵심 아이디어를 바꾸지 말고, 채널 마스터 규칙에 맞는 "
                "제작 가능한 한 개의 주제로 다듬어라. 후보 3개를 만들지 않는다. "
                "토픽헌터의 답변에는 무엇을 살리고 어떻게 확장했는지 자연스럽게 설명한다."
            ),
        }
        plan = self.runner.run(
            "TopicHunter",
            DirectTopicPlan,
            payload,
            web=True,
            max_tokens=5000,
            max_turns=6,
        )
        if not isinstance(plan, DirectTopicPlan):
            plan = DirectTopicPlan.model_validate(plan)
        direct_candidate = plan.candidate.model_dump(mode="python")
        direct_candidate["selection_override"] = "user_direct_topic"
        plan = plan.model_copy(
            update={
                "candidate": KnowledgeCandidate.model_validate(direct_candidate)
            }
        )
        if plan.candidate.selection_status == "rejected":
            retry_payload = {
                **payload,
                "strict_simplicity_retry": True,
                "previous_rejection_reason": plan.candidate.rejection_reason,
                "manager_instruction": {
                    "urgent_instructions": [
                        "사용자의 핵심 아이디어는 유지하세요.",
                        "제목 42자, 배경 10초, 전문용어 2개, 총점 70점 기준을 충족하세요.",
                        "정의 설명이 아니라 인간과 문명에 벌어질 장면으로 바꾸세요.",
                    ]
                },
            }
            plan = self.runner.run(
                "TopicHunter",
                DirectTopicPlan,
                retry_payload,
                web=True,
                max_tokens=4000,
                max_turns=4,
            )
            if not isinstance(plan, DirectTopicPlan):
                plan = DirectTopicPlan.model_validate(plan)
        if plan.candidate.selection_status == "rejected":
            raise RuntimeError(
                "직접 지정한 주제를 제작 가능한 형태로 다듬지 못했습니다: "
                + plan.candidate.rejection_reason
            )
        return plan


class ScientificResearcher:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def research(self, candidate: KnowledgeCandidate) -> ResearchDossier:
        return self.runner.run(
            "ScientificResearcher",
            ResearchDossier,
            {"candidate": candidate.model_dump(mode="json")},
            web=True,
            max_tokens=7500,
            max_turns=8,
        )


class HistoricalResearcher:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def research(self, candidate: KnowledgeCandidate) -> ResearchDossier:
        return self.runner.run(
            "HistoricalResearcher",
            ResearchDossier,
            {"candidate": candidate.model_dump(mode="json")},
            web=True,
            max_tokens=7500,
            max_turns=8,
        )


class HumanCuriosityDirector:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def transform(
        self,
        candidate: KnowledgeCandidate,
        scientific: ResearchDossier,
        historical: ResearchDossier,
    ) -> CuriosityReport:
        return self.runner.run(
            "HumanCuriosityDirector",
            CuriosityReport,
            {
                "candidate": candidate.model_dump(mode="json"),
                "scientific_research": scientific.model_dump(mode="json"),
                "historical_research": historical.model_dump(mode="json"),
            },
            max_tokens=5500,
        )


class FutureConsequenceSimulator:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def simulate(
        self,
        candidate: KnowledgeCandidate,
        scientific: ResearchDossier,
        historical: ResearchDossier,
        curiosity: CuriosityReport,
    ) -> ConsequenceReport:
        return self.runner.run(
            "FutureConsequenceSimulator",
            ConsequenceReport,
            {
                "candidate": candidate.model_dump(mode="json"),
                "scientific_research": scientific.model_dump(mode="json"),
                "historical_research": historical.model_dump(mode="json"),
                "curiosity_report": curiosity.model_dump(mode="json"),
            },
            max_tokens=6000,
        )


class GihwanAgent:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def amplify(
        self,
        candidate: KnowledgeCandidate,
        curiosity: CuriosityReport,
        consequences: ConsequenceReport,
    ) -> GihwanReport:
        return self.runner.run(
            "GihwanAgent",
            GihwanReport,
            {
                "candidate": candidate.model_dump(mode="json"),
                "curiosity_report": curiosity.model_dump(mode="json"),
                "consequence_report": consequences.model_dump(mode="json"),
            },
            max_tokens=5000,
        )


class MysteryArchitect:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def build(
        self,
        candidate: KnowledgeCandidate,
        scientific: ResearchDossier,
        historical: ResearchDossier,
        curiosity: CuriosityReport,
        consequences: ConsequenceReport,
        gihwan: GihwanReport,
    ) -> NarrativeArchitecture:
        return self.runner.run(
            "MysteryArchitect",
            NarrativeArchitecture,
            {
                "candidate": candidate.model_dump(mode="json"),
                "scientific_research": scientific.model_dump(mode="json"),
                "historical_research": historical.model_dump(mode="json"),
                "curiosity_report": curiosity.model_dump(mode="json"),
                "consequence_report": consequences.model_dump(mode="json"),
                "gihwan_report": gihwan.model_dump(mode="json"),
            },
            max_tokens=6000,
        )


class AudienceSimulator:
    def __init__(self, root: Path) -> None:
        self.runner = MasterAgentRunner(root)

    def evaluate(
        self,
        script: KnowledgeScript,
        architecture: NarrativeArchitecture,
    ) -> AudienceSimulation:
        return self.runner.run(
            "AudienceSimulator",
            AudienceSimulation,
            {
                "script": script.model_dump(mode="json"),
                "narrative_architecture": architecture.model_dump(mode="json"),
            },
            max_tokens=4500,
        )
