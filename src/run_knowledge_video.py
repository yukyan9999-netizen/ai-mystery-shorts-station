from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.knowledge_video_studio import KnowledgeVideoStudio


def main() -> int:
    parser = argparse.ArgumentParser(description="승인된 지식 쇼츠 MP4 제작")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--rebuild-style",
        action="store_true",
        help="기존 이미지 자료는 유지하고 프레임·음성·영상 스타일을 다시 제작",
    )
    args = parser.parse_args()
    try:
        path = KnowledgeVideoStudio(PROJECT_ROOT, live=True).render(
            args.run_id,
            force_rebuild=args.rebuild_style,
        )
        try:
            print(f"지식 쇼츠 MP4 완성: {path}", flush=True)
        except OSError:
            pass
        return 0
    except Exception as exc:
        try:
            print(f"지식 쇼츠 영상 제작 오류: {exc}", file=sys.stderr, flush=True)
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
