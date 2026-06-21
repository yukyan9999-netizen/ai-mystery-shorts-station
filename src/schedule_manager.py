from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from src.knowledge_models import KnowledgeCategory


WEEKDAY_CATEGORY: dict[int, KnowledgeCategory] = {
    0: "역사 미스터리",
    1: "우주 미스터리",
    2: "고대문명과 놀라운 기술",
    3: "과학·자연 미스터리",
    4: "가상 시나리오",
}


class ScheduleManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.items_path = self.root / "ideas" / "knowledge_items.json"

    def _history(self) -> list[dict]:
        if not self.items_path.exists():
            return []
        try:
            return json.loads(self.items_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def category_for(self, target: date) -> tuple[KnowledgeCategory, str]:
        if target.weekday() in WEEKDAY_CATEGORY:
            category = WEEKDAY_CATEGORY[target.weekday()]
            return category, f"{target.strftime('%A')} 고정 순환 편성"

        history = self._history()
        week_start = target - timedelta(days=target.weekday())
        recent = [
            item
            for item in history
            if str(item.get("production_date", "")) >= week_start.isoformat()
        ]

        if target.weekday() == 5:
            options: list[KnowledgeCategory] = ["역사 미스터리", "우주 미스터리"]
            totals = {
                category: max(
                    (
                        candidate.get("total_score", 0)
                        for batch in recent
                        if batch.get("category") == category
                        for candidate in batch.get("candidates", [])
                    ),
                    default=0,
                )
                for category in options
            }
            chosen = max(options, key=lambda category: totals[category])
            return chosen, "토요일 · 역사/우주 최근 고득점 카테고리"

        best = max(
            (
                candidate
                for batch in recent
                for candidate in batch.get("candidates", [])
                if candidate.get("selection_status") in {"candidate", "priority"}
            ),
            key=lambda candidate: candidate.get("total_score", 0),
            default=None,
        )
        if best and best.get("category") in WEEKDAY_CATEGORY.values():
            return best["category"], "일요일 · 이번 주 최고 점수 아이템 리메이크"
        return "역사 미스터리", "일요일 · 주간 기록이 없어 역사 미스터리로 시작"

    def instruction_for(self, target: date) -> dict[str, str]:
        category, reason = self.category_for(target)
        return {
            "production_date": target.isoformat(),
            "category": category,
            "schedule_reason": reason,
            "candidate_count": "3",
            "rule": "같은 날짜의 세 후보는 서로 다른 세부 주제를 사용한다.",
        }

