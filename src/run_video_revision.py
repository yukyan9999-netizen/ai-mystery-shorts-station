from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.knowledge_models import KnowledgeProductionPackage
from src.knowledge_video_studio import KnowledgeVideoStudio
from src.video_revision_director import VideoRevisionDirector


OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "knowledge"
HISTORY_PATH = PROJECT_ROOT / "ideas" / "knowledge_items.json"


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def update_history(run_id: str, **updates: object) -> None:
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    for item in history:
        if item.get("run_id") == run_id:
            item.update(updates)
            break
    write_json(HISTORY_PATH, history)


def remove_scene_assets(run_dir: Path, scene_numbers: set[int]) -> None:
    for number in scene_numbers:
        patterns = [
            run_dir / "media" / "downloaded" / f"scene_{number:02d}.*",
            run_dir / "media" / "generated" / f"scene_{number:02d}.*",
            run_dir / "media" / "motion_graphics" / f"scene_{number:02d}.*",
            run_dir / "frames" / f"scene_{number:02d}.*",
            run_dir / "frames" / "caption_overlays" / f"scene_{number:02d}.*",
        ]
        for pattern in patterns:
            for path in pattern.parent.glob(pattern.name):
                path.unlink()
    for directory in ("clips",):
        target = run_dir / directory
        if target.exists():
            shutil.rmtree(target)
    stock = run_dir / "media" / "stock"
    if stock.exists():
        shutil.rmtree(stock)
    for filename in (
        "final_short.mp4",
        "narration_short.mp4",
        "thumbnail.png",
        "render_manifest.json",
        "timeline.json",
        "sources.md",
    ):
        path = run_dir / filename
        if path.exists():
            path.unlink()


def restore_video(run_dir: Path, archived_relative: str) -> None:
    if not archived_relative:
        return
    archived = PROJECT_ROOT / archived_relative
    if archived.exists() and not (run_dir / "final_short.mp4").exists():
        shutil.copy2(archived, run_dir / "final_short.mp4")


def revise(run_id: str, feedback_path: Path) -> Path:
    run_dir = OUTPUT_ROOT / run_id
    package_path = run_dir / "final_knowledge_short.json"
    payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    feedback = str(payload.get("feedback", "")).strip()
    archived_video = str(payload.get("archived_video", "")).strip()
    raw_pkg = json.loads(package_path.read_text(encoding="utf-8"))
    if "visual_package" in raw_pkg and len(raw_pkg["visual_package"].get("scenes", [])) > 36:
        raw_pkg["visual_package"]["scenes"] = raw_pkg["visual_package"]["scenes"][:36]
    if "mixed_media_plan" in raw_pkg and len(raw_pkg["mixed_media_plan"].get("scene_assets", [])) > 36:
        raw_pkg["mixed_media_plan"]["scene_assets"] = raw_pkg["mixed_media_plan"]["scene_assets"][:36]
    package = KnowledgeProductionPackage.model_validate(raw_pkg)
    previous_timeline = {}
    timeline_path = run_dir / "timeline.json"
    if timeline_path.exists():
        timeline_payload = json.loads(timeline_path.read_text(encoding="utf-8"))
        previous_timeline = {
            int(item.get("scene_number", 0)): item
            for item in timeline_payload.get("scenes", [])
        }
    print(
        "@@AGENT_STATE@@"
        + json.dumps({"role": "VideoRevisionDirector", "state": "working"}, ensure_ascii=False),
        flush=True,
    )
    plan = VideoRevisionDirector(PROJECT_ROOT).plan(package, feedback)
    revision_number = len(list(run_dir.glob("video_feedback_*.json")))
    write_json(
        run_dir / f"video_revision_plan_{revision_number:02d}.json",
        plan.model_dump(mode="json"),
    )
    scenes = {scene.scene_number: scene for scene in package.visual_package.scenes}
    assets = {
        asset.scene_number: asset
        for asset in package.mixed_media_plan.scene_assets
    }
    changed: set[int] = set()
    for change in plan.scene_changes:
        scene = scenes.get(change.scene_number)
        asset = assets.get(change.scene_number)
        if scene is None or asset is None:
            continue
        changed.add(change.scene_number)
        previous_source_url = str(
            previous_timeline.get(change.scene_number, {}).get("source_url", "")
        ).strip()
        if previous_source_url and previous_source_url not in scene.excluded_source_urls:
            scene.excluded_source_urls.append(previous_source_url)
        scene.visual_description = (
            f"{scene.visual_description} Replacement direction: {change.instruction}"
        )
        scene.image_prompt = (
            f"{scene.image_prompt} Create a replacement visual: {change.instruction}. "
            "Use a distinctly different composition and source concept. "
            "No text, labels, logos, badges, or watermarks."
        )
        if change.preferred_media in {"external_video", "official_media"}:
            asset.asset_mode = "official_media"
        elif change.preferred_media == "ai_image":
            asset.asset_mode = "ai_reconstruction"
        elif change.preferred_media == "motion_graphics":
            asset.asset_mode = "motion_graphics"
        asset.usage_instruction = (
            f"완성 영상 피드백에 따른 교체: {change.instruction}"
        )
        asset.fallback_ai_prompt = scene.image_prompt
        asset.on_screen_source_label = ""
    if not changed:
        raise RuntimeError("수정할 장면 번호를 찾지 못했습니다.")
    package.human_approval = package.human_approval or {"approved": True}
    package.human_approval["approved"] = True
    package.upload_ready = False
    package_path.write_text(package.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "12_visual_package.json").write_text(
        package.visual_package.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_dir / "13_mixed_media_plan.json").write_text(
        package.mixed_media_plan.model_dump_json(indent=2),
        encoding="utf-8",
    )
    payload.update(
        {
            "status": "rendering",
            "planned_at": datetime.now().isoformat(timespec="seconds"),
            "scene_numbers": sorted(changed),
            "plan_file": f"video_revision_plan_{revision_number:02d}.json",
        }
    )
    write_json(feedback_path, payload)
    remove_scene_assets(run_dir, changed)
    try:
        output = KnowledgeVideoStudio(PROJECT_ROOT, live=True).render(run_id)
    except Exception:
        restore_video(run_dir, archived_video)
        update_history(
            run_id,
            production_status="video_ready" if (run_dir / "final_short.mp4").exists() else "video_failed",
            video_revision_error="영상 피드백 재제작에 실패해 이전 영상을 복원했습니다.",
        )
        raise
    payload.update(
        {
            "status": "completed",
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "output_video": str(output.relative_to(PROJECT_ROOT)),
        }
    )
    write_json(feedback_path, payload)
    update_history(
        run_id,
        production_status="video_ready",
        latest_video_feedback=feedback,
        video_revision_count=revision_number,
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--feedback-file", required=True)
    args = parser.parse_args()
    try:
        revise(args.run_id, Path(args.feedback_file).resolve())
        return 0
    except Exception as exc:
        print(f"영상 피드백 수정 오류: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
