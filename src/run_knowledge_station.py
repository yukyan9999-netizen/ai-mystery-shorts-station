from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fact_checker import FactChecker
from src.knowledge_models import (
    DailyTopicBatch,
    FactCheckReport,
    KnowledgeProductionPackage,
    KnowledgeScript,
    MixedMediaPlan,
    ResearchDossier,
    ShortsAdaptationResult,
    SourceResearchReport,
    TrendReport,
    VisualPackage,
)
from src.master_agents import (
    HistoricalResearcher,
    ScientificResearcher,
    TopicHunter,
    TrendAnalyst,
)
from src.mixed_media_planner import MixedMediaPlanner
from src.schedule_manager import ScheduleManager
from src.script_writer import ScriptWriter
from src.shorts_adaptation_editor import ShortsAdaptationEditor
from src.source_researcher import SourceResearcher
from src.topic_library import TopicLibrary
from src.visual_prompt_generator import VisualPromptGenerator
from src.knowledge_runtime import KnowledgeRuntime

ITEMS_PATH = PROJECT_ROOT / "ideas" / "knowledge_items.json"
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "knowledge"


def emit_state(role: str, state: str) -> None:
    print(
        "@@AGENT_STATE@@"
        + json.dumps({"role": role, "state": state}, ensure_ascii=False),
        flush=True,
    )


def emit_progress(role: str, percent: int, message: str) -> None:
    print(
        "@@AGENT_PROGRESS@@"
        + json.dumps(
            {"role": role, "percent": percent, "message": message},
            ensure_ascii=False,
        ),
        flush=True,
    )


def emit_comment(role: str, comment: str) -> None:
    print(
        "@@AGENT_COMMENT@@"
        + json.dumps({"role": role, "comment": comment}, ensure_ascii=False),
        flush=True,
    )


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_history() -> list[dict[str, Any]]:
    if not ITEMS_PATH.exists():
        return []
    try:
        value = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def append_history(entry: dict[str, Any]) -> None:
    history = load_history()
    history.append(entry)
    save_json(ITEMS_PATH, history)


def update_history(run_id: str, **changes: Any) -> None:
    history = load_history()
    for entry in reversed(history):
        if entry.get("run_id") == run_id:
            entry.update(changes)
            break
    else:
        raise FileNotFoundError(f"실행 기록을 찾을 수 없습니다: {run_id}")
    save_json(ITEMS_PATH, history)


def generate_candidates(target: date, requested_direction: str = "") -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = OUTPUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    emit_state("ScheduleManager", "working")
    schedule = ScheduleManager(PROJECT_ROOT).instruction_for(target)
    schedule["requested_direction"] = requested_direction
    schedule["discovery_mode"] = (
        "user_direction" if requested_direction else "automatic_schedule"
    )
    save_json(run_dir / "00_schedule.json", schedule)
    emit_progress(
        "ScheduleManager",
        100,
        (
            f"사용자 방향 ‘{requested_direction}’을 우선해 탐색합니다."
            if requested_direction
            else f"{target.isoformat()} 자동 편성은 ‘{schedule['category']}’입니다."
        ),
    )
    emit_state("ScheduleManager", "idle")

    emit_state("TrendAnalyst", "working")
    emit_progress(
        "TrendAnalyst",
        10,
        "최근 과학 뉴스·역사 논쟁·쇼츠 반응에서 질문으로 확장될 신호를 찾고 있습니다.",
    )
    trend_report = TrendAnalyst(PROJECT_ROOT).analyze(
        target,
        schedule,
        requested_direction,
    )
    save_json(run_dir / "01_trend_report.json", trend_report)
    emit_comment("TrendAnalyst", trend_report.character_comment)
    emit_progress(
        "TrendAnalyst",
        100,
        f"트렌드 신호 {len(trend_report.trending_topics)}개를 정리했습니다.",
    )
    emit_state("TrendAnalyst", "idle")

    emit_state("TopicHunter", "working")
    emit_progress(
        "TopicHunter",
        10,
        "현실에서 시작해 인간과 문명의 질문으로 커질 후보를 추적하고 있습니다.",
    )
    batch = TopicHunter(PROJECT_ROOT).hunt(
        target,
        schedule,
        trend_report,
        requested_direction,
    )
    save_json(run_dir / "01_topic_candidates.json", batch)
    library_result = TopicLibrary(PROJECT_ROOT).add_batch(
        batch,
        run_id,
        requested_direction,
    )
    emit_comment("TopicHunter", batch.character_comment)
    emit_progress(
        "TopicHunter",
        100,
        "후보 3개를 준비했습니다. 제작할 주제는 사람이 선택합니다.",
    )
    emit_state("TopicHunter", "idle")

    history_entry = batch.model_dump(mode="json")
    history_entry.update(
        {
            "run_id": run_id,
            "selected_title": None,
            "selected_candidate_index": None,
            "production_status": "awaiting_topic_selection",
            "human_approved": False,
            "requested_direction": requested_direction,
            "discovery_mode": (
                "user_direction" if requested_direction else "automatic_schedule"
            ),
            "topic_library_result": library_result,
            "trend_report": str(
                (run_dir / "01_trend_report.json").relative_to(PROJECT_ROOT)
            ),
        }
    )
    append_history(history_entry)
    save_json(
        run_dir / "RESULT.json",
        {
            "status": "awaiting_topic_selection",
            "message": "AI 후보 3개 생성 완료. 사람이 제작 주제를 선택해야 합니다.",
            "candidate_count": 3,
            "topic_library_result": library_result,
        },
    )
    print(
        f"후보 3개 생성 완료 · 사람 채택 대기: {run_dir / '01_topic_candidates.json'}",
        flush=True,
    )
    return run_dir / "01_topic_candidates.json"


def produce_direct_topic(target: date, user_topic: str) -> Path:
    user_topic = user_topic.strip()
    if not user_topic:
        raise ValueError("토픽헌터에게 전달할 주제를 입력해주세요.")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = OUTPUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    emit_state("ScheduleManager", "working")
    schedule = ScheduleManager(PROJECT_ROOT).instruction_for(target)
    schedule["requested_direction"] = user_topic
    schedule["discovery_mode"] = "direct_topic"
    save_json(run_dir / "00_schedule.json", schedule)
    emit_progress(
        "ScheduleManager",
        100,
        "자동 편성 대신 사용자가 직접 준 주제를 최우선으로 배정했습니다.",
    )
    emit_state("ScheduleManager", "idle")

    emit_state("TopicHunter", "working")
    emit_progress(
        "TopicHunter",
        10,
        "주제의 핵심은 유지하고 바로 대본으로 넘길 수 있는 질문으로 다듬고 있습니다.",
    )
    plan = TopicHunter(PROJECT_ROOT).refine_direct(target, schedule, user_topic)
    save_json(run_dir / "01_direct_topic_plan.json", plan)
    batch = DailyTopicBatch(
        production_date=target,
        schedule_reason="사용자가 토픽헌터에게 직접 지정한 주제",
        category=plan.candidate.category,
        character_comment=plan.topic_hunter_reply,
        candidates=[plan.candidate],
    )
    save_json(run_dir / "01_topic_candidates.json", batch)
    library_result = TopicLibrary(PROJECT_ROOT).add_batch(
        batch,
        run_id,
        user_topic,
    )
    emit_comment("TopicHunter", plan.topic_hunter_reply)
    emit_progress(
        "TopicHunter",
        100,
        f"‘{plan.candidate.title}’로 정리했습니다. 지금 조사와 대본 제작으로 넘깁니다.",
    )
    emit_state("TopicHunter", "idle")

    history_entry = batch.model_dump(mode="json")
    history_entry.update(
        {
            "run_id": run_id,
            "selected_title": plan.candidate.title,
            "selected_candidate_index": 0,
            "production_status": "production_running",
            "human_approved": False,
            "requested_direction": user_topic,
            "direct_topic_request": user_topic,
            "topic_hunter_reply": plan.topic_hunter_reply,
            "discovery_mode": "direct_topic",
            "topic_library_result": library_result,
            "selected_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    append_history(history_entry)
    save_json(
        run_dir / "RESULT.json",
        {
            "status": "production_running",
            "message": "토픽헌터 직접 지정 주제로 대본 제작을 시작합니다.",
            "selected_title": plan.candidate.title,
        },
    )
    emit_comment(
        "ProductionManager",
        "사용자가 직접 지정한 주제입니다. 후보 선택을 생략하고 최종 대본 승인 단계까지 제작합니다.",
    )
    return continue_selected(run_id, 0)


def _simple_script_checks(script: KnowledgeScript) -> list[str]:
    """Replace AudienceSimulator with deterministic quality checks."""
    warnings: list[str] = []
    narration = script.full_narration if hasattr(script, "full_narration") else ""
    if not narration and hasattr(script, "timed_script"):
        parts = []
        ts = script.timed_script
        for field in ("hook_0_3", "context_3_10", "deep_dive_10_40", "climax_40_50", "closing_50_60"):
            val = getattr(ts, field, None)
            if val:
                parts.append(val)
        narration = " ".join(parts)

    # Check 1: engagement (at least 3 question marks)
    question_count = narration.count("?")
    if question_count < 3:
        warnings.append(f"질문이 {question_count}개뿐입니다 (최소 3개 권장).")

    # Check 2: no repeated sentences
    sentences = [s.strip() for s in narration.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    seen: set[str] = set()
    for s in sentences:
        if s in seen:
            warnings.append(f"중복 문장 발견: '{s[:30]}...'")
            break
        seen.add(s)

    # Check 3: reasonable length (200-800 chars)
    length = len(narration)
    if length < 200:
        warnings.append(f"내레이션이 너무 짧습니다 ({length}자, 최소 200자 권장).")
    elif length > 800:
        warnings.append(f"내레이션이 너무 깁니다 ({length}자, 최대 800자 권장).")

    return warnings


def _load_or_research(
    run_dir: Path,
    selected: Any,
) -> tuple[ResearchDossier, ResearchDossier]:
    scientific_path = run_dir / "02_scientific_research.json"
    historical_path = run_dir / "03_historical_research.json"
    results: dict[str, ResearchDossier] = {}
    tasks: dict[Any, tuple[str, Path]] = {}

    emit_state("Researcher", "working")

    if scientific_path.exists():
        results["scientific"] = ResearchDossier.model_validate_json(
            scientific_path.read_text(encoding="utf-8")
        )
    if historical_path.exists():
        results["historical"] = ResearchDossier.model_validate_json(
            historical_path.read_text(encoding="utf-8")
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        if "scientific" not in results:
            emit_progress(
                "Researcher",
                10,
                "논문·실험·공식 과학 자료에서 검증된 출발점을 찾고 있습니다.",
            )
            tasks[
                pool.submit(ScientificResearcher(PROJECT_ROOT).research, selected)
            ] = ("scientific", scientific_path)
        if "historical" not in results:
            emit_progress(
                "Researcher",
                50,
                "기록·유물·박물관 자료에서 잊힌 세부를 찾고 있습니다.",
            )
            tasks[
                pool.submit(HistoricalResearcher(PROJECT_ROOT).research, selected)
            ] = ("historical", historical_path)
        for future in as_completed(tasks):
            key, path = tasks[future]
            dossier = future.result()
            results[key] = dossier
            save_json(path, dossier)

    for key in ("scientific", "historical"):
        dossier = results[key]
        emit_comment("Researcher", dossier.character_comment)

    total_evidence = len(results["scientific"].evidence) + len(results["historical"].evidence)
    emit_progress(
        "Researcher",
        100,
        f"과학·역사 근거 {total_evidence}개와 미해결 질문을 정리했습니다.",
    )
    emit_state("Researcher", "idle")

    return results["scientific"], results["historical"]


def continue_selected(run_id: str, candidate_index: int) -> Path:
    if candidate_index not in {0, 1, 2}:
        raise ValueError("후보 번호는 0, 1, 2 중 하나여야 합니다.")
    run_dir = OUTPUT_ROOT / run_id
    batch_path = run_dir / "01_topic_candidates.json"
    if not batch_path.exists():
        raise FileNotFoundError(f"후보 파일을 찾을 수 없습니다: {batch_path}")
    final_path = run_dir / "final_knowledge_short.json"
    if final_path.exists():
        print(f"이미 완성된 제작 패키지를 재사용합니다: {final_path}", flush=True)
        return final_path

    batch = DailyTopicBatch.model_validate_json(batch_path.read_text(encoding="utf-8"))
    selected = batch.candidates[candidate_index]
    TopicLibrary(PROJECT_ROOT).mark_selected(selected.title, run_id)
    update_history(
        run_id,
        selected_title=selected.title,
        selected_candidate_index=candidate_index,
        production_status="production_running",
        selected_at=datetime.now().isoformat(timespec="seconds"),
    )
    emit_comment(
        "ProductionManager",
        f"사람이 ‘{selected.title}’을 채택했습니다. 저장된 단계는 재사용하며 제작을 이어갑니다.",
    )

    scientific, historical = _load_or_research(run_dir, selected)

    script_path = run_dir / "08_script.json"
    emit_state("KnowledgeScriptWriter", "working")
    if script_path.exists():
        script = KnowledgeScript.model_validate_json(
            script_path.read_text(encoding="utf-8")
        )
        emit_progress("KnowledgeScriptWriter", 100, "저장된 60초 대본을 재사용합니다.")
    else:
        emit_progress(
            "KnowledgeScriptWriter",
            15,
            "검증된 현실에서 시작해 존재론적 질문으로 끝나는 60초 대본을 쓰고 있습니다.",
        )
        script = ScriptWriter(PROJECT_ROOT).write(
            selected,
            scientific,
            historical,
        )
        save_json(script_path, script)
    emit_comment("KnowledgeScriptWriter", script.character_comment)
    emit_progress("KnowledgeScriptWriter", 100, "60초 대본을 완성했습니다.")
    emit_state("KnowledgeScriptWriter", "idle")

    adaptation_path = run_dir / "08_shorts_adaptation.json"
    adapted_script_path = run_dir / "08_shorts_adapted_script.json"
    emit_state("ShortsAdaptationEditor", "working")
    if adaptation_path.exists():
        adaptation = ShortsAdaptationResult.model_validate_json(
            adaptation_path.read_text(encoding="utf-8")
        )
        script = adaptation.adapted_script
        if not adapted_script_path.exists():
            save_json(adapted_script_path, script)
        emit_progress(
            "ShortsAdaptationEditor",
            100,
            "저장된 쇼츠 각색본을 재사용합니다.",
        )
    else:
        emit_progress(
            "ShortsAdaptationEditor",
            15,
            "다른 담당자와 상의하지 않고 기존 대본만 쉬운 쇼츠 말투로 바꾸고 있습니다.",
        )
        adaptation = ShortsAdaptationEditor(PROJECT_ROOT).adapt(script)
        script = adaptation.adapted_script
        save_json(adaptation_path, adaptation)
        save_json(adapted_script_path, script)
        for downstream_name in (
            "10_fact_check.json",
            "12_visual_package.json",
            "13_mixed_media_plan.json",
        ):
            downstream = run_dir / downstream_name
            if downstream.exists():
                downstream.unlink()
    emit_comment("ShortsAdaptationEditor", adaptation.character_comment)
    emit_progress(
        "ShortsAdaptationEditor",
        100,
        "사실은 유지하고 문장 길이·질문·반전 리듬만 각색했습니다.",
    )
    emit_state("ShortsAdaptationEditor", "idle")

    # Code-based quality checks (replaces AudienceSimulator)
    script_warnings = _simple_script_checks(script)
    if script_warnings:
        for warning in script_warnings:
            emit_comment("QualityCheck", warning)
        print(
            f"스크립트 품질 경고 {len(script_warnings)}건 (제작은 계속합니다).",
            flush=True,
        )

    fact_path = run_dir / "10_fact_check.json"
    emit_state("FactChecker", "working")
    if fact_path.exists():
        fact_check = FactCheckReport.model_validate_json(
            fact_path.read_text(encoding="utf-8")
        )
        emit_progress("FactChecker", 100, "저장된 최종 사실성 분류를 재사용합니다.")
    else:
        emit_progress(
            "FactChecker",
            10,
            "대본의 주요 문장을 사실·학설·추정·가상 시나리오로 분리하고 있습니다.",
        )
        fact_check = FactChecker(PROJECT_ROOT).check(
            selected,
            scientific,
            historical,
            script,
        )
        save_json(fact_path, fact_check)
    if fact_check.verdict == "reject" and not fact_check.blocking_safety_issue:
        fact_check = fact_check.model_copy(
            update={
                "verdict": "revise",
                "dramatization_allowed": True,
                "required_on_screen_labels": list(
                    dict.fromkeys(
                        [
                            *fact_check.required_on_screen_labels,
                            "진위 미확인",
                            "가상 시나리오",
                        ]
                    )
                ),
            }
        )
        save_json(fact_path, fact_check)
    emit_comment("FactChecker", fact_check.character_comment)
    emit_progress("FactChecker", 100, "최종 사실성 등급과 표시 문구를 확정했습니다.")
    emit_state("FactChecker", "idle")

    if fact_check.verdict == "reject" and fact_check.blocking_safety_issue:
        update_history(run_id, production_status="fact_check_rejected")
        save_json(
            run_dir / "RESULT.json",
            {
                "status": "fact_check_rejected",
                "message": "중대한 안전 문제로 사람 검토 전 제작을 보류했습니다.",
            },
        )
        raise RuntimeError("중대한 안전 문제로 제작이 보류되었습니다.")

    source_path = run_dir / "11_source_research.json"
    emit_state("SourceResearcher", "working")
    if source_path.exists():
        source_research = SourceResearchReport.model_validate_json(
            source_path.read_text(encoding="utf-8")
        )
        emit_progress("SourceResearcher", 100, "저장된 시각 자료 조사를 재사용합니다.")
    else:
        emit_progress(
            "SourceResearcher",
            10,
            "논문·기록·박물관·공개 아카이브에서 실제 화면 자료를 찾고 있습니다.",
        )
        source_research = SourceResearcher(PROJECT_ROOT).research(
            selected,
            fact_check,
        )
        save_json(source_path, source_research)
    emit_comment("SourceResearcher", source_research.character_comment)
    emit_progress(
        "SourceResearcher",
        100,
        f"사용 가능한 실제 시각 자료 {source_research.usable_visual_asset_count}개를 분류했습니다.",
    )
    emit_state("SourceResearcher", "idle")

    visual_path = run_dir / "12_visual_package.json"
    emit_state("VisualPromptGenerator", "working")
    if visual_path.exists():
        visuals = VisualPackage.model_validate_json(
            visual_path.read_text(encoding="utf-8")
        )
        emit_progress("VisualPromptGenerator", 100, "저장된 장면 설계를 재사용합니다.")
    else:
        emit_progress(
            "VisualPromptGenerator",
            15,
            "실제 증거 화면을 우선 배치하고 필요한 장면만 AI 재구성으로 설계합니다.",
        )
        visuals = VisualPromptGenerator(PROJECT_ROOT).generate(
            script,
            fact_check,
            None,
            source_research,
        )
        save_json(visual_path, visuals)
    emit_comment("VisualPromptGenerator", visuals.character_comment)
    emit_progress("VisualPromptGenerator", 100, "장면·자막·썸네일 설계를 완성했습니다.")
    emit_state("VisualPromptGenerator", "idle")

    media_plan_path = run_dir / "13_mixed_media_plan.json"
    emit_state("MixedMediaPlanner", "working")
    if media_plan_path.exists():
        media_plan = MixedMediaPlan.model_validate_json(
            media_plan_path.read_text(encoding="utf-8")
        )
        emit_progress("MixedMediaPlanner", 100, "저장된 자료 혼합 편집안을 재사용합니다.")
    else:
        emit_progress(
            "MixedMediaPlanner",
            15,
            "실제 증거 자료와 AI 재구성의 장면별 비율을 설계하고 있습니다.",
        )
        media_plan = MixedMediaPlanner(PROJECT_ROOT).plan(
            visuals,
            source_research,
        )
        save_json(media_plan_path, media_plan)
    emit_comment("MixedMediaPlanner", media_plan.character_comment)
    emit_progress(
        "MixedMediaPlanner",
        100,
        f"실제 자료 {media_plan.planned_real_media_percent}% 기준 편집안을 완성했습니다.",
    )
    emit_state("MixedMediaPlanner", "idle")

    trend_path = run_dir / "01_trend_report.json"
    trend_report = (
        TrendReport.model_validate_json(trend_path.read_text(encoding="utf-8"))
        if trend_path.exists()
        else None
    )
    package = KnowledgeProductionPackage(
        run_id=run_id,
        production_date=batch.production_date,
        category=batch.category,
        selected_candidate=selected,
        trend_report=trend_report,
        scientific_research=scientific,
        historical_research=historical,
        curiosity_report=None,
        consequence_report=None,
        gihwan_report=None,
        narrative_architecture=None,
        audience_simulation=None,
        reference_brief=KnowledgeRuntime(PROJECT_ROOT).reference_context(),
        fact_check=fact_check,
        source_research=source_research,
        script=script,
        shorts_adaptation=adaptation,
        visual_package=visuals,
        mixed_media_plan=media_plan,
    )
    save_json(final_path, package)
    update_history(
        run_id,
        production_status="package_ready",
        final_package=str(final_path.relative_to(PROJECT_ROOT)),
        human_approved=False,
    )
    save_json(
        run_dir / "RESULT.json",
        {
            "status": "package_ready",
            "message": "제작 패키지 완료. 사람 승인 후 MP4 제작을 시작합니다.",
            "fact_check_verdict": fact_check.verdict,
        },
    )
    print(f"제작 패키지 완료 · 사람 승인 대기: {final_path}", flush=True)
    return final_path


def revise_script(run_id: str, feedback_path: Path) -> Path:
    run_dir = OUTPUT_ROOT / run_id
    final_path = run_dir / "final_knowledge_short.json"
    if not final_path.exists():
        raise FileNotFoundError("수정할 최종 제작 패키지가 없습니다.")
    feedback_payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    user_feedback = str(feedback_payload.get("feedback", "")).strip()
    if not user_feedback:
        raise ValueError("대본 수정 피드백이 비어 있습니다.")

    raw_pkg = json.loads(final_path.read_text(encoding="utf-8"))
    if "visual_package" in raw_pkg and len(raw_pkg["visual_package"].get("scenes", [])) > 20:
        raw_pkg["visual_package"]["scenes"] = raw_pkg["visual_package"]["scenes"][:20]
    if "mixed_media_plan" in raw_pkg and len(raw_pkg["mixed_media_plan"].get("scene_assets", [])) > 20:
        raw_pkg["mixed_media_plan"]["scene_assets"] = raw_pkg["mixed_media_plan"]["scene_assets"][:20]
    package = KnowledgeProductionPackage.model_validate(raw_pkg)
    required = {
        "scientific_research": package.scientific_research,
        "historical_research": package.historical_research,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise RuntimeError(
            "이전 방식으로 만든 패키지는 새 대본 피드백 기능을 사용할 수 없습니다: "
            + ", ".join(missing)
        )

    update_history(
        run_id,
        production_status="script_revision_running",
        human_approved=False,
        latest_script_feedback=user_feedback,
    )
    emit_comment(
        "ProductionManager",
        f"사람 피드백을 작가에게 전달했습니다: {user_feedback}",
    )

    existing = sorted(run_dir.glob("08_script_revision_[0-9][0-9].json"))
    revision_number = len(existing) + 1
    revision_path = run_dir / f"08_script_revision_{revision_number:02d}.json"
    current_script = package.script
    feedback_history: list[str] = []
    for previous_path in sorted(run_dir.glob("script_feedback_*.json")):
        previous_payload = json.loads(previous_path.read_text(encoding="utf-8"))
        previous_text = str(previous_payload.get("feedback", "")).strip()
        if previous_text:
            feedback_history.append(previous_text)

    emit_state("KnowledgeScriptWriter", "working")
    emit_progress(
        "KnowledgeScriptWriter",
        10,
        "사람이 남긴 피드백을 기준으로 대본을 다시 쓰고 있습니다.",
    )
    writer_revision = ScriptWriter(PROJECT_ROOT).revise(
        package.selected_candidate,
        package.scientific_research,
        package.historical_research,
        current_script,
        user_feedback,
        feedback_history,
    )
    writer_revision_path = (
        run_dir / f"08_script_revision_{revision_number:02d}_writer.json"
    )
    save_json(writer_revision_path, writer_revision)
    emit_comment("KnowledgeScriptWriter", writer_revision.character_comment)
    emit_progress(
        "KnowledgeScriptWriter",
        100,
        "사람 피드백을 반영한 작가 수정본을 완성했습니다.",
    )
    emit_state("KnowledgeScriptWriter", "idle")

    emit_state("ShortsAdaptationEditor", "working")
    emit_progress(
        "ShortsAdaptationEditor",
        15,
        "수정된 대본 하나만 받아 쉬운 쇼츠 말투로 다시 각색하고 있습니다.",
    )
    adaptation = ShortsAdaptationEditor(PROJECT_ROOT).adapt(writer_revision)
    revised_script = adaptation.adapted_script
    adaptation_revision_path = (
        run_dir / f"08_shorts_adaptation_revision_{revision_number:02d}.json"
    )
    save_json(adaptation_revision_path, adaptation)
    save_json(revision_path, revised_script)
    save_json(run_dir / "08_script.json", revised_script)
    save_json(run_dir / "08_shorts_adaptation.json", adaptation)
    save_json(run_dir / "08_shorts_adapted_script.json", revised_script)
    emit_comment("ShortsAdaptationEditor", adaptation.character_comment)
    emit_progress(
        "ShortsAdaptationEditor",
        100,
        "피드백 수정본의 사실은 유지하고 쇼츠 리듬만 다시 정리했습니다.",
    )
    emit_state("ShortsAdaptationEditor", "idle")

    # Code-based quality checks (replaces AudienceSimulator)
    script_warnings = _simple_script_checks(revised_script)
    if script_warnings:
        for warning in script_warnings:
            emit_comment("QualityCheck", warning)

    emit_state("FactChecker", "working")
    emit_progress(
        "FactChecker",
        15,
        "수정 문장이 사실·학설·추정 구분을 지키는지 다시 확인합니다.",
    )
    fact_check = FactChecker(PROJECT_ROOT).check(
        package.selected_candidate,
        package.scientific_research,
        package.historical_research,
        revised_script,
    )
    if fact_check.verdict == "reject" and not fact_check.blocking_safety_issue:
        fact_check = fact_check.model_copy(
            update={"verdict": "revise", "dramatization_allowed": True}
        )
    save_json(run_dir / "10_fact_check.json", fact_check)
    emit_comment("FactChecker", fact_check.character_comment)
    emit_state("FactChecker", "idle")
    if fact_check.verdict == "reject" and fact_check.blocking_safety_issue:
        update_history(run_id, production_status="fact_check_rejected")
        raise RuntimeError("수정된 대본에 중대한 안전 문제가 있어 사람 검토가 필요합니다.")

    emit_state("VisualPromptGenerator", "working")
    emit_progress(
        "VisualPromptGenerator",
        15,
        "수정된 대사에 맞춰 자막과 장면 지시를 다시 맞추고 있습니다.",
    )
    visuals = VisualPromptGenerator(PROJECT_ROOT).generate(
        revised_script,
        fact_check,
        None,
        package.source_research,
    )
    save_json(run_dir / "12_visual_package.json", visuals)
    emit_comment("VisualPromptGenerator", visuals.character_comment)

    media_plan = MixedMediaPlanner(PROJECT_ROOT).plan(
        visuals,
        package.source_research,
    )
    save_json(run_dir / "13_mixed_media_plan.json", media_plan)
    emit_comment("MixedMediaPlanner", media_plan.character_comment)
    emit_progress("VisualPromptGenerator", 100, "수정 대본 기준 장면 설계를 갱신했습니다.")
    emit_state("VisualPromptGenerator", "idle")

    resolved_run_dir = run_dir.resolve()
    if OUTPUT_ROOT.resolve() not in resolved_run_dir.parents:
        raise RuntimeError("대본 수정 캐시 경로가 올바르지 않습니다.")
    for directory_name in ("frames", "clips", "audio"):
        directory = run_dir / directory_name
        if directory.exists():
            shutil.rmtree(directory)
    for directory in (
        run_dir / "media" / "generated",
        run_dir / "media" / "motion_graphics",
    ):
        if directory.exists():
            shutil.rmtree(directory)
    for filename in (
        "final_short.mp4",
        "narration_short.mp4",
        "thumbnail.png",
        "render_manifest.json",
        "music_selection.json",
    ):
        derivative = run_dir / filename
        if derivative.exists():
            derivative.unlink()

    feedback_payload.update(
        {
            "status": "applied",
            "applied_at": datetime.now().isoformat(timespec="seconds"),
            "revision_number": revision_number,
            "revision_file": str(revision_path.relative_to(PROJECT_ROOT)),
            "writer_report": (
                f"{writer_revision.character_comment} "
                f"쇼츠 각색: {adaptation.character_comment}"
            ),
            "before_hook": current_script.timed_script.hook_0_3,
            "after_hook": revised_script.timed_script.hook_0_3,
        }
    )
    save_json(feedback_path, feedback_payload)

    revised_package = package.model_copy(
        update={
            "script": revised_script,
            "shorts_adaptation": adaptation,
            "audience_simulation": None,
            "fact_check": fact_check,
            "visual_package": visuals,
            "mixed_media_plan": media_plan,
            "human_approval": None,
            "upload_ready": False,
        }
    )
    save_json(final_path, revised_package)
    update_history(
        run_id,
        production_status="package_ready",
        human_approved=False,
        script_revision_count=revision_number,
        latest_script_feedback=user_feedback,
    )
    save_json(
        run_dir / "RESULT.json",
        {
            "status": "package_ready",
            "message": "사람 피드백 반영 완료. 수정된 최종 대본의 재승인을 기다립니다.",
            "script_revision_count": revision_number,
        },
    )
    print(f"대본 수정 완료 · 사람 재승인 대기: {final_path}", flush=True)
    return final_path


def main() -> int:
    parser = argparse.ArgumentParser(description="미스터리 다큐 AI 스튜디오")
    parser.add_argument("--date", help="편성 날짜 YYYY-MM-DD, 기본 오늘")
    parser.add_argument("--schedule", action="store_true", help="오늘 편성만 출력")
    parser.add_argument("--select-run", help="사람이 후보를 채택할 기존 실행번호")
    parser.add_argument("--revise-run", help="사람 피드백으로 대본을 수정할 실행번호")
    parser.add_argument("--feedback-file", help="대본 피드백 JSON 파일")
    parser.add_argument(
        "--direct-topic-file",
        help="토픽헌터에게 직접 전달할 주제가 저장된 JSON 파일",
    )
    parser.add_argument("--candidate-index", type=int, help="채택 후보 번호 0~2")
    parser.add_argument(
        "--direction",
        default="",
        help="사용자 지정 소재 방향. 비우면 요일별 자동 편성",
    )
    args = parser.parse_args()
    target = date.fromisoformat(args.date) if args.date else date.today()
    try:
        if args.schedule:
            print(
                json.dumps(
                    ScheduleManager(PROJECT_ROOT).instruction_for(target),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.select_run:
            if args.candidate_index is None:
                parser.error("--select-run에는 --candidate-index가 필요합니다.")
            continue_selected(args.select_run, args.candidate_index)
            return 0
        if args.revise_run:
            if not args.feedback_file:
                parser.error("--revise-run에는 --feedback-file이 필요합니다.")
            revise_script(args.revise_run, Path(args.feedback_file).resolve())
            return 0
        if args.direct_topic_file:
            request_value = json.loads(
                Path(args.direct_topic_file).read_text(encoding="utf-8")
            )
            produce_direct_topic(target, str(request_value.get("prompt", "")))
            return 0
        generate_candidates(target, args.direction.strip())
        return 0
    except Exception as exc:
        active_run = args.select_run or args.revise_run
        if active_run:
            try:
                current = next(
                    (
                        item
                        for item in load_history()
                        if item.get("run_id") == active_run
                    ),
                    {},
                )
                if current.get("production_status") in {
                    "production_running",
                    "script_revision_running",
                }:
                    update_history(
                        active_run,
                        production_status=(
                            "package_ready"
                            if args.revise_run
                            else "selection_interrupted"
                        ),
                        production_error=str(exc),
                    )
            except Exception:
                pass
        print(f"미스터리 다큐 제작 오류: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
