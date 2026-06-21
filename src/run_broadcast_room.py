from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.broadcast_room import BroadcastRoom, approve_episode
from src.episode_queue import EpisodeQueue, episode_lock
from src.video_studio import VideoStudio


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="멀티 에이전트 AI 여행 웹툰 쇼츠 방송국"
    )
    parser.add_argument("--topic", help="직접 지정할 오늘의 여행썰 주제")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API 호출 없이 설정, 프롬프트, 폴더 구조만 검증",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="담당 AI 사이의 실제 전달 자료와 결과를 콘솔에 실시간 표시",
    )
    parser.add_argument("--approve", metavar="RUN_ID", help="사람 검토 후 최종본 승인")
    parser.add_argument("--approver", help="승인자 이름 또는 식별명")
    parser.add_argument(
        "--render",
        metavar="RUN_ID",
        help="심의 통과 final_episode.json으로 이미지·음성·MP4 제작",
    )
    parser.add_argument(
        "--force-render",
        action="store_true",
        help="기존 이미지와 음성도 다시 생성",
    )
    parser.add_argument(
        "--render-after",
        action="store_true",
        help="방송국 제작과 심의 통과 후 곧바로 실제 MP4까지 생성",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="중단된 실행의 완료 체크포인트를 재사용해 마지막 미완료 단계부터 계속",
    )
    parser.add_argument(
        "--work-pending",
        action="store_true",
        help="가장 오래된 미완성 에피소드부터 병렬로 계속 제작",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="동시에 작업할 미완성 에피소드 수(기본 1, 최대 3)",
    )
    parser.add_argument(
        "--queue-status",
        action="store_true",
        help="에피소드별 완료·미완성·승인 대기 상태 표시",
    )
    parser.add_argument(
        "--episode-manager",
        action="store_true",
        help="완성·진행·대기·오류 에피소드 종합 현황판 표시",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = PROJECT_ROOT
    try:
        if args.episode_manager:
            EpisodeQueue(root).print_manager_report()
            return 0

        if args.queue_status:
            statuses = EpisodeQueue(root).scan()
            for item in statuses:
                print(
                    f"{item.run_id} | {item.state} | next={item.next_action} | "
                    f"updated={item.updated_at}"
                )
            return 0

        if args.work_pending:
            workers = min(3, max(1, args.workers))
            results = EpisodeQueue(root).work_pending(workers=workers)
            return 0 if all(code == 0 for _, code in results) else 1

        if args.render:
            with episode_lock(root, args.render):
                path = VideoStudio(root, live=args.live).render(
                    args.render, force=args.force_render
                )
            print(f"웹툰 쇼츠 제작 완료(사람 승인 대기): {path}")
            return 0

        if args.approve:
            if not args.approver:
                raise ValueError("--approve 사용 시 --approver가 필요합니다.")
            path = approve_episode(root, args.approve, args.approver)
            print(f"사람 승인 완료: {path}")
            return 0

        room = BroadcastRoom(root, live=args.live, resume_run_id=args.resume)
        if args.dry_run:
            path = room.dry_run(args.topic)
            print(f"드라이런 완료: {path}")
            return 0

        with episode_lock(root, room.run_id):
            path = room.produce(args.topic)
            print(f"제작 완료(사람 승인 대기): {path}")
            if args.render_after:
                video_path = VideoStudio(root, live=args.live).render(room.run_id)
                print(f"웹툰 쇼츠 제작 완료(사람 승인 대기): {video_path}")
        print(
            f"승인 명령: python src/run_broadcast_room.py "
            f"--approve {room.run_id} --approver \"검토자 이름\""
        )
        return 0
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
