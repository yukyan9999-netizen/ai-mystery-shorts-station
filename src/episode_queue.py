from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from queue import Empty, Queue
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

import yaml


@dataclass
class EpisodeStatus:
    run_id: str
    state: str
    next_action: str
    created_at: str
    updated_at: str
    locked: bool


@dataclass
class EpisodeManagerReport:
    generated_at: str
    total: int
    completed: int
    in_progress: int
    waiting: int
    blocked: int
    awaiting_human_approval: int
    approved: int
    episodes: list[dict[str, object]]


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_path(root: Path, run_id: str) -> Path:
    return root / "outputs" / "drafts" / run_id / ".episode.lock"


def lock_is_active(root: Path, run_id: str) -> bool:
    path = _lock_path(root, run_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if _pid_running(int(data.get("pid", 0))):
            return True
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    path.unlink(missing_ok=True)
    return False


@contextmanager
def episode_lock(root: Path, run_id: str) -> Iterator[None]:
    path = _lock_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if lock_is_active(root, run_id):
        raise RuntimeError(f"에피소드 {run_id}는 이미 다른 작업자가 처리 중입니다.")
    payload = {
        "pid": os.getpid(),
        "run_id": run_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"에피소드 {run_id} 잠금 획득에 실패했습니다.") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
            json.dump(payload, lock_file, ensure_ascii=False, indent=2)
        yield
    finally:
        path.unlink(missing_ok=True)


class EpisodeQueue:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.drafts = self.root / "outputs" / "drafts"
        self.final = self.root / "outputs" / "final"
        self.script = self.root / "src" / "run_broadcast_room.py"
        self._print_lock = threading.Lock()
        config = yaml.safe_load(
            (self.root / "config.yaml").read_text(encoding="utf-8")
        )
        self.report_seconds = float(
            config.get("episode_manager_report_seconds", 30)
        )

    def _status_for(self, draft_dir: Path) -> EpisodeStatus | None:
        run_id = draft_dir.name
        has_episode_work = (draft_dir / "01_programming_direction.json").exists()
        if not has_episode_work:
            return None

        final_dir = self.final / run_id
        final_json = final_dir / "final_episode.json"
        final_video = final_dir / "final_short.mp4"
        approved = final_dir / "HUMAN_APPROVED.json"
        error_file = draft_dir / "episode_error.json"
        render_manifest = final_dir / "render_manifest.json"
        locked = lock_is_active(self.root, run_id)

        render_failed = False
        render_error = ""
        if render_manifest.exists():
            try:
                render_data = json.loads(render_manifest.read_text(encoding="utf-8"))
                render_failed = render_data.get("status") == "failed"
                render_error = str(render_data.get("error", ""))
            except (OSError, json.JSONDecodeError):
                render_failed = True

        episode_error = ""
        if error_file.exists():
            try:
                episode_error = str(
                    json.loads(error_file.read_text(encoding="utf-8")).get(
                        "message", ""
                    )
                )
            except (OSError, json.JSONDecodeError):
                episode_error = "unreadable error record"
        retryable_error = any(
            marker in f"{episode_error} {render_error}"
            for marker in (
                "[Errno 22] Invalid argument",
                "UnicodeEncodeError",
                "cp949",
            )
        )

        if locked:
            state, action = "running", "wait"
        elif approved.exists():
            state, action = "approved", "none"
        elif final_video.exists():
            state, action = "awaiting_human_approval", "human_review"
        elif (error_file.exists() or render_failed) and not retryable_error:
            state, action = "blocked", "inspect_error"
        elif final_json.exists():
            try:
                final_data = json.loads(final_json.read_text(encoding="utf-8"))
                conditional = (
                    final_data.get("completion_status")
                    == "conditional_after_revision_limit"
                )
            except (OSError, json.JSONDecodeError):
                conditional = False
            state = "conditional_render_pending" if conditional else "render_pending"
            action = "render"
        else:
            state, action = "draft_pending", "resume"

        created = datetime.fromtimestamp(draft_dir.stat().st_ctime).isoformat(
            timespec="seconds"
        )
        updated_candidates = [draft_dir.stat().st_mtime]
        if final_dir.exists():
            updated_candidates.append(final_dir.stat().st_mtime)
        updated = datetime.fromtimestamp(max(updated_candidates)).isoformat(
            timespec="seconds"
        )
        status = EpisodeStatus(
            run_id=run_id,
            state=state,
            next_action=action,
            created_at=created,
            updated_at=updated,
            locked=locked,
        )
        (draft_dir / "episode_status.json").write_text(
            json.dumps(asdict(status), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return status

    def scan(self) -> list[EpisodeStatus]:
        if not self.drafts.exists():
            return []
        statuses = [
            status
            for directory in self.drafts.iterdir()
            if directory.is_dir()
            for status in [self._status_for(directory)]
            if status is not None
        ]
        return sorted(statuses, key=lambda item: (item.created_at, item.run_id))

    def manager_report(self, save: bool = True) -> EpisodeManagerReport:
        statuses = self.scan()
        completed_states = {"awaiting_human_approval", "approved"}
        report = EpisodeManagerReport(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            total=len(statuses),
            completed=sum(item.state in completed_states for item in statuses),
            in_progress=sum(item.state == "running" for item in statuses),
            waiting=sum(
                item.state
                in {"draft_pending", "render_pending", "conditional_render_pending"}
                for item in statuses
            ),
            blocked=sum(item.state == "blocked" for item in statuses),
            awaiting_human_approval=sum(
                item.state == "awaiting_human_approval" for item in statuses
            ),
            approved=sum(item.state == "approved" for item in statuses),
            episodes=[asdict(item) for item in statuses],
        )
        if save:
            output = self.root / "outputs" / "episode_manager_status.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(asdict(report), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return report

    def print_manager_report(self) -> EpisodeManagerReport:
        report = self.manager_report()
        self._print("")
        self._print("[EpisodeManager 현황]")
        self._print(f"전체 에피소드          : {report.total}개")
        self._print(f"완성                  : {report.completed}개")
        self._print(f"현재 진행 중           : {report.in_progress}개")
        self._print(f"작업 대기              : {report.waiting}개")
        self._print(f"오류로 작업 불가       : {report.blocked}개")
        self._print(
            f"완성본 중 승인 대기/승인: "
            f"{report.awaiting_human_approval}개 / {report.approved}개"
        )
        return report

    def _compact_report(self) -> None:
        report = self.manager_report()
        self._print(
            "[EpisodeManager] "
            f"완성 {report.completed} | 진행 {report.in_progress} | "
            f"대기 {report.waiting} | 작업불가 {report.blocked}"
        )

    def pending(self, limit: int | None = None) -> list[EpisodeStatus]:
        candidates = [
            item
            for item in self.scan()
            if item.state
            in {"draft_pending", "render_pending", "conditional_render_pending"}
        ]
        if limit is None:
            return candidates
        return candidates[: max(1, limit)]

    def _print(self, message: str) -> None:
        with self._print_lock:
            try:
                print(message, flush=True)
            except UnicodeEncodeError:
                encoded = (message + "\n").encode("utf-8", errors="replace")
                sys.stdout.buffer.write(encoded)
                sys.stdout.buffer.flush()

    def _run_one(self, episode: EpisodeStatus) -> tuple[str, int]:
        if episode.next_action == "render":
            command = [
                sys.executable,
                str(self.script),
                "--live",
                "--render",
                episode.run_id,
            ]
        else:
            command = [
                sys.executable,
                str(self.script),
                "--live",
                "--resume",
                episode.run_id,
                "--render-after",
            ]
        self._print(f"[큐] {episode.run_id} 시작 · {episode.next_action}")
        child_env = os.environ.copy()
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            command,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self._print(f"[{episode.run_id}] {line.rstrip()}")
        return_code = process.wait()
        outcome = "완료" if return_code == 0 else f"실패({return_code})"
        error_file = self.drafts / episode.run_id / "episode_error.json"
        if return_code == 0:
            error_file.unlink(missing_ok=True)
        else:
            error_file.write_text(
                json.dumps(
                    {
                        "run_id": episode.run_id,
                        "failed_at": datetime.now().isoformat(timespec="seconds"),
                        "return_code": return_code,
                        "message": "병렬 작업 프로세스가 실패했습니다. 로그와 체크포인트를 확인하세요.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        self._print(f"[큐] {episode.run_id} {outcome}")
        self._status_for(self.drafts / episode.run_id)
        return episode.run_id, return_code

    def work_pending(self, workers: int = 1) -> list[tuple[str, int]]:
        self.print_manager_report()
        episodes = self.pending()
        if not episodes:
            self._print("[큐] 처리할 미완성 에피소드가 없습니다.")
            return []

        results: list[tuple[str, int]] = []
        result_lock = threading.Lock()
        worker_errors: list[tuple[str, str]] = []
        monitor_stop = threading.Event()
        jobs: Queue[EpisodeStatus] = Queue()
        for episode in episodes:
            jobs.put(episode)

        def worker() -> None:
            while True:
                try:
                    episode = jobs.get_nowait()
                except Empty:
                    return
                try:
                    try:
                        result = self._run_one(episode)
                        with result_lock:
                            results.append(result)
                    except Exception as exc:
                        error_file = (
                            self.drafts / episode.run_id / "episode_error.json"
                        )
                        error_file.write_text(
                            json.dumps(
                                {
                                    "run_id": episode.run_id,
                                    "failed_at": datetime.now().isoformat(
                                        timespec="seconds"
                                    ),
                                    "message": str(exc),
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        with result_lock:
                            results.append((episode.run_id, 1))
                            worker_errors.append((episode.run_id, str(exc)))
                        self._print(
                            f"[큐] {episode.run_id} 작업 스레드 오류: {exc}"
                        )
                finally:
                    jobs.task_done()

        threads = [
            threading.Thread(target=worker, daemon=False)
            for _ in range(min(workers, len(episodes)))
        ]
        def monitor() -> None:
            while not monitor_stop.wait(self.report_seconds):
                self._compact_report()

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        monitor_stop.set()
        monitor_thread.join(timeout=1)
        self.print_manager_report()
        if worker_errors:
            self._print(
                f"[큐] 작업 스레드 오류 {len(worker_errors)}건을 실패로 기록했습니다."
            )
        return sorted(results)
