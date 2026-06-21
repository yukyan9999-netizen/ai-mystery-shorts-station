from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import yaml
from agents import Agent, ModelSettings, Runner, trace
from dotenv import load_dotenv
from pydantic import BaseModel

from src.models import (
    CharacterPlan,
    ComedyRevision,
    ComplianceReview,
    EpisodeIdea,
    FinalEpisode,
    HumanApproval,
    ManagementIntervention,
    ProgrammingDirection,
    ShortsPlan,
    StoryDraft,
    YouTubePackage,
)
from src.progress import heartbeat

T = TypeVar("T", bound=BaseModel)


@dataclass
class Paths:
    root: Path

    @property
    def agents(self) -> Path:
        return self.root / "agents"

    @property
    def ideas(self) -> Path:
        return self.root / "ideas" / "episode_ideas.json"

    @property
    def drafts(self) -> Path:
        return self.root / "outputs" / "drafts"

    @property
    def final(self) -> Path:
        return self.root / "outputs" / "final"

    @property
    def logs(self) -> Path:
        return self.root / "logs"


class BroadcastRoom:
    def __init__(
        self, root: Path, live: bool = False, resume_run_id: str | None = None
    ) -> None:
        self.paths = Paths(root.resolve())
        self.live = live
        load_dotenv(self.paths.root / ".env")
        load_dotenv(self.paths.root / ".env.local", override=True)
        self.config = yaml.safe_load((self.paths.root / "config.yaml").read_text(encoding="utf-8"))
        self.model = self.config["model"]
        self.max_revisions = int(self.config.get("max_revision_loops", 3))
        self.max_turns = int(self.config.get("max_turns_per_agent", 4))
        self.heartbeat_seconds = float(self.config.get("heartbeat_seconds", 10))
        self.agent_timeout_seconds = float(
            self.config.get("agent_timeout_seconds", 60)
        )
        self.manager_intervention_timeout_seconds = float(
            self.config.get("manager_intervention_timeout_seconds", 10)
        )
        self.expedite_timeout_seconds = float(
            self.config.get("expedite_timeout_seconds", 45)
        )
        self.expedite_max_tokens = int(self.config.get("expedite_max_tokens", 2500))
        self.run_id = resume_run_id or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.run_dir = self.paths.drafts / self.run_id
        if resume_run_id:
            if not self.run_dir.is_dir():
                raise FileNotFoundError(
                    f"재개할 실행 폴더를 찾을 수 없습니다: {self.run_dir}"
                )
        else:
            self.run_dir.mkdir(parents=True, exist_ok=False)
        self.transcript_path = self.run_dir / "agent_transcript.jsonl"
        self.paths.final.mkdir(parents=True, exist_ok=True)
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        self.logger = self._build_logger()

    def _broadcast(self, event: str, role: str, content: Any) -> None:
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "role": role,
            "content": content,
        }
        with self.transcript_path.open("a", encoding="utf-8") as transcript:
            transcript.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.live:
            if event == "comment":
                print(
                    "@@AGENT_COMMENT@@"
                    + json.dumps(
                        {"role": role, "comment": content},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return
            labels = {
                "input": "📨 업무 전달",
                "start": "🟡 업무 시작",
                "output": "✅ 결과 보고",
                "revision": "🔁 수정 요청",
                "notice": "📢 방송국 공지",
            }
            print(f"\n[{labels.get(event, event)}] {role}", flush=True)
            if content not in (None, "", {}):
                if isinstance(content, str):
                    print(content, flush=True)
                else:
                    print(
                        json.dumps(content, ensure_ascii=False, indent=2),
                        flush=True,
                    )

    def _build_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"broadcast-room-{self.run_id}")
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(
            self.paths.logs / f"{self.run_id}.log", encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        return logger

    def _prompt(self, role: str) -> str:
        return (self.paths.agents / f"{role}.md").read_text(encoding="utf-8")

    def _temperature(self, role: str) -> float | None:
        model_name = str(self.model).lower()
        models_without_temperature = ("gpt-5", "o1", "o3", "o4")
        if model_name.startswith(models_without_temperature):
            return None
        role_config = self.config.get("agents", {}).get(role, {})
        value = role_config.get("temperature", self.config.get("temperature"))
        return None if value is None else float(value)

    def _agent(
        self, role: str, output_type: type[T], expedited: bool = False
    ) -> Agent[Any]:
        temperature = self._temperature(role)
        model_name = str(self.model).lower()
        reasoning = (
            {"effort": "low"}
            if expedited and model_name.startswith(("gpt-5", "o1", "o3", "o4"))
            else None
        )
        settings = ModelSettings(
            temperature=temperature,
            reasoning=reasoning,
            verbosity="low" if expedited else None,
            max_tokens=self.expedite_max_tokens if expedited else None,
        )
        return Agent(
            name=role,
            instructions=self._prompt(role),
            model=self.model,
            model_settings=settings,
            output_type=output_type,
        )

    async def _run_with_timeout(
        self,
        role: str,
        output_type: type[T],
        payload: dict[str, Any],
        expedited: bool,
        timeout_seconds: float,
        manager_instruction: dict[str, Any] | None = None,
    ) -> Any:
        request_payload = dict(payload)
        if expedited:
            request_payload["manager_instruction"] = manager_instruction or {
                "urgent_instructions": [
                    "설명을 늘리지 말고 필수 판단만 수행하세요.",
                    "출력 스키마를 정확히 지키며 즉시 최종안을 제출하세요.",
                ]
            }
        return await asyncio.wait_for(
            Runner.run(
                self._agent(role, output_type, expedited=expedited),
                json.dumps(request_payload, ensure_ascii=False, indent=2),
                max_turns=2 if expedited else self.max_turns,
            ),
            timeout=timeout_seconds,
        )

    async def _manager_intervention(
        self, delayed_role: str, payload: dict[str, Any]
    ) -> ManagementIntervention:
        manager_payload = {
            "delayed_role": delayed_role,
            "elapsed_seconds": self.agent_timeout_seconds,
            "original_assignment": payload,
            "instruction": (
                "10초 안에 병목을 판단하고, 안전 필수사항은 유지하면서 "
                "담당자가 즉시 완료할 수 있는 긴급 지시를 작성하세요."
            ),
        }
        result = await asyncio.wait_for(
            Runner.run(
                self._agent(
                    "ProductionManager",
                    ManagementIntervention,
                    expedited=True,
                ),
                json.dumps(manager_payload, ensure_ascii=False, indent=2),
                max_turns=1,
            ),
            timeout=self.manager_intervention_timeout_seconds,
        )
        output = result.final_output
        if not isinstance(output, ManagementIntervention):
            output = ManagementIntervention.model_validate(output)
        return output

    def _run_agent(self, role: str, output_type: type[T], payload: dict[str, Any]) -> T:
        self.logger.info("Starting %s", role)
        self._broadcast("input", role, payload)
        self._broadcast("start", role, "담당 AI가 전달받은 자료를 검토하고 있습니다.")
        if self.live:
            print(
                "@@AGENT_STATE@@"
                + json.dumps(
                    {"role": role, "state": "working"},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        try:
            with heartbeat(
                self.live,
                role,
                self.heartbeat_seconds,
                writer=lambda message: print(message, flush=True),
            ):
                result = asyncio.run(
                    self._run_with_timeout(
                        role,
                        output_type,
                        payload,
                        expedited=False,
                        timeout_seconds=self.agent_timeout_seconds,
                    )
                )
        except TimeoutError:
            self.logger.warning(
                "%s exceeded %.0f seconds; expedited retry",
                role,
                self.agent_timeout_seconds,
            )
            self._broadcast(
                "start",
                "ProductionManager",
                f"{role}의 지연 원인을 판단하고 긴급 지시를 작성합니다.",
            )
            try:
                intervention = asyncio.run(
                    self._manager_intervention(role, payload)
                )
                manager_instruction = intervention.model_dump(mode="json")
                self._broadcast(
                    "output",
                    "ProductionManager → " + role,
                    manager_instruction,
                )
            except TimeoutError:
                manager_instruction = {
                    "delayed_role": role,
                    "bottleneck_assessment": "관리자 AI도 제한 시간을 초과하여 기본 긴급 지시 적용",
                    "keep_required": ["출력 스키마", "안전 및 검수 필수사항"],
                    "skip_or_shorten": ["장황한 설명", "중복 검토"],
                    "urgent_instructions": [
                        "필수 판단만 남기고 즉시 구조화 결과를 제출하세요.",
                        "안전 규칙과 출력 스키마는 생략하지 마세요.",
                    ],
                }
                self._broadcast(
                    "notice",
                    "ProductionManager",
                    manager_instruction,
                )
            try:
                with heartbeat(
                    self.live,
                    f"{role} 긴급 재배정",
                    self.heartbeat_seconds,
                    writer=lambda message: print(message, flush=True),
                ):
                    result = asyncio.run(
                        self._run_with_timeout(
                            role,
                            output_type,
                            payload,
                            expedited=True,
                            timeout_seconds=self.expedite_timeout_seconds,
                            manager_instruction=manager_instruction,
                        )
                    )
            except TimeoutError as exc:
                raise RuntimeError(
                    f"{role}가 일반 제한 {self.agent_timeout_seconds:.0f}초와 "
                    f"긴급 재배정 제한 {self.expedite_timeout_seconds:.0f}초를 모두 넘겼습니다. "
                    "잠시 후 다시 실행하세요."
                ) from exc
        output = result.final_output
        if not isinstance(output, output_type):
            output = output_type.model_validate(output)
        self._broadcast("output", role, output.model_dump(mode="json"))
        character_comment = getattr(output, "character_comment", "").strip()
        if character_comment:
            self._broadcast(
                "comment",
                role,
                character_comment,
            )
        if self.live:
            print(
                "@@AGENT_STATE@@"
                + json.dumps(
                    {"role": role, "state": "idle"},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        self.logger.info("Finished %s", role)
        return output

    def _save(self, filename: str, data: BaseModel | dict[str, Any] | list[Any]) -> Path:
        path = self.run_dir / filename
        if isinstance(data, BaseModel):
            payload = data.model_dump(mode="json")
        else:
            payload = data
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _load_checkpoint(self, filename: str, output_type: type[T]) -> T | None:
        path = self.run_dir / filename
        if not path.exists():
            return None
        output = output_type.model_validate_json(path.read_text(encoding="utf-8"))
        self._broadcast(
            "notice",
            "CheckpointManager",
            {"reused": filename, "message": "완료된 작업을 재사용합니다."},
        )
        return output

    def load_ideas(self) -> list[EpisodeIdea]:
        raw = json.loads(self.paths.ideas.read_text(encoding="utf-8"))
        return [EpisodeIdea.model_validate(item) for item in raw]

    def mark_idea_used(self, selected_idea_id: str) -> None:
        ideas = self.load_ideas()
        changed = False
        for idea in ideas:
            if idea.id == selected_idea_id:
                idea.used = True
                changed = True
        if changed:
            self.paths.ideas.write_text(
                json.dumps(
                    [idea.model_dump(mode="json") for idea in ideas],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def dry_run(self, topic: str | None) -> Path:
        roles = [
            "ProgrammingDirector",
            "StoryWriter",
            "ComedyWriter",
            "CharacterDirector",
            "ShortsDirector",
            "YouTubeProducer",
            "ComplianceReviewer",
            "ProductionManager",
        ]
        manifest = {
            "status": "dry_run_ok",
            "run_id": self.run_id,
            "topic": topic,
            "model": self.model,
            "max_revision_loops": self.max_revisions,
            "idea_count": len(self.load_ideas()),
            "prompt_files": {role: str(self.paths.agents / f"{role}.md") for role in roles},
            "api_key_present": bool(os.getenv("OPENAI_API_KEY")),
            "note": "API 호출 없이 설정·폴더·프롬프트를 검증했습니다.",
        }
        return self._save("dry_run_manifest.json", manifest)

    def produce(self, topic: str | None = None) -> Path:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY가 없습니다. 프로젝트 루트의 .env 또는 .env.local에 안전하게 설정하세요."
            )

        existing_final = self.paths.final / self.run_id / "final_episode.json"
        if existing_final.exists():
            self._broadcast(
                "notice",
                "CheckpointManager",
                {"message": "이미 완성된 final_episode.json을 재사용합니다."},
            )
            return existing_final

        ideas = self.load_ideas()
        self._broadcast(
            "notice",
            "BroadcastRoom",
            {
                "run_id": self.run_id,
                "topic": topic or "편성국장 자율 선정",
                "message": "표시되는 내용은 실제 전달 입력과 구조화 결과이며, 숨겨진 내부 추론은 포함하지 않습니다.",
            },
        )
        with trace(workflow_name="AI Travel Webtoon Broadcast Room", group_id=self.run_id):
            direction = self._load_checkpoint(
                "01_programming_direction.json", ProgrammingDirection
            )
            if direction is None:
                direction = self._run_agent(
                    "ProgrammingDirector",
                    ProgrammingDirection,
                    {
                        "requested_topic": topic,
                        "candidate_ideas": [idea.model_dump() for idea in ideas],
                        "instruction": "사용자 주제가 있으면 우선하되 후보와 중복 위험을 검토하세요.",
                    },
                )
                self._save("01_programming_direction.json", direction)

            story = self._load_checkpoint("02_story_draft_r0.json", StoryDraft)
            if story is None:
                story = self._run_agent(
                    "StoryWriter",
                    StoryDraft,
                    {
                        "production_direction": direction.model_dump(),
                        "revision_request": [],
                    },
                )
                self._save("02_story_draft_r0.json", story)

            comedy = self._load_checkpoint(
                "03_comedy_revision_r0.json", ComedyRevision
            )
            if comedy is None:
                comedy = self._run_agent(
                    "ComedyWriter",
                    ComedyRevision,
                    {"story_draft": story.model_dump(), "revision_request": []},
                )
                self._save("03_comedy_revision_r0.json", comedy)
            story = comedy.revised_story

            revision_count = 0
            completion_status = "compliance_passed"
            unresolved_review_items: list[str] = []
            while True:
                character = self._load_checkpoint(
                    f"05_character_direction_r{revision_count}.json", CharacterPlan
                )
                if character is None:
                    character = self._run_agent(
                        "CharacterDirector",
                        CharacterPlan,
                        {"story": story.model_dump()},
                    )
                    self._save(
                        f"05_character_direction_r{revision_count}.json", character
                    )

                shorts = self._load_checkpoint(
                    f"06_shorts_plan_r{revision_count}.json", ShortsPlan
                )
                if shorts is None:
                    shorts = self._run_agent(
                        "ShortsDirector",
                        ShortsPlan,
                        {
                            "story": story.model_dump(),
                            "character_direction": character.model_dump(),
                            "duration_range_seconds": self.config["shorts"],
                        },
                    )
                    self._save(f"06_shorts_plan_r{revision_count}.json", shorts)

                youtube = self._load_checkpoint(
                    f"07_youtube_package_r{revision_count}.json", YouTubePackage
                )
                if youtube is None:
                    youtube = self._run_agent(
                        "YouTubeProducer",
                        YouTubePackage,
                        {
                            "story": story.model_dump(),
                            "shorts_plan": shorts.model_dump(),
                        },
                    )
                    self._save(f"07_youtube_package_r{revision_count}.json", youtube)

                compliance = self._load_checkpoint(
                    f"08_compliance_review_r{revision_count}.json",
                    ComplianceReview,
                )
                if compliance is None:
                    compliance = self._run_agent(
                        "ComplianceReviewer",
                        ComplianceReview,
                        {
                            "production_direction": direction.model_dump(),
                            "story": story.model_dump(),
                            "character_direction": character.model_dump(),
                            "shorts_plan": shorts.model_dump(),
                            "youtube_package": youtube.model_dump(),
                            "revision_number": revision_count,
                        },
                    )
                    self._save(
                        f"08_compliance_review_r{revision_count}.json", compliance
                    )

                if compliance.verdict == "pass":
                    break
                if compliance.verdict == "discard":
                    raise RuntimeError(
                        f"심의 결과 폐기 판정입니다: {compliance.summary}. 초안은 {self.run_dir}에 보존됩니다."
                    )
                if revision_count >= self.max_revisions:
                    completion_status = "conditional_after_revision_limit"
                    unresolved_review_items = [
                        risk.required_fix for risk in compliance.risks
                    ] + compliance.human_review_checklist
                    self._broadcast(
                        "notice",
                        "ProductionManager",
                        {
                            "action": "조건부 완성본 생성",
                            "reason": (
                                f"최대 수정 횟수 {self.max_revisions}회에 도달했지만 "
                                "결과물 생성을 계속합니다."
                            ),
                            "compliance_verdict": compliance.verdict,
                            "mandatory_human_review": True,
                            "unresolved_items": unresolved_review_items,
                        },
                    )
                    break

                revision_count += 1
                self._broadcast(
                    "revision",
                    "ComplianceReviewer → StoryWriter / ComedyWriter",
                    {
                        "revision_number": revision_count,
                        "story_writer": compliance.revision_request_for_story_writer,
                        "comedy_writer": compliance.revision_request_for_comedy_writer,
                    },
                )
                revised_story = self._load_checkpoint(
                    f"02_story_draft_r{revision_count}.json", StoryDraft
                )
                if revised_story is None:
                    revised_story = self._run_agent(
                        "StoryWriter",
                        StoryDraft,
                        {
                            "previous_story": story.model_dump(),
                            "compliance_revision_request": compliance.revision_request_for_story_writer,
                            "revision_number": revision_count,
                        },
                    )
                    self._save(
                        f"02_story_draft_r{revision_count}.json", revised_story
                    )
                comedy = self._load_checkpoint(
                    f"03_comedy_revision_r{revision_count}.json", ComedyRevision
                )
                if comedy is None:
                    comedy = self._run_agent(
                        "ComedyWriter",
                        ComedyRevision,
                        {
                            "story_draft": revised_story.model_dump(),
                            "compliance_revision_request": compliance.revision_request_for_comedy_writer,
                            "revision_number": revision_count,
                        },
                    )
                    self._save(
                        f"03_comedy_revision_r{revision_count}.json", comedy
                    )
                story = comedy.revised_story

        final = FinalEpisode(
            run_id=self.run_id,
            topic=direction.topic,
            production_direction=direction,
            story=story,
            travel_review=None,
            character_direction=character,
            shorts_editing_guide=shorts,
            youtube_package=youtube,
            compliance_review=compliance,
            revision_count=revision_count,
            completion_status=completion_status,
            mandatory_human_review=True,
            unresolved_review_items=unresolved_review_items,
            human_approval=HumanApproval(),
            upload_ready=False,
        )
        final_dir = self.paths.final / self.run_id
        final_dir.mkdir(parents=True, exist_ok=True)
        final_path = final_dir / "final_episode.json"
        final_path.write_text(
            json.dumps(final.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.mark_idea_used(direction.selected_idea_id)
        self.logger.info("Final episode saved pending human approval: %s", final_path)
        return final_path


def approve_episode(root: Path, run_id: str, approver: str) -> Path:
    final_path = root / "outputs" / "final" / run_id / "final_episode.json"
    if not final_path.exists():
        raise FileNotFoundError(f"최종본을 찾을 수 없습니다: {final_path}")
    episode = FinalEpisode.model_validate_json(final_path.read_text(encoding="utf-8"))
    allowed_conditional = (
        episode.completion_status == "conditional_after_revision_limit"
        and episode.mandatory_human_review
    )
    if episode.compliance_review.verdict != "pass" and not allowed_conditional:
        raise RuntimeError("심의를 통과하거나 조건부 완성된 에피소드만 승인할 수 있습니다.")
    final_video = final_path.parent / "final_short.mp4"
    if not final_video.exists() or episode.video_assets.status != "rendered":
        raise RuntimeError("실제 final_short.mp4를 만든 뒤 영상을 확인하고 승인하세요.")
    episode.human_approval = HumanApproval.approved(approver)
    episode.upload_ready = True
    final_path.write_text(
        json.dumps(episode.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    approval_path = final_path.parent / "HUMAN_APPROVED.json"
    approval_path.write_text(
        json.dumps(
            episode.human_approval.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return final_path
