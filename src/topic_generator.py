from __future__ import annotations

from datetime import date
from pathlib import Path

from src.knowledge_models import DailyTopicBatch
from src.knowledge_runtime import KnowledgeRuntime
from src.schedule_manager import ScheduleManager
from src.topic_library import TopicLibrary


class TopicGenerator:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime = KnowledgeRuntime(self.root)
        self.schedule = ScheduleManager(self.root)

    def generate(
        self,
        target: date,
        requested_direction: str = "",
    ) -> DailyTopicBatch:
        instruction = self.schedule.instruction_for(target)
        library = TopicLibrary(self.root)
        prompt = {
            **instruction,
            "requested_direction": requested_direction,
            "direction_rule": (
                "사용자 지정 방향을 최우선으로 따르고 가장 가까운 카테고리를 선택한다."
                if requested_direction
                else "사용자 지정 방향이 없으므로 요일별 자동 편성을 따른다."
            ),
            "previously_discovered_titles_to_avoid": library.known_titles(),
            "required_categories": [
                "역사 미스터리",
                "우주 미스터리",
                "고대문명과 놀라운 기술",
                "과학·자연 미스터리",
                "가상 시나리오",
            ],
            "selection_threshold": 70,
            "priority_threshold": 85,
            "output_rule": "후보를 정확히 3개 반환",
            "deduplication_rule": (
                "이전에 발굴한 제목과 같은 사건·인물·핵심 미스터리는 피한다. "
                "같은 큰 분야라도 다른 사건과 질문을 선택한다."
            ),
        }
        return self.runtime.run_structured(
            "TopicGenerator",
            DailyTopicBatch,
            prompt,
            web=True,
            max_turns=5,
        )
