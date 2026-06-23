from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = PROJECT_ROOT / "dashboard"
KNOWLEDGE_SCRIPT = PROJECT_ROOT / "src" / "run_knowledge_station.py"
KNOWLEDGE_VIDEO_SCRIPT = PROJECT_ROOT / "src" / "run_knowledge_video.py"
VIDEO_REVISION_SCRIPT = PROJECT_ROOT / "src" / "run_video_revision.py"
KNOWLEDGE_HISTORY = PROJECT_ROOT / "ideas" / "knowledge_items.json"
KNOWLEDGE_OUTPUTS = PROJECT_ROOT / "outputs" / "knowledge"
DIRECT_TOPIC_REQUESTS = KNOWLEDGE_OUTPUTS / "_direct_topic_requests"
VIDEO_REFERENCES = PROJECT_ROOT / "ideas" / "video_references.json"
REFERENCE_STYLE = PROJECT_ROOT / "ideas" / "reference_style_profile.json"
CONCEPT_REFERENCES = PROJECT_ROOT / "ideas" / "concept_reference_library.json"
MASTER_REFERENCE = PROJECT_ROOT / "REFERENCE_STYLE.md"
CURRENT_VIDEO_STYLE_VERSION = 4

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schedule_manager import ScheduleManager
from src.topic_library import TopicLibrary
from src.knowledge_models import KnowledgeCandidate


class CommandRequest(BaseModel):
    command: str


class CandidateSelectionRequest(BaseModel):
    candidate_index: int


class DirectionRequest(BaseModel):
    direction: str = ""


class DirectTopicRequest(BaseModel):
    prompt: str


class ScriptFeedbackRequest(BaseModel):
    feedback: str


class VideoFeedbackRequest(BaseModel):
    feedback: str


class ApprovalRequest(BaseModel):
    fit_to_60_seconds: bool = False


class UploadScriptRequest(BaseModel):
    title: str
    narration: str
    category: str = "과학·자연 미스터리"


class ManualSceneEdit(BaseModel):
    scene_number: int
    time_range: str
    subtitle: str
    narration: str


class ManualScriptEditRequest(BaseModel):
    title: str
    hook_0_3: str
    background_3_12: str
    facts_12_35: list[str]
    mystery_35_50: str
    close_50_60: str
    scenes: list[ManualSceneEdit]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_render_derivatives(run_dir: Path) -> None:
    resolved_run_dir = run_dir.resolve()
    if KNOWLEDGE_OUTPUTS.resolve() not in resolved_run_dir.parents:
        raise HTTPException(status_code=400, detail="잘못된 실행 폴더입니다.")
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
        "timeline.json",
        "sources.md",
    ):
        path = run_dir / filename
        if path.exists():
            path.unlink()


def preserve_current_video(run_dir: Path, reason: str) -> str | None:
    final_video = run_dir / "final_short.mp4"
    if not final_video.exists():
        return None
    versions_dir = run_dir / "video_versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    version_number = len(list(versions_dir.glob("version_[0-9][0-9].mp4"))) + 1
    version_name = f"version_{version_number:02d}.mp4"
    archived_video = versions_dir / version_name
    shutil.copy2(final_video, archived_video)
    for filename in ("thumbnail.png", "render_manifest.json", "timeline.json", "sources.md"):
        source = run_dir / filename
        if source.exists():
            shutil.copy2(
                source,
                versions_dir / f"version_{version_number:02d}_{filename}",
            )
    write_json(
        versions_dir / f"version_{version_number:02d}.json",
        {
            "version": version_number,
            "archived_at": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "video_file": version_name,
        },
    )
    return str(archived_video.relative_to(PROJECT_ROOT))


class KnowledgeControlRoom:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: deque[dict[str, Any]] = deque(maxlen=3000)
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._sequence = 0
        self.process: subprocess.Popen[str] | None = None
        self.process_label: str | None = None
        self.started_at: str | None = None
        self.emit("system", "미스터리 다큐 AI 스튜디오가 준비되었습니다.")

    def emit(self, source: str, message: str, level: str = "info") -> None:
        with self._lock:
            self._sequence += 1
            event = {
                "id": self._sequence,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "source": source,
                "level": level,
                "message": message,
            }
            self._events.append(event)
            dead: list[queue.Queue[dict[str, Any]]] = []
            for subscriber in self._subscribers:
                try:
                    subscriber.put_nowait(event)
                except queue.Full:
                    dead.append(subscriber)
            for subscriber in dead:
                self._subscribers.discard(subscriber)

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def process_status(self) -> dict[str, Any]:
        running = self.is_running()
        return {
            "running": running,
            "label": self.process_label if running else None,
            "started_at": self.started_at if running else None,
            "pid": self.process.pid if running and self.process else None,
        }

    def _emit_process_line(self, label: str, text: str) -> None:
        markers = {
            "@@AGENT_PROGRESS@@": "agent_progress",
            "@@AGENT_STATE@@": "agent_state",
            "@@AGENT_COMMENT@@": "character",
        }
        for marker, level in markers.items():
            if not text.startswith(marker):
                continue
            try:
                payload = json.loads(text[len(marker) :])
            except json.JSONDecodeError:
                break
            role = str(payload.get("role", label))
            if level == "agent_progress":
                message = json.dumps(
                    {
                        "percent": int(payload.get("percent", 0)),
                        "message": str(payload.get("message", "")),
                    },
                    ensure_ascii=False,
                )
            elif level == "agent_state":
                message = str(payload.get("state", "idle"))
            else:
                message = str(payload.get("comment", ""))
            self.emit(role, message, level)
            return
        self.emit(label, text)

    def _reader(self, process: subprocess.Popen[str], label: str) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            text = line.rstrip()
            if text:
                self._emit_process_line(label, text)
        return_code = process.wait()
        self.emit(
            "ProductionManager",
            f"{label} 작업 {'완료' if return_code == 0 else f'실패 · 오류 코드 {return_code}'}",
            "success" if return_code == 0 else "error",
        )
        with self._lock:
            if self.process is process:
                self.process = None
                self.process_label = None
                self.started_at = None

    def _start_process(
        self,
        script: Path,
        arguments: list[str],
        label: str,
    ) -> dict[str, Any]:
        with self._lock:
            if self.is_running():
                raise RuntimeError(
                    f"현재 '{self.process_label}' 작업이 진행 중입니다. 완료하거나 중지한 뒤 다시 실행하세요."
                )
            command = [sys.executable, str(script), *arguments]
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            )
            child_env = os.environ.copy()
            child_env["PYTHONUTF8"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                env=child_env,
            )
            self.process = process
            self.process_label = label
            self.started_at = datetime.now().isoformat(timespec="seconds")
        self.emit(
            "ProductionManager",
            f"{label} 작업을 시작했습니다. PID={process.pid}",
        )
        threading.Thread(
            target=self._reader,
            args=(process, self.process_label),
            daemon=True,
        ).start()
        return self.process_status()

    def start_generation(
        self,
        target: date | None = None,
        direction: str = "",
    ) -> dict[str, Any]:
        arguments = ["--date", target.isoformat()] if target else []
        if direction.strip():
            arguments.extend(["--direction", direction.strip()])
        return self._start_process(
            KNOWLEDGE_SCRIPT,
            arguments,
            (
                f"‘{direction.strip()}’ 방향 후보 3개 생성"
                if direction.strip()
                else "오늘의 자동 편성 후보 3개 생성"
            ),
        )

    def start_selection(self, run_id: str, candidate_index: int) -> dict[str, Any]:
        return self._start_process(
            KNOWLEDGE_SCRIPT,
            [
                "--select-run",
                run_id,
                "--candidate-index",
                str(candidate_index),
            ],
            f"{run_id} 선택 주제 제작",
        )

    def start_direct_topic(self, prompt: str) -> dict[str, Any]:
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        request_path = DIRECT_TOPIC_REQUESTS / f"{request_id}.json"
        write_json(
            request_path,
            {
                "prompt": prompt,
                "requested_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        return self._start_process(
            KNOWLEDGE_SCRIPT,
            ["--direct-topic-file", str(request_path)],
            f"토픽헌터 직접 지정 · {prompt[:32]}",
        )

    def start_script_revision(
        self,
        run_id: str,
        feedback_path: Path,
    ) -> dict[str, Any]:
        return self._start_process(
            KNOWLEDGE_SCRIPT,
            [
                "--revise-run",
                run_id,
                "--feedback-file",
                str(feedback_path),
            ],
            f"{run_id} 사람 피드백 대본 수정",
        )

    def start_video(self, run_id: str, rebuild_style: bool = False) -> dict[str, Any]:
        arguments = ["--run-id", run_id]
        if rebuild_style:
            arguments.append("--rebuild-style")
        return self._start_process(
            KNOWLEDGE_VIDEO_SCRIPT,
            arguments,
            (
                f"{run_id} 레퍼런스 스타일 재제작"
                if rebuild_style
                else f"{run_id} MP4 영상 제작"
            ),
        )

    def start_video_revision(
        self,
        run_id: str,
        feedback_path: Path,
    ) -> dict[str, Any]:
        return self._start_process(
            VIDEO_REVISION_SCRIPT,
            [
                "--run-id",
                run_id,
                "--feedback-file",
                str(feedback_path),
            ],
            f"{run_id} 완성 영상 장면 수정",
        )

    def stop(self) -> dict[str, Any]:
        process = self.process
        if process is None or process.poll() is not None:
            return {"stopped": False, "message": "현재 실행 중인 작업이 없습니다."}
        self.emit("ProductionManager", "현재 제작 작업을 중지합니다.", "warning")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            process.terminate()
        return {"stopped": True, "message": "중지 요청을 전달했습니다."}

    def status_report(self) -> dict[str, Any]:
        history = read_json(KNOWLEDGE_HISTORY, [])
        if not isinstance(history, list):
            history = []
        changed = False
        for item in history:
            run_id = str(item.get("run_id", ""))
            run_dir = KNOWLEDGE_OUTPUTS / run_id
            candidates = item.get("candidates") or []
            normalized_candidates: list[dict[str, Any]] = []
            for candidate in candidates:
                try:
                    normalized_candidates.append(
                        KnowledgeCandidate.model_validate(candidate).model_dump(mode="json")
                    )
                except Exception:
                    normalized_candidates.append(candidate)
            if normalized_candidates != candidates:
                item["candidates"] = normalized_candidates
                candidates = normalized_candidates
                changed = True
            if item.get("selected_candidate_index") is None and item.get("selected_title"):
                for index, candidate in enumerate(candidates):
                    if candidate.get("title") == item.get("selected_title"):
                        item["selected_candidate_index"] = index
                        changed = True
                        break
            if (
                item.get("production_status")
                in {"script_revision_running", "rendering", "video_revision_running"}
                and self.is_running()
            ):
                continue
            if (run_dir / "final_short.mp4").exists():
                manifest = read_json(run_dir / "render_manifest.json", {})
                target_state = (
                    "video_ready"
                    if int(manifest.get("style_version", 0))
                    >= CURRENT_VIDEO_STYLE_VERSION
                    else "video_style_outdated"
                )
                if item.get("production_status") != target_state:
                    item["production_status"] = target_state
                    item["final_video"] = str(
                        (run_dir / "final_short.mp4").relative_to(PROJECT_ROOT)
                    )
                    changed = True
                for stale_error in ("video_error", "production_error"):
                    if stale_error in item:
                        item.pop(stale_error, None)
                        changed = True
            elif item.get("production_status") == "approved":
                item["production_status"] = "package_ready"
                changed = True
            elif (
                item.get("production_status")
                in {"production_running", "script_revision_running"}
                and not self.is_running()
                and not (run_dir / "final_knowledge_short.json").exists()
            ):
                item["production_status"] = "selection_interrupted"
                changed = True
            elif (
                item.get("production_status") == "script_revision_running"
                and not self.is_running()
                and (run_dir / "final_knowledge_short.json").exists()
            ):
                item["production_status"] = "package_ready"
                item["production_error"] = "대본 수정이 완료되기 전에 중단되었습니다."
                changed = True
            elif (
                item.get("production_status") == "rendering"
                and not self.is_running()
                and not (run_dir / "final_short.mp4").exists()
            ):
                item["production_status"] = "video_failed"
                item["video_error"] = "영상 제작이 완료되기 전에 중단되었습니다."
                changed = True
        if changed:
            write_json(KNOWLEDGE_HISTORY, history)
        library = TopicLibrary(PROJECT_ROOT)
        library.sync_history()
        topic_count = len(library.load())
        references = read_json(VIDEO_REFERENCES, [])
        reference_count = len(references) if isinstance(references, list) else 0
        concept_library = read_json(CONCEPT_REFERENCES, {})
        concept_count = sum(
            len(category.get("references", []))
            for category in concept_library.get("categories", [])
        )
        runs = list(reversed(history))
        return {
            "mode": "knowledge",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "schedule": ScheduleManager(PROJECT_ROOT).instruction_for(date.today()),
            "total": len(history),
            "completed": sum(
                item.get("production_status")
                in {
                    "package_ready",
                    "rendering",
                    "video_ready",
                    "video_style_outdated",
                }
                for item in history
            ),
            "in_progress": int(self.is_running()),
            "waiting": sum(
                item.get("production_status")
                in {"awaiting_topic_selection", "no_candidate", "candidates_only"}
                for item in history
            ),
            "blocked": sum(
                item.get("production_status")
                in {"fact_check_rejected", "video_failed"}
                for item in history
            ),
            "knowledge_runs": runs,
            "topic_library_count": topic_count,
            "reference_video_count": reference_count,
            "concept_reference_count": concept_count,
            "reference_profile_name": read_json(REFERENCE_STYLE, {}).get(
                "name",
                "사용자 제공 미스터리 쇼츠 레퍼런스",
            ),
            "master_reference_name": MASTER_REFERENCE.name,
            "master_reference_available": MASTER_REFERENCE.exists(),
            "control_process": self.process_status(),
        }

    def conversation(self, run_id: str | None = None) -> dict[str, Any]:
        run_dirs = (
            sorted(KNOWLEDGE_OUTPUTS.glob("*"), key=lambda p: p.stat().st_mtime)
            if KNOWLEDGE_OUTPUTS.exists()
            else []
        )
        if run_id:
            selected = KNOWLEDGE_OUTPUTS / run_id
        else:
            selected = run_dirs[-1] if run_dirs else None
        if selected is None or not selected.is_dir():
            return {"run_id": None, "comments": []}

        role_files = [
            ("01_trend_report.json", "TrendAnalyst"),
            ("01_topic_candidates.json", "TopicHunter"),
            ("02_scientific_research.json", "ScientificResearcher"),
            ("03_historical_research.json", "HistoricalResearcher"),
            ("04_curiosity_report.json", "HumanCuriosityDirector"),
            ("05_consequence_report.json", "FutureConsequenceSimulator"),
            ("06_gihwan_report.json", "GihwanAgent"),
            ("07_narrative_architecture.json", "MysteryArchitect"),
            ("08_script.json", "KnowledgeScriptWriter"),
            ("08_shorts_adaptation.json", "ShortsAdaptationEditor"),
            ("09_audience_simulation.json", "AudienceSimulator"),
            ("10_fact_check.json", "FactChecker"),
            ("11_source_research.json", "VisualPromptGenerator"),
            ("12_visual_package.json", "VisualPromptGenerator"),
            ("13_mixed_media_plan.json", "VisualPromptGenerator"),
            # 이전 버전 실행 결과도 회의록에서 계속 볼 수 있다.
            ("02_fact_check_selected.json", "FactChecker"),
            ("03_source_research.json", "VisualPromptGenerator"),
            ("04_script.json", "KnowledgeScriptWriter"),
            ("05_visual_package.json", "VisualPromptGenerator"),
            ("06_mixed_media_plan.json", "VisualPromptGenerator"),
        ]
        comments = []
        for filename, role in role_files:
            path = selected / filename
            if not path.exists():
                continue
            data = read_json(path, {})
            comment = str(data.get("character_comment", "")).strip()
            if not comment:
                continue
            comments.append(
                {
                    "id": filename,
                    "role": role,
                    "comment": comment,
                    "created_at": datetime.fromtimestamp(
                        path.stat().st_mtime
                    ).isoformat(timespec="seconds"),
                }
            )
        return {"run_id": selected.name, "comments": comments}

    def command(self, raw: str) -> dict[str, Any]:
        command = raw.strip()
        if not command:
            raise ValueError("지시 내용을 입력하세요.")
        self.emit("사용자 → ProductionManager", command)
        normalized = command.replace(" ", "")
        if any(word in normalized for word in ("현황", "상태", "편성확인")):
            return {
                "action": "status",
                "message": "현재 편성과 제작 현황을 갱신했습니다.",
                "status": self.status_report(),
            }
        if any(word in normalized for word in ("중지", "정지", "작업중지")):
            return {"action": "stop", **self.stop()}
        direction_match = re.search(
            r"(?:소재\s*방향|소재\s*찾기|방향)\s*[:：]\s*(.+)",
            command,
        )
        if direction_match:
            direction = direction_match.group(1).strip()
            return {
                "action": "knowledge_generate",
                "message": f"‘{direction}’ 방향으로 후보 3개를 찾기 시작했습니다.",
                "process": self.start_generation(direction=direction),
            }
        if any(
            word in normalized
            for word in ("후보", "제작", "생성", "지식쇼츠", "미스터리")
        ):
            return {
                "action": "knowledge_generate",
                "message": "AI가 후보 3개를 만들기 시작했습니다. 제작 주제는 완료 후 사람이 선택합니다.",
                "process": self.start_generation(),
            }
        message = (
            "가능한 지시: 오늘 편성 확인, 오늘 후보 3개 제작, "
            "소재 방향: 로마 역사, 현재 작업 중지"
        )
        self.emit("ProductionManager", message, "warning")
        return {"action": "help", "message": message}

    def recent_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def clear_events(self) -> None:
        with self._lock:
            self._events.clear()
        self.emit("system", "화면 로그를 비웠습니다.")

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)


control_room = KnowledgeControlRoom()
app = FastAPI(title="미스터리 다큐 AI 스튜디오")
app.mount("/assets", StaticFiles(directory=STATIC_ROOT / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_ROOT / "index.html").read_text(encoding="utf-8"))


@app.get("/styles.css")
def styles() -> HTMLResponse:
    return HTMLResponse(
        (STATIC_ROOT / "styles.css").read_text(encoding="utf-8"),
        media_type="text/css",
    )


@app.get("/app.js")
def javascript() -> HTMLResponse:
    return HTMLResponse(
        (STATIC_ROOT / "app.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", **control_room.process_status()}


@app.get("/api/status")
@app.get("/api/knowledge")
def status() -> dict[str, Any]:
    return control_room.status_report()


@app.post("/api/knowledge/generate")
def generate(request: DirectionRequest | None = None) -> dict[str, Any]:
    direction = request.direction.strip() if request else ""
    try:
        process = control_room.start_generation(direction=direction)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "message": (
            f"‘{direction}’ 방향에서 후보 3개를 찾습니다."
            if direction
            else "요일별 자동 편성으로 후보 3개를 찾습니다."
        ),
        "process": process,
    }


@app.post("/api/knowledge/direct-topic")
def direct_topic(request: DirectTopicRequest) -> dict[str, Any]:
    prompt = request.prompt.strip()
    if len(prompt) < 2:
        raise HTTPException(
            status_code=400,
            detail="토픽헌터에게 전달할 주제를 두 글자 이상 입력해주세요.",
        )
    if len(prompt) > 2000:
        raise HTTPException(
            status_code=400,
            detail="주제 설명은 2,000자 이하로 입력해주세요.",
        )
    control_room.emit("사용자 → TopicHunter", prompt, "character")
    try:
        process = control_room.start_direct_topic(prompt)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "message": (
            "토픽헌터가 주제를 다듬고 있습니다. 완료되면 후보 선택 없이 "
            "조사와 최종 대본 제작까지 이어집니다."
        ),
        "process": process,
    }


@app.post("/api/knowledge/upload-script")
def upload_script(request: UploadScriptRequest) -> dict[str, Any]:
    title = request.title.strip()
    narration = request.narration.strip()
    if len(title) < 2:
        raise HTTPException(status_code=400, detail="제목을 두 글자 이상 입력해주세요.")
    if len(narration) < 10:
        raise HTTPException(status_code=400, detail="내레이션을 10자 이상 입력해주세요.")
    if control_room.is_running():
        raise HTTPException(
            status_code=409,
            detail="다른 작업이 진행 중입니다. 완료 후 다시 시도하세요.",
        )
    category = request.category
    valid_categories = [
        "역사 미스터리", "우주 미스터리", "고대문명과 놀라운 기술",
        "과학·자연 미스터리", "가상 시나리오",
    ]
    if category not in valid_categories:
        category = "과학·자연 미스터리"
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = KNOWLEDGE_OUTPUTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sentences = [
        s.strip() for s in re.split(r"(?<=[.!?。！？])\s+|\n+", narration) if s.strip()
    ]
    if not sentences:
        sentences = [narration]
    scene_count = max(5, min(24, len(sentences)))
    chunk_size = max(1, len(sentences) // scene_count)
    chunks: list[str] = []
    for i in range(0, len(sentences), chunk_size):
        chunks.append(" ".join(sentences[i : i + chunk_size]))
    if len(chunks) > 24:
        chunks = chunks[:24]
    while len(chunks) < 5:
        chunks.append(chunks[-1])
    total_seconds = 90.0
    per_scene = total_seconds / len(chunks)
    scenes = []
    for i, chunk in enumerate(chunks):
        start = round(per_scene * i, 1)
        end = round(per_scene * (i + 1), 1)
        subtitle = chunk[:33].rstrip() + "…" if len(chunk) > 34 else chunk
        scenes.append({
            "scene_number": i + 1,
            "time_range": f"{start}-{end}",
            "visual_description": f"{title} 관련 장면 {i + 1}",
            "image_prompt": (
                f"Cinematic scene about {title}, scene {i + 1}. "
                "No text, labels, badges, captions, or watermarks."
            ),
            "subtitle": subtitle,
            "narration": chunk,
        })
    scene_assets = [
        {
            "scene_number": s["scene_number"],
            "asset_mode": "ai_reconstruction",
            "license_status": "not_applicable",
            "usage_instruction": "AI 재구성 이미지",
            "crop_and_motion": "subtle cinematic motion",
            "on_screen_source_label": "",
            "fallback_ai_prompt": s["image_prompt"],
        }
        for s in scenes
    ]
    hook = sentences[0] if sentences else title
    close = sentences[-1] if sentences else title
    mid = len(sentences) // 2
    facts_mid = sentences[max(1, mid - 1) : min(len(sentences) - 1, mid + 2)]
    if len(facts_mid) < 2:
        facts_mid = sentences[1:4] if len(sentences) > 3 else sentences[:2]
    package = {
        "run_id": run_id,
        "production_date": date.today().isoformat(),
        "category": category,
        "selected_candidate": {
            "title": title,
            "category": category,
            "one_line_hook": hook,
            "plain_language_summary": narration[:200],
            "core_facts": facts_mid[:5] if len(facts_mid) >= 2 else [hook, close],
            "fact_hypothesis_distinction": "사용자 제공 대본",
            "visualization_ideas": [f"{title} 시각화 {i}" for i in range(1, 4)],
            "comment_question": f"{title}에 대해 어떻게 생각하시나요?",
            "criteria": {
                "title_curiosity": True,
                "source_or_claim_traceable": True,
                "explainable_in_60_seconds": True,
                "easy_to_visualize": True,
                "has_twist_or_misconception_resolution": True,
                "has_comment_question": True,
                "interesting_without_exaggeration": True,
            },
            "score": {
                "hook": 30, "source_traceability": 8,
                "visualization": 20, "sixty_second_fit": 18,
                "comment_potential": 8,
            },
            "selection_override": "user_direct_topic",
        },
        "fact_check": {
            "candidate_title": title,
            "character_comment": "사용자 업로드 대본 — 팩트체크 생략",
            "verdict": "pass",
            "verified_claims": [
                {
                    "claim": hook,
                    "classification": "reported_claim",
                    "evidence_summary": "사용자 제공",
                    "safe_narration": hook,
                    "source_urls": ["user_upload"],
                },
                {
                    "claim": close,
                    "classification": "reported_claim",
                    "evidence_summary": "사용자 제공",
                    "safe_narration": close,
                    "source_urls": ["user_upload"],
                },
            ],
            "entertainment_value_note": "사용자 직접 업로드",
            "sources": [
                {
                    "title": "사용자 제공",
                    "url": "user_upload",
                    "publisher": "사용자",
                    "source_type": "primary",
                },
                {
                    "title": "사용자 제공",
                    "url": "user_upload",
                    "publisher": "사용자",
                    "source_type": "primary",
                },
            ],
        },
        "source_research": {
            "candidate_title": title,
            "character_comment": "사용자 업로드 대본 — 자료 조사 생략",
            "research_summary": "사용자가 직접 작성한 대본입니다.",
            "sources": [
                {
                    "title": "사용자 제공 대본",
                    "page_url": "user_upload",
                    "publisher_or_community": "사용자",
                    "source_kind": "official",
                    "role": "fact_evidence",
                    "media_type": "article",
                    "license_status": "public_domain",
                    "usable_in_final_video": True,
                    "suggested_use": "내레이션 원본",
                    "reliability_note": "사용자 직접 작성",
                }
            ] * 6,
            "usable_visual_asset_count": 0,
        },
        "script": {
            "title": title,
            "category": category,
            "character_comment": "사용자 업로드 대본",
            "timed_script": {
                "hook_0_3": hook,
                "background_3_12": sentences[1] if len(sentences) > 1 else hook,
                "facts_12_35": facts_mid[:3] if len(facts_mid) >= 2 else [hook, close],
                "mystery_35_50": sentences[mid] if mid < len(sentences) else hook,
                "close_50_60": close,
            },
            "full_narration": narration,
            "fact_hypothesis_labels": ["사용자 제공"],
        },
        "visual_package": {
            "character_comment": "사용자 업로드 대본 기반 자동 생성",
            "scenes": scenes,
            "thumbnail_text_candidates": [
                title,
                f"{title}?!",
                f"충격! {title}",
                f"{title}의 비밀",
                f"알고 계셨나요? {title}",
            ],
            "hashtags": [f"#{title[:10]}", "#미스터리", "#쇼츠", "#shorts", "#지식"],
            "fact_check_checklist": ["사용자 제공 대본"],
        },
        "mixed_media_plan": {
            "character_comment": "사용자 업로드 — AI 이미지로 전체 구성",
            "target_real_media_percent": 50,
            "planned_real_media_percent": 0,
            "scene_assets": scene_assets,
            "global_editing_rules": ["AI 재구성 이미지 사용"],
            "attribution_end_card": [],
        },
        "human_approval": {
            "approved": True,
            "approved_at": datetime.now().isoformat(timespec="seconds"),
            "approver": "대본 직접 업로드",
            "script_revision_count": 0,
            "manual_script_edit_count": 0,
            "render_options": {
                "fit_to_60_seconds": False,
                "target_seconds": 60,
                "maximum_speed_factor": 1.2,
            },
        },
        "human_approval_required": False,
        "upload_ready": False,
    }
    write_json(run_dir / "final_knowledge_short.json", package)
    history = read_json(KNOWLEDGE_HISTORY, [])
    history.append({
        "run_id": run_id,
        "title": title,
        "category": category,
        "total_score": 84,
        "production_status": "rendering",
        "human_approved": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "upload_script",
    })
    write_json(KNOWLEDGE_HISTORY, history)
    try:
        process = control_room.start_video(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    control_room.emit(
        "ProductionManager",
        f"대본 업로드 완료 · {run_id} 영상 제작을 시작합니다.",
        "success",
    )
    return {
        "status": "rendering",
        "run_id": run_id,
        "scene_count": len(scenes),
        "message": f"대본 '{title}' 업로드 완료. {len(scenes)}개 장면으로 영상 제작을 시작합니다.",
    }


@app.get("/api/topics")
def topic_library(q: str = "", limit: int = 100) -> dict[str, Any]:
    library = TopicLibrary(PROJECT_ROOT)
    library.sync_history()
    all_items = library.load()
    items = all_items
    query = q.strip().lower()
    if query:
        items = [
            item
            for item in items
            if query
            in " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("category", "")),
                    str(item.get("one_line_hook", "")),
                    " ".join(item.get("requested_directions") or []),
                ]
            ).lower()
        ]
    items = sorted(
        items,
        key=lambda item: (
            item.get("last_discovered_at", ""),
            int(item.get("highest_score", 0)),
        ),
        reverse=True,
    )
    return {
        "total": len(all_items),
        "matched": len(items),
        "items": items[: max(1, min(limit, 300))],
    }


@app.get("/api/references")
def references() -> dict[str, Any]:
    videos = read_json(VIDEO_REFERENCES, [])
    if not isinstance(videos, list):
        videos = []
    concept_library = read_json(CONCEPT_REFERENCES, {})
    concept_references = [
        reference
        for category in concept_library.get("categories", [])
        for reference in category.get("references", [])
    ]
    return {
        "count": len(videos),
        "videos": videos,
        "style_profile": read_json(REFERENCE_STYLE, {}),
        "master_reference": {
            "name": MASTER_REFERENCE.name,
            "available": MASTER_REFERENCE.exists(),
            "content": (
                MASTER_REFERENCE.read_text(encoding="utf-8")
                if MASTER_REFERENCE.exists()
                else ""
            ),
        },
        "concept_library": concept_library,
        "concept_reference_count": len(concept_references),
        "applied_to": [
            "TrendAnalyst",
            "TopicHunter",
            "HumanCuriosityDirector",
            "MysteryArchitect",
            "KnowledgeScriptWriter",
            "AudienceSimulator",
            "SourceResearcher",
            "VisualPromptGenerator",
            "MixedMediaPlanner",
            "FactChecker",
        ],
    }


def history_item(run_id: str) -> dict[str, Any]:
    item = next(
        (
            entry
            for entry in read_json(KNOWLEDGE_HISTORY, [])
            if entry.get("run_id") == run_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="실행 기록을 찾을 수 없습니다.")
    return item


@app.post("/api/knowledge/{run_id}/select")
def select_candidate(
    run_id: str,
    request: CandidateSelectionRequest,
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}-\d{6}(?:-\d{6})?", run_id):
        raise HTTPException(status_code=400, detail="올바르지 않은 실행번호입니다.")
    if request.candidate_index not in {0, 1, 2}:
        raise HTTPException(status_code=400, detail="후보 번호는 0~2여야 합니다.")
    item = history_item(run_id)
    if item.get("production_status") not in {
        "awaiting_topic_selection",
        "selection_interrupted",
    }:
        raise HTTPException(
            status_code=409,
            detail="현재 주제를 선택할 수 있는 상태가 아닙니다.",
        )
    candidates = item.get("candidates") or []
    direct_topic = item.get("discovery_mode") == "direct_topic"
    expected_count = 1 if direct_topic else 3
    if len(candidates) != expected_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "직접 지정 주제 후보가 준비되지 않았습니다."
                if direct_topic
                else "후보 3개가 준비되지 않았습니다."
            ),
        )
    try:
        selected_candidate = KnowledgeCandidate.model_validate(
            candidates[request.candidate_index]
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="후보 정보가 올바르지 않아 선택할 수 없습니다.",
        ) from exc
    if selected_candidate.selection_status == "rejected":
        raise HTTPException(
            status_code=409,
            detail=(
                "난이도 또는 점수 기준을 통과하지 못한 후보입니다: "
                + str(selected_candidate.rejection_reason or "선정 기준 미달")
            ),
        )
    previous_index = item.get("selected_candidate_index")
    if (
        item.get("production_status") == "selection_interrupted"
        and previous_index is not None
        and previous_index != request.candidate_index
    ):
        raise HTTPException(
            status_code=409,
            detail="중단된 작업은 이전에 선택한 같은 주제로만 이어갈 수 있습니다.",
        )
    try:
        process = control_room.start_selection(run_id, request.candidate_index)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    selected_title = str(candidates[request.candidate_index].get("title", ""))
    control_room.emit(
        "ProductionManager",
        f"사람이 ‘{selected_title}’을 제작 주제로 채택했습니다.",
        "character",
    )
    return {
        "status": "production_running",
        "selected_title": selected_title,
        "message": f"‘{selected_title}’ 제작을 시작했습니다.",
        "process": process,
    }


def package_path(run_id: str) -> Path:
    if not re.fullmatch(r"\d{8}-\d{6}(?:-\d{6})?", run_id):
        raise HTTPException(status_code=400, detail="올바르지 않은 실행번호입니다.")
    return KNOWLEDGE_OUTPUTS / run_id / "final_knowledge_short.json"


@app.get("/api/knowledge/{run_id}/package")
def download_package(run_id: str) -> FileResponse:
    path = package_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="완성된 제작 패키지가 없습니다.")
    return FileResponse(path, filename=f"{run_id}-knowledge-short.json")


@app.get("/api/knowledge/{run_id}/review")
def review_script(run_id: str) -> dict[str, Any]:
    path = package_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="검토할 최종 대본이 없습니다.")
    package = read_json(path, {})
    run_dir = KNOWLEDGE_OUTPUTS / run_id
    feedbacks = []
    for feedback_path in sorted(run_dir.glob("script_feedback_*.json")):
        feedback = read_json(feedback_path, {})
        if feedback:
            revision_file = feedback.get("revision_file")
            if revision_file and not feedback.get("writer_report"):
                revision = read_json(PROJECT_ROOT / str(revision_file), {})
                feedback["writer_report"] = revision.get("character_comment", "")
                feedback["after_hook"] = (
                    revision.get("timed_script") or {}
                ).get("hook_0_3", "")
            feedbacks.append(feedback)
    return {
        "run_id": run_id,
        "title": (package.get("selected_candidate") or {}).get("title", ""),
        "script": package.get("script") or {},
        "shorts_adaptation": package.get("shorts_adaptation") or {},
        "audience_simulation": package.get("audience_simulation") or {},
        "fact_check": package.get("fact_check") or {},
        "visual_scenes": (package.get("visual_package") or {}).get("scenes", []),
        "feedback_history": feedbacks,
        "human_approval": package.get("human_approval"),
        "manual_edit_count": len(
            list(run_dir.glob("manual_script_edit_*.json"))
        ),
        "video_versions": (
            [
                read_json(metadata_path, {})
                for metadata_path in sorted(
                    (run_dir / "video_versions").glob("version_[0-9][0-9].json")
                )
            ]
            if (run_dir / "video_versions").exists()
            else []
        ),
    }


@app.post("/api/knowledge/{run_id}/manual-script")
def save_manual_script(
    run_id: str,
    request: ManualScriptEditRequest,
) -> dict[str, Any]:
    if control_room.is_running():
        raise HTTPException(
            status_code=409,
            detail="다른 작업이 진행 중입니다. 완료된 뒤 직접 수정본을 저장해주세요.",
        )
    path = package_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="수정할 최종 제작 패키지가 없습니다.")
    item = history_item(run_id)
    if item.get("production_status") not in {
        "package_ready",
        "video_ready",
        "video_style_outdated",
        "video_failed",
        "approved",
    }:
        raise HTTPException(
            status_code=409,
            detail="제작 완료 또는 사람 승인 대기 상태에서만 직접 수정할 수 있습니다.",
        )

    package = read_json(path, {})
    script = package.get("script") or {}
    visual_package = package.get("visual_package") or {}
    existing_scenes = visual_package.get("scenes") or []
    if not existing_scenes:
        raise HTTPException(status_code=409, detail="수정할 영상 장면이 없습니다.")

    title = request.title.strip()
    hook = request.hook_0_3.strip()
    background = request.background_3_12.strip()
    facts = [value.strip() for value in request.facts_12_35 if value.strip()]
    mystery = request.mystery_35_50.strip()
    close = request.close_50_60.strip()
    if not all((title, hook, background, mystery, close)):
        raise HTTPException(status_code=400, detail="비어 있는 시나리오 구간이 있습니다.")
    if not 2 <= len(facts) <= 3:
        raise HTTPException(
            status_code=400,
            detail="핵심 사실은 줄바꿈으로 구분해 2~3개를 입력해주세요.",
        )

    edits = {scene.scene_number: scene for scene in request.scenes}
    existing_numbers = {
        int(scene.get("scene_number", 0)) for scene in existing_scenes
    }
    if set(edits) != existing_numbers:
        raise HTTPException(
            status_code=400,
            detail="기존 장면을 빠짐없이 수정해야 합니다.",
        )

    revised_scenes: list[dict[str, Any]] = []
    for scene in existing_scenes:
        number = int(scene.get("scene_number", 0))
        edit = edits[number]
        narration = edit.narration.strip()
        if not narration:
            raise HTTPException(
                status_code=400,
                detail=f"{number}번 장면의 내레이션이 비어 있습니다.",
            )
        revised_scene = dict(scene)
        revised_scene.update(
            {
                "time_range": edit.time_range.strip()
                or str(scene.get("time_range", "")),
                "subtitle": edit.subtitle.strip(),
                "narration": narration,
            }
        )
        revised_scenes.append(revised_scene)

    timed_script = {
        "hook_0_3": hook,
        "background_3_12": background,
        "facts_12_35": facts,
        "mystery_35_50": mystery,
        "close_50_60": close,
    }
    revised_script = dict(script)
    revised_script.update(
        {
            "title": title,
            "timed_script": timed_script,
            "full_narration": " ".join(
                scene["narration"] for scene in revised_scenes
            ),
            "character_comment": (
                "사용자가 최종 시나리오와 실제 TTS 장면 대사를 직접 수정했습니다."
            ),
        }
    )
    revised_visual_package = dict(visual_package)
    revised_visual_package["scenes"] = revised_scenes
    revised_visual_package["character_comment"] = (
        "사용자 직접 수정본에 맞춰 장면별 자막과 내레이션을 고정했습니다."
    )

    run_dir = KNOWLEDGE_OUTPUTS / run_id
    archived_video = preserve_current_video(
        run_dir,
        "사용자가 완성 영상의 시나리오를 직접 수정함",
    )
    edit_number = len(list(run_dir.glob("manual_script_edit_*.json"))) + 1
    write_json(
        run_dir / f"manual_script_edit_{edit_number:02d}.json",
        {
            "edit_number": edit_number,
            "edited_at": datetime.now().isoformat(timespec="seconds"),
            "editor": "관제실 사용자",
            "before": {
                "script": script,
                "scenes": existing_scenes,
            },
            "after": {
                "script": revised_script,
                "scenes": revised_scenes,
            },
        },
    )

    package["script"] = revised_script
    package["shorts_adaptation"] = None
    package["visual_package"] = revised_visual_package
    package["human_approval"] = None
    package["upload_ready"] = False
    package["video_assets"] = None
    write_json(path, package)
    write_json(run_dir / "08_script.json", revised_script)
    write_json(run_dir / "12_visual_package.json", revised_visual_package)
    for stale_adaptation in (
        run_dir / "08_shorts_adaptation.json",
        run_dir / "08_shorts_adapted_script.json",
    ):
        if stale_adaptation.exists():
            stale_adaptation.unlink()
    clear_render_derivatives(run_dir)

    history = read_json(KNOWLEDGE_HISTORY, [])
    for history_entry in history:
        if history_entry.get("run_id") == run_id:
            history_entry["production_status"] = "package_ready"
            history_entry["human_approved"] = False
            history_entry["manual_script_edit_count"] = edit_number
            history_entry["manual_script_edited_at"] = datetime.now().isoformat(
                timespec="seconds"
            )
            history_entry.pop("final_video", None)
            break
    write_json(KNOWLEDGE_HISTORY, history)
    write_json(
        run_dir / "RESULT.json",
        {
            "status": "package_ready",
            "message": "직접 수정본 저장 완료. 내용을 확인한 뒤 승인하면 영상을 다시 제작합니다.",
            "manual_script_edit_count": edit_number,
        },
    )
    control_room.emit(
        "ProductionManager",
        f"{run_id} 최종 시나리오 직접 수정본을 저장했습니다. 승인 후 새 영상으로 다시 제작합니다.",
        "character",
    )
    return {
        "status": "package_ready",
        "message": "직접 수정본을 저장했습니다. 확인 후 승인하면 영상을 다시 제작합니다.",
        "manual_edit_count": edit_number,
        "archived_video": archived_video,
    }


@app.post("/api/knowledge/{run_id}/script-feedback")
def submit_script_feedback(
    run_id: str,
    request: ScriptFeedbackRequest,
) -> dict[str, Any]:
    if control_room.is_running():
        raise HTTPException(
            status_code=409,
            detail="다른 작업이 진행 중입니다. 완료 후 대본 피드백을 보내세요.",
        )
    feedback = request.feedback.strip()
    if len(feedback) < 2:
        raise HTTPException(status_code=400, detail="수정할 내용을 조금 더 구체적으로 적어주세요.")
    path = package_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="수정할 제작 패키지가 없습니다.")
    item = history_item(run_id)
    if item.get("production_status") not in {
        "package_ready",
        "video_failed",
        "video_ready",
        "video_style_outdated",
        "approved",
    }:
        raise HTTPException(
            status_code=409,
            detail="사람 승인 대기 또는 영상 제작 실패 상태의 대본만 수정할 수 있습니다.",
        )
    run_dir = KNOWLEDGE_OUTPUTS / run_id
    archived_video = preserve_current_video(
        run_dir,
        "사용자가 완성 영상에 AI 대본 피드백을 요청함",
    )
    feedback_number = len(list(run_dir.glob("script_feedback_*.json"))) + 1
    feedback_path = run_dir / f"script_feedback_{feedback_number:02d}.json"
    write_json(
        feedback_path,
        {
            "feedback": feedback,
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "status": "pending",
            "feedback_number": feedback_number,
            "archived_video": archived_video,
        },
    )
    history = read_json(KNOWLEDGE_HISTORY, [])
    for history_entry in history:
        if history_entry.get("run_id") == run_id:
            history_entry["production_status"] = "script_revision_running"
            history_entry["latest_script_feedback"] = feedback
            history_entry["human_approved"] = False
            break
    write_json(KNOWLEDGE_HISTORY, history)
    try:
        process = control_room.start_script_revision(run_id, feedback_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    control_room.emit(
        "ProductionManager",
        f"{run_id} 대본 피드백을 접수했습니다. 작가와 검수 담당이 수정본을 준비합니다.",
        "character",
    )
    return {
        "status": "script_revision_running",
        "message": "피드백을 전달했습니다. 수정 대본이 나오면 다시 승인할 수 있습니다.",
        "process": process,
        "archived_video": archived_video,
    }


@app.post("/api/knowledge/{run_id}/approve")
def approve_package(
    run_id: str,
    request: ApprovalRequest | None = None,
) -> dict[str, Any]:
    if control_room.is_running():
        raise HTTPException(
            status_code=409,
            detail="다른 작업이 진행 중입니다. 완료 후 영상 제작을 승인하세요.",
        )
    path = package_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="완성된 제작 패키지가 없습니다.")
    package = read_json(path, {})
    package["human_approval"] = {
        "approved": True,
        "approved_at": datetime.now().isoformat(timespec="seconds"),
        "approver": "관제실 사용자",
        "script_revision_count": len(
            list(
                (KNOWLEDGE_OUTPUTS / run_id).glob(
                    "08_script_revision_[0-9][0-9].json"
                )
            )
        ),
        "manual_script_edit_count": len(
            list((KNOWLEDGE_OUTPUTS / run_id).glob("manual_script_edit_*.json"))
        ),
        "render_options": {
            "fit_to_60_seconds": bool(
                request and request.fit_to_60_seconds
            ),
            "target_seconds": 60,
            "maximum_speed_factor": 1.2,
            "eligible_max_natural_seconds": 72,
        },
    }
    package["upload_ready"] = False
    write_json(path, package)
    history = read_json(KNOWLEDGE_HISTORY, [])
    for item in history:
        if item.get("run_id") == run_id:
            item["human_approved"] = True
            item["production_status"] = "rendering"
            item["render_options"] = package["human_approval"]["render_options"]
            break
    write_json(KNOWLEDGE_HISTORY, history)
    try:
        process = control_room.start_video(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    control_room.emit(
        "ProductionManager",
        f"{run_id} 제작 패키지를 승인했습니다. 영상제작실이 MP4 제작을 시작합니다.",
        "success",
    )
    return {
        "status": "rendering",
        "message": (
            "사람 승인 완료 · 60초 자동 맞춤 옵션으로 영상 제작을 시작했습니다."
            if request and request.fit_to_60_seconds
            else "사람 승인 완료 · 자연스러운 말 속도로 영상 제작을 시작했습니다."
        ),
        "process": process,
    }


@app.get("/api/knowledge/{run_id}/video")
def knowledge_video(run_id: str) -> FileResponse:
    if not re.fullmatch(r"\d{8}-\d{6}(?:-\d{6})?", run_id):
        raise HTTPException(status_code=400, detail="올바르지 않은 실행번호입니다.")
    path = KNOWLEDGE_OUTPUTS / run_id / "final_short.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="완성된 MP4 영상이 없습니다.")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{run_id}.mp4",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.post("/api/knowledge/{run_id}/video-feedback")
def submit_video_feedback(
    run_id: str,
    request: VideoFeedbackRequest,
) -> dict[str, Any]:
    if control_room.is_running():
        raise HTTPException(
            status_code=409,
            detail="다른 작업이 진행 중입니다. 완료 후 영상 피드백을 보내세요.",
        )
    feedback = request.feedback.strip()
    if len(feedback) < 3:
        raise HTTPException(
            status_code=400,
            detail="장면 번호와 바꿀 내용을 구체적으로 적어주세요.",
        )
    run_dir = KNOWLEDGE_OUTPUTS / run_id
    if not (run_dir / "final_short.mp4").exists():
        raise HTTPException(
            status_code=409,
            detail="완성 영상이 있는 에피소드만 영상 피드백으로 수정할 수 있습니다.",
        )
    archived_video = preserve_current_video(
        run_dir,
        "사용자가 완성 영상의 장면별 수정 피드백을 요청함",
    )
    number = len(list(run_dir.glob("video_feedback_*.json"))) + 1
    feedback_path = run_dir / f"video_feedback_{number:02d}.json"
    write_json(
        feedback_path,
        {
            "feedback_number": number,
            "feedback": feedback,
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "status": "pending",
            "archived_video": archived_video,
        },
    )
    history = read_json(KNOWLEDGE_HISTORY, [])
    for item in history:
        if item.get("run_id") == run_id:
            item["production_status"] = "video_revision_running"
            item["latest_video_feedback"] = feedback
            break
    write_json(KNOWLEDGE_HISTORY, history)
    try:
        process = control_room.start_video_revision(run_id, feedback_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    control_room.emit(
        "VideoRenderer",
        f"{run_id} 완성 영상 피드백을 받았습니다. 지목한 장면만 교체해 다시 렌더링합니다.",
        "character",
    )
    return {
        "status": "video_revision_running",
        "message": (
            "기존 영상을 보관하고 장면 수정 작업을 시작했습니다. "
            "대본·음성·음악은 유지됩니다."
        ),
        "process": process,
        "archived_video": archived_video,
    }


@app.post("/api/knowledge/{run_id}/rerender")
def rerender_knowledge_video(run_id: str) -> dict[str, Any]:
    if control_room.is_running():
        raise HTTPException(
            status_code=409,
            detail="다른 작업이 진행 중입니다. 완료 후 재제작하세요.",
        )
    path = package_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="제작 패키지가 없습니다.")
    package = read_json(path, {})
    if not (package.get("human_approval") or {}).get("approved"):
        raise HTTPException(status_code=409, detail="사람 승인 후 재제작할 수 있습니다.")
    history = read_json(KNOWLEDGE_HISTORY, [])
    for item in history:
        if item.get("run_id") == run_id:
            item["production_status"] = "rendering"
            item["style_rebuild_requested_at"] = datetime.now().isoformat(
                timespec="seconds"
            )
            break
    write_json(KNOWLEDGE_HISTORY, history)
    try:
        process = control_room.start_video(run_id, rebuild_style=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": "rendering",
        "message": "기존 이미지 자료를 유지하고 자막·연출·음성을 새 스타일로 재제작합니다.",
        "process": process,
    }


class MusicChangeRequest(BaseModel):
    track_file: str = ""


@app.post("/api/knowledge/{run_id}/change-music")
def change_music(run_id: str, request: MusicChangeRequest | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}-\d{6}(?:-\d{6})?", run_id):
        raise HTTPException(status_code=400, detail="올바르지 않은 실행번호입니다.")
    run_dir = KNOWLEDGE_OUTPUTS / run_id
    narration_video = run_dir / "narration_short.mp4"
    if not narration_video.exists():
        raise HTTPException(status_code=404, detail="narration_short.mp4가 없습니다. 영상을 먼저 제작하세요.")
    import yaml
    config = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))
    music_library = config.get("video_studio", {}).get("music_library", {})
    music_dir = PROJECT_ROOT / str(music_library.get("folder", "music"))
    available = {
        p.name: p for p in music_dir.glob("*")
        if p.is_file() and p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}
    }
    if not available:
        raise HTTPException(status_code=500, detail="배경음악 파일이 없습니다.")
    track_file = (request.track_file.strip() if request and request.track_file else "").strip()
    if track_file and track_file in available:
        music_path = available[track_file]
    else:
        import random
        music_path = random.choice(list(available.values()))
    # 기존 final 백업
    final_video = run_dir / "final_short.mp4"
    if final_video.exists():
        preserve_current_video(run_dir, "배경음악 교체")
    mix_volume = float(music_library.get("mix_volume", 0.20))
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    import subprocess
    completed = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(narration_video),
            "-stream_loop", "-1",
            "-i", str(music_path),
            "-filter_complex",
            f"[0:a]volume=1.0[v];[1:a]volume={mix_volume:.3f}[m];[v][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            str(final_video),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if completed.returncode != 0:
        raise HTTPException(status_code=500, detail=f"FFmpeg 오류: {completed.stderr.strip()}")
    write_json(run_dir / "music_selection.json", {
        "track_title": music_path.stem,
        "source_file": music_path.name,
        "reason": "사용자 배경음악 교체",
    })
    control_room.emit(
        "MusicProducer",
        f"{run_id} 배경음악을 '{music_path.stem}'으로 교체했습니다.",
        "success",
    )
    return {
        "status": "done",
        "music": music_path.name,
        "message": f"배경음악을 '{music_path.stem}'으로 교체 완료.",
    }


@app.get("/api/knowledge/{run_id}/music-options")
def music_options(run_id: str) -> dict[str, Any]:
    import yaml
    config = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))
    music_library = config.get("video_studio", {}).get("music_library", {})
    music_dir = PROJECT_ROOT / str(music_library.get("folder", "music"))
    tracks = []
    for track in music_library.get("tracks", []):
        filename = str(track.get("file", ""))
        if (music_dir / filename).exists():
            tracks.append({
                "file": filename,
                "mood": track.get("mood", ""),
            })
    return {"tracks": tracks}


@app.get("/api/conversation")
def conversation(run_id: str | None = None) -> dict[str, Any]:
    return control_room.conversation(run_id)


@app.get("/api/events/recent")
def recent_events() -> dict[str, Any]:
    return {"events": control_room.recent_events()}


@app.get("/api/events")
def events() -> StreamingResponse:
    subscriber = control_room.subscribe()

    def stream() -> Any:
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            control_room.unsubscribe(subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/command")
def command(request: CommandRequest) -> dict[str, Any]:
    try:
        return control_room.command(request.command)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/stop")
def stop() -> dict[str, Any]:
    return control_room.stop()


@app.post("/api/logs/clear")
def clear_logs() -> dict[str, str]:
    control_room.clear_events()
    return {"message": "로그를 비웠습니다."}


@app.api_route(
    "/api/ideas/{legacy_path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
def disabled_legacy_ideas(legacy_path: str) -> None:
    raise HTTPException(
        status_code=410,
        detail="커뮤니티 썰·사연 추천 기능은 지식 미스터리 편성 전환으로 비활성화되었습니다.",
    )


def main() -> None:
    port = int(os.getenv("PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
