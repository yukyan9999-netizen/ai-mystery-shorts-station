from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.knowledge_models import DailyTopicBatch


class TopicLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / "ideas" / "topic_library.json"

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def normalize_title(title: str) -> str:
        return re.sub(r"[^0-9a-z가-힣]+", "", title.lower())

    def known_titles(self, limit: int = 150) -> list[str]:
        return [str(item.get("title", "")) for item in self.load()[-limit:]]

    def add_batch(
        self,
        batch: DailyTopicBatch,
        run_id: str,
        requested_direction: str = "",
    ) -> dict[str, int]:
        items = self.load()
        processed_runs = {
            str(run)
            for item in items
            for run in (
                item.get("discovery_run_ids")
                or [item.get("first_run_id", "")]
            )
            if run
        }
        if run_id in processed_runs:
            return {"added": 0, "duplicates": 0, "total": len(items)}
        by_key = {
            self.normalize_title(str(item.get("title", ""))): item
            for item in items
        }
        added = 0
        duplicates = 0
        now = datetime.now().isoformat(timespec="seconds")
        for index, candidate in enumerate(batch.candidates):
            payload = candidate.model_dump(mode="json")
            key = self.normalize_title(candidate.title)
            existing = by_key.get(key)
            if existing is not None:
                existing["last_discovered_at"] = now
                existing["last_run_id"] = run_id
                existing["occurrence_count"] = int(existing.get("occurrence_count", 1)) + 1
                run_ids = list(
                    existing.get("discovery_run_ids")
                    or [existing.get("first_run_id", "")]
                )
                if run_id not in run_ids:
                    run_ids.append(run_id)
                existing["discovery_run_ids"] = [value for value in run_ids if value]
                existing["highest_score"] = max(
                    int(existing.get("highest_score", 0)),
                    candidate.total_score,
                )
                if requested_direction:
                    directions = list(existing.get("requested_directions") or [])
                    if requested_direction not in directions:
                        directions.append(requested_direction)
                    existing["requested_directions"] = directions
                duplicates += 1
                continue
            item = {
                "topic_id": f"{run_id}-{index + 1}",
                **payload,
                "discovered_at": now,
                "last_discovered_at": now,
                "first_run_id": run_id,
                "last_run_id": run_id,
                "discovery_run_ids": [run_id],
                "requested_directions": (
                    [requested_direction] if requested_direction else []
                ),
                "discovery_mode": "user_direction" if requested_direction else "automatic",
                "library_status": "unused",
                "selected_count": 0,
                "occurrence_count": 1,
                "highest_score": candidate.total_score,
            }
            items.append(item)
            by_key[key] = item
            added += 1
        self.save(items)
        return {"added": added, "duplicates": duplicates, "total": len(items)}

    def mark_selected(self, title: str, run_id: str) -> None:
        items = self.load()
        key = self.normalize_title(title)
        for item in items:
            if self.normalize_title(str(item.get("title", ""))) == key:
                item["library_status"] = "selected"
                item["selected_count"] = int(item.get("selected_count", 0)) + 1
                item["last_selected_at"] = datetime.now().isoformat(timespec="seconds")
                item["last_selected_run_id"] = run_id
                break
        self.save(items)

    def sync_history(self) -> None:
        history_path = self.root / "ideas" / "knowledge_items.json"
        if not history_path.exists():
            return
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        known_runs = {
            str(run)
            for item in self.load()
            for run in (
                item.get("discovery_run_ids")
                or [item.get("first_run_id", "")]
            )
            if run
        }
        for entry in history if isinstance(history, list) else []:
            run_id = str(entry.get("run_id", ""))
            if not run_id or run_id in known_runs:
                continue
            try:
                batch = DailyTopicBatch.model_validate(entry)
            except Exception:
                continue
            self.add_batch(
                batch,
                run_id,
                str(entry.get("requested_direction", "")),
            )
            selected_title = str(entry.get("selected_title", ""))
            if selected_title:
                self.mark_selected(selected_title, run_id)
            known_runs.add(run_id)
