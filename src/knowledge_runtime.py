from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import yaml
from agents import Agent, ModelBehaviorError, ModelSettings, Runner, WebSearchTool
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from src.models import ManagementIntervention


class KnowledgeRuntime:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        load_dotenv(self.root / ".env")
        load_dotenv(self.root / ".env.local", override=True)
        self.config = yaml.safe_load(
            (self.root / "config.yaml").read_text(encoding="utf-8")
        )
        self.model = str(self.config.get("model", "gpt-5-mini"))
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
        self.expedite_max_tokens = int(
            self.config.get("expedite_max_tokens", 2500)
        )

    def _load_benchmark_scripts(self) -> list[dict[str, str]]:
        scripts = []
        # 1. 기본 벤치마크 대본
        bench_path = self.root / "bench" / "benchtext.txt"
        if bench_path.exists():
            try:
                text = bench_path.read_text(encoding="utf-8")
                import re
                blocks = re.split(r"<\d+번 참고 대본[^>]*>", text)
                for block in blocks:
                    block = block.strip().strip('"').strip()
                    if len(block) > 20:
                        scripts.append({
                            "script": block,
                            "length": len(block),
                            "source": "benchmark",
                        })
            except OSError:
                pass
        # 2. 사용자 업로드 대본 (최근 20개)
        user_dir = self.root / "bench" / "user_scripts"
        if user_dir.exists():
            user_files = sorted(user_dir.glob("*.txt"), reverse=True)[:20]
            for f in user_files:
                try:
                    text = f.read_text(encoding="utf-8")
                    # "제목: ..." 줄 제거하고 본문만
                    lines = text.strip().split("\n")
                    body = "\n".join(l for l in lines if not l.startswith("제목:")).strip()
                    if len(body) > 20:
                        scripts.append({
                            "script": body,
                            "length": len(body),
                            "source": "user_upload",
                        })
                except OSError:
                    pass
        return scripts[:30]

    def reference_context(self) -> dict[str, Any]:
        references_path = self.root / "ideas" / "video_references.json"
        style_path = self.root / "ideas" / "reference_style_profile.json"
        concept_path = self.root / "ideas" / "concept_reference_library.json"
        master_reference_path = self.root / "REFERENCE_STYLE.md"
        try:
            references = json.loads(references_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            references = []
        try:
            style_profile = json.loads(style_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            style_profile = {}
        try:
            concept_library = json.loads(concept_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            concept_library = {}
        concept_references = [
            reference
            for category in concept_library.get("categories", [])
            for reference in category.get("references", [])
        ]
        master_reference_available = master_reference_path.exists()
        return {
            "name": style_profile.get(
                "name",
                "사용자 제공 미스터리 쇼츠 레퍼런스",
            ),
            "reference_video_count": len(references),
            "reference_videos": references,
            "style_profile": style_profile,
            "concept_library_name": concept_library.get(
                "name",
                "REFERENCE LIBRARY",
            ),
            "concept_reference_count": len(concept_references),
            "concept_references": concept_references,
            "concept_usage_rule": concept_library.get(
                "usage_rule",
                "가장 가까운 사고 패턴을 골라 설계에 적용한다.",
            ),
            "concept_reference_mandatory": bool(
                concept_library.get("mandatory_use", True)
            ),
            "master_reference": {
                "name": "REFERENCE_STYLE.md",
                "path": str(master_reference_path.relative_to(self.root)),
                "available": master_reference_available,
                "mandatory": True,
                "channel_definition": (
                    "실제로 존재하는 사실을 이용해 시청자의 상상력을 폭발시키는 채널"
                ),
                "expansion_order": [
                    "실제 사실",
                    "상상 가능한 미래",
                    "인간에게 미치는 영향",
                    "문명에 미치는 영향",
                ],
                "topic_rule": (
                    "백과사전식 개념 설명을 금지하고, 쉬운 충격 질문으로 시작해 "
                    "실제 근거·이상한 증거·가설·최근 연구·미해결 질문으로 확장한다."
                ),
                "minimum_reference_criteria": 7,
                "priority_reference_criteria": 8,
                "script_phases": [
                    "0~3초 충격 질문",
                    "3~15초 실제 사실",
                    "15~35초 이상한 증거와 핵심 근거",
                    "35~50초 가설과 인간·문명 영향",
                    "50~55초 가설의 문제점 또는 더 불편한 가능성",
                    "55~60초 최근 연구와 현재 상황",
                    "마지막 미해결 질문",
                ],
                "speech_rule": (
                    "짧게 쓰고 설명보다 장면을 보여준다. 한 문장에는 한 정보만 넣는다."
                ),
                "quality_gate": (
                    "그래서?가 나오면 폐기하고, 잠깐 뭐라고?가 나오면 채택한다."
                ),
            },
            "usage_rule": (
                "후킹 강도, 정보 공개 순서, 내레이션 호흡, 자막 밀도, "
                "실제 자료와 재구성 화면의 배치 원리를 적극 참고한다. "
                "특정 영상의 문장이나 고유 장면 배열을 그대로 복사하지 않는다."
            ),
            "benchmark_scripts": self._load_benchmark_scripts(),
            "benchmark_usage_rule": (
                "benchmark_scripts는 실제 인기 유튜브 쇼츠 대본 10개다. "
                "이 대본들의 공통 패턴(문장 길이, 정보 공개 속도, 후킹 방식, "
                "질문과 답의 리듬, 마무리 방식)을 반드시 참고하되 "
                "문장을 그대로 복사하지 않는다."
            ),
        }

    def agent(
        self,
        role: str,
        output_type: type[Any],
        *,
        web: bool,
        max_tokens: int = 5000,
        expedited: bool = False,
    ) -> Agent[Any]:
        token_limit = min(max_tokens, self.expedite_max_tokens) if expedited else max_tokens
        instructions = (self.root / "agents" / f"{role}.md").read_text(
            encoding="utf-8"
        )
        if expedited:
            instructions += (
                "\n\n# 관리자 긴급 재배정\n"
                "- manager_instruction을 최우선으로 따른다.\n"
                "- 장황한 설명과 중복 검토를 생략한다.\n"
                "- 필수 근거, 안전 규칙, 출력 스키마는 유지한다.\n"
                "- 가능한 한 즉시 최종 구조화 결과를 제출한다.\n"
            )
        return Agent(
            name=role,
            instructions=instructions,
            model=self.model,
            model_settings=ModelSettings(
                reasoning={"effort": "low"}
                if self.model.startswith(("gpt-5", "o1", "o3", "o4"))
                else None,
                verbosity="low"
                if expedited and self.model.startswith("gpt-5")
                else None,
                max_tokens=token_limit,
            ),
            tools=(
                [WebSearchTool(search_context_size="medium", external_web_access=True)]
                if web
                else []
            ),
            output_type=output_type,
        )

    @staticmethod
    def _emit(marker: str, payload: dict[str, Any]) -> None:
        print(
            marker + json.dumps(payload, ensure_ascii=False),
            flush=True,
        )

    async def _run_once(
        self,
        role: str,
        output_type: type[BaseModel],
        payload: dict[str, Any],
        *,
        web: bool,
        max_tokens: int,
        max_turns: int,
        expedited: bool,
        timeout_seconds: float,
    ) -> Any:
        return await asyncio.wait_for(
            Runner.run(
                self.agent(
                    role,
                    output_type,
                    web=web,
                    max_tokens=max_tokens,
                    expedited=expedited,
                ),
                json.dumps(payload, ensure_ascii=False, indent=2),
                max_turns=2 if expedited else max_turns,
            ),
            timeout=timeout_seconds,
        )

    async def _manager_intervention(
        self,
        delayed_role: str,
        payload: dict[str, Any],
    ) -> ManagementIntervention:
        manager_payload = {
            "delayed_role": delayed_role,
            "elapsed_seconds": self.agent_timeout_seconds,
            "original_assignment": payload,
            "instruction": (
                "지연 원인을 짧게 판단하고 품질·안전·출력 스키마는 유지하면서 "
                "담당자가 45초 안에 끝낼 긴급 지시를 3개 이하로 작성하세요."
            ),
        }
        result = await self._run_once(
            "ProductionManager",
            ManagementIntervention,
            manager_payload,
            web=False,
            max_tokens=self.expedite_max_tokens,
            max_turns=1,
            expedited=True,
            timeout_seconds=self.manager_intervention_timeout_seconds,
        )
        output = result.final_output
        if not isinstance(output, ManagementIntervention):
            output = ManagementIntervention.model_validate(output)
        return output

    def run_structured(
        self,
        role: str,
        output_type: type[BaseModel],
        payload: dict[str, Any],
        *,
        web: bool,
        max_tokens: int = 5000,
        max_turns: int = 5,
    ) -> BaseModel:
        stop_heartbeat = threading.Event()
        started = time.monotonic()
        heartbeat_state = {
            "percent": 15,
            "mode": "normal",
            "retry_started": started,
        }

        def heartbeat() -> None:
            while not stop_heartbeat.wait(self.heartbeat_seconds):
                if heartbeat_state["mode"] == "urgent":
                    elapsed = round(
                        time.monotonic() - float(heartbeat_state["retry_started"])
                    )
                    message = (
                        f"한실장 긴급 재처리 진행 중 · {elapsed}초 경과 · "
                        "핵심 결과를 기다리고 있습니다."
                    )
                else:
                    elapsed = round(time.monotonic() - started)
                    message = (
                        f"작업 진행 중 · {elapsed}초 경과 · 응답을 기다리고 있습니다."
                    )
                self._emit(
                    "@@AGENT_PROGRESS@@",
                    {
                        "role": role,
                        "percent": int(heartbeat_state["percent"]),
                        "message": message,
                    },
                )

        worker = threading.Thread(target=heartbeat, daemon=True)
        worker.start()
        try:
            try:
                try:
                    result = asyncio.run(
                        self._run_once(
                            role,
                            output_type,
                            payload,
                            web=web,
                            max_tokens=max_tokens,
                            max_turns=max_turns,
                            expedited=False,
                            timeout_seconds=self.agent_timeout_seconds,
                        )
                    )
                except TimeoutError:
                    heartbeat_state.update(
                        {
                            "percent": 60,
                            "mode": "urgent",
                            "retry_started": time.monotonic(),
                        }
                    )
                    self._emit(
                        "@@AGENT_STATE@@",
                        {"role": "ProductionManager", "state": "working"},
                    )
                    self._emit(
                        "@@AGENT_COMMENT@@",
                        {
                            "role": "ProductionManager",
                            "comment": (
                                f"{role}가 {self.agent_timeout_seconds:.0f}초를 넘겼습니다. "
                                "제가 중간 개입해 필수 판단만 남기고 빠른 재처리를 지시하겠습니다."
                            ),
                        },
                    )
                    try:
                        intervention = asyncio.run(
                            self._manager_intervention(role, payload)
                        )
                        manager_instruction = intervention.model_dump(mode="json")
                        self._emit(
                            "@@AGENT_COMMENT@@",
                            {
                                "role": "ProductionManager",
                                "comment": intervention.character_comment
                                or intervention.reason,
                            },
                        )
                    except Exception:
                        manager_instruction = {
                            "delayed_role": role,
                            "bottleneck_assessment": "응답 지연으로 기본 긴급 지시 적용",
                            "keep_required": [
                                "출력 스키마",
                                "핵심 근거",
                                "안전 및 사람 승인 규칙",
                            ],
                            "skip_or_shorten": ["장황한 설명", "중복 검토", "선택적 부가 항목"],
                            "urgent_instructions": [
                                "핵심 판단만 남기고 즉시 구조화 결과를 제출하세요.",
                                "출력 스키마와 필수 안전 항목은 생략하지 마세요.",
                            ],
                            "reason": "관리자 기본 긴급 재배정",
                        }
                        self._emit(
                            "@@AGENT_COMMENT@@",
                            {
                                "role": "ProductionManager",
                                "comment": "관리자 판단도 지연되어 기본 긴급 지시로 바로 재배정합니다.",
                            },
                        )
                    self._emit(
                        "@@AGENT_PROGRESS@@",
                        {
                            "role": role,
                            "percent": 60,
                            "message": (
                                "한실장 긴급 지시를 받아 설명을 줄이고 핵심 결과를 "
                                f"{self.expedite_timeout_seconds:.0f}초 안에 다시 작성합니다."
                            ),
                        },
                    )
                    retry_payload = {
                        **payload,
                        "manager_instruction": manager_instruction,
                        "expedited_retry": True,
                    }
                    try:
                        result = asyncio.run(
                            self._run_once(
                                role,
                                output_type,
                                retry_payload,
                                web=web,
                                max_tokens=max_tokens,
                                max_turns=max_turns,
                                expedited=True,
                                timeout_seconds=self.expedite_timeout_seconds,
                            )
                        )
                    except TimeoutError as exc:
                        raise RuntimeError(
                            f"{role}가 일반 제한 {self.agent_timeout_seconds:.0f}초와 "
                            f"관리자 긴급 재시도 {self.expedite_timeout_seconds:.0f}초를 모두 넘겼습니다. "
                            "완료된 체크포인트는 보존되며 같은 에피소드를 다시 실행하면 이어서 시작합니다."
                        ) from exc
                output = result.final_output
                if not isinstance(output, output_type):
                    output = output_type.model_validate(output)
            except (ModelBehaviorError, ValidationError) as exc:
                heartbeat_state.update(
                    {
                        "percent": 70,
                        "mode": "urgent",
                        "retry_started": time.monotonic(),
                    }
                )
                self._emit(
                    "@@AGENT_COMMENT@@",
                    {
                        "role": "ProductionManager",
                        "comment": (
                            f"{role}의 판단 내용은 도착했지만 저장 형식이 깨졌습니다. "
                            "앞 단계는 유지하고 같은 담당자에게 짧은 JSON으로 한 번 다시 제출시킵니다."
                        ),
                    },
                )
                self._emit(
                    "@@AGENT_PROGRESS@@",
                    {
                        "role": role,
                        "percent": 70,
                        "message": "저장 형식 오류를 복구하며 핵심 결과만 다시 작성합니다.",
                    },
                )
                repair_payload = {
                    **payload,
                    "structured_output_repair": True,
                    "manager_instruction": {
                        "urgent_instructions": [
                            "직전 응답은 JSON 형식이 깨져 저장되지 않았습니다.",
                            "출력 스키마의 필수 필드를 모두 채우고 JSON 이외의 문장을 출력하지 마세요.",
                            "각 목록은 핵심 항목만 남겨 짧게 작성하고 반드시 완전한 JSON으로 끝내세요.",
                        ]
                    },
                }
                try:
                    repaired = asyncio.run(
                        self._run_once(
                            role,
                            output_type,
                            repair_payload,
                            web=web,
                            max_tokens=max_tokens,
                            max_turns=min(max_turns, 4),
                            expedited=False,
                            timeout_seconds=self.agent_timeout_seconds,
                        )
                    )
                    output = repaired.final_output
                    if not isinstance(output, output_type):
                        output = output_type.model_validate(output)
                except (ModelBehaviorError, ValidationError) as retry_exc:
                    raise RuntimeError(
                        f"{role}의 구조화 저장 형식이 두 번 연속 깨졌습니다. "
                        "완료된 체크포인트는 보존되며 같은 에피소드를 다시 실행하면 이 단계부터 재시도합니다."
                    ) from retry_exc
            return output
        finally:
            stop_heartbeat.set()
            worker.join(timeout=1)
            self._emit(
                "@@AGENT_STATE@@",
                {"role": "ProductionManager", "state": "idle"},
            )

    def run_isolated_structured(
        self,
        role: str,
        output_type: type[BaseModel],
        payload: dict[str, Any],
        *,
        max_tokens: int = 5000,
        max_turns: int = 4,
        timeout_seconds: float = 90,
    ) -> BaseModel:
        stop_heartbeat = threading.Event()
        started = time.monotonic()

        def heartbeat() -> None:
            while not stop_heartbeat.wait(self.heartbeat_seconds):
                elapsed = round(time.monotonic() - started)
                self._emit(
                    "@@AGENT_PROGRESS@@",
                    {
                        "role": role,
                        "percent": 45,
                        "message": (
                            f"다른 AI와 상의하지 않고 기존 대본만 각색하고 있습니다. "
                            f"{elapsed}초 경과"
                        ),
                    },
                )

        worker = threading.Thread(target=heartbeat, daemon=True)
        worker.start()
        try:
            last_error: Exception | None = None
            for attempt in range(2):
                current_payload = dict(payload)
                if attempt:
                    current_payload["same_editor_retry"] = {
                        "reason": "이전 출력의 형식 또는 자체 점검이 통과하지 못함",
                        "instruction": (
                            "다른 자료나 의견을 찾지 말고 같은 원본 대본만 다시 각색한다. "
                            "모든 필수 JSON 필드와 자체 점검을 완성한다."
                        ),
                    }
                try:
                    result = asyncio.run(
                        self._run_once(
                            role,
                            output_type,
                            current_payload,
                            web=False,
                            max_tokens=max_tokens,
                            max_turns=max_turns,
                            expedited=False,
                            timeout_seconds=timeout_seconds,
                        )
                    )
                    output = result.final_output
                    if not isinstance(output, output_type):
                        output = output_type.model_validate(output)
                    return output
                except (
                    TimeoutError,
                    ModelBehaviorError,
                    ValidationError,
                ) as exc:
                    last_error = exc
                    if attempt == 0:
                        self._emit(
                            "@@AGENT_COMMENT@@",
                            {
                                "role": role,
                                "comment": (
                                    "형식이나 자체 점검이 맞지 않아 제가 혼자 원본 대본을 "
                                    "다시 다듬겠습니다. 다른 담당자에게 넘기지 않습니다."
                                ),
                            },
                        )
            raise RuntimeError(
                f"{role}가 독립 각색을 두 번 시도했지만 완료하지 못했습니다."
            ) from last_error
        finally:
            stop_heartbeat.set()
            worker.join(timeout=1)
