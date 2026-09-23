import argparse
import json
import math
import pickle
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRIDGE_READY = True
FPS = 25.0


def _repo_root(model_dir: Path) -> Path:
    candidates = [model_dir / "repo", model_dir / "TalkNet-ASD", model_dir]
    for candidate in candidates:
        if (candidate / "demoTalkNet.py").exists():
            return candidate
    raise FileNotFoundError("official TalkNet-ASD repo not found under model_dir/repo")


def _pretrain_model_path(model_dir: Path, repo_root: Path) -> Path:
    candidates = [
        model_dir / "pretrain_TalkSet.model",
        repo_root / "pretrain_TalkSet.model",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("pretrain_TalkSet.model not found")


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _summarize_scores(scores, frames):
    if not scores:
        return {
            "active_probability": 0.0,
            "active_segments": [],
            "positive_frame_ratio": 0.0,
        }

    active_mask = [float(score) >= 0.0 for score in scores]
    positive_ratio = sum(1 for flag in active_mask if flag) / len(active_mask)
    mean_score = sum(float(score) for score in scores) / len(scores)
    probability = max(positive_ratio, _sigmoid(mean_score))

    segments = []
    start_index = None
    for index, is_active in enumerate(active_mask):
        if is_active and start_index is None:
            start_index = index
        elif not is_active and start_index is not None:
            start_frame = int(frames[start_index])
            end_frame = int(frames[index - 1]) + 1
            segments.append({"start": round(start_frame / FPS, 3), "end": round(end_frame / FPS, 3)})
            start_index = None

    if start_index is not None:
        start_frame = int(frames[start_index])
        end_frame = int(frames[len(active_mask) - 1]) + 1
        segments.append({"start": round(start_frame / FPS, 3), "end": round(end_frame / FPS, 3)})

    return {
        "active_probability": round(float(probability), 4),
        "active_segments": segments,
        "positive_frame_ratio": round(float(positive_ratio), 4),
    }


def _load_demo_outputs(save_dir: Path):
    pywork_dir = save_dir / "pywork"
    score_path = pywork_dir / "scores.pckl"
    track_path = pywork_dir / "tracks.pckl"
    if not score_path.exists() or not track_path.exists():
        raise FileNotFoundError("TalkNet-ASD output files not found after demo run")

    with score_path.open("rb") as handle:
        score_payload = pickle.load(handle)
    with track_path.open("rb") as handle:
        track_payload = pickle.load(handle)

    return score_payload, track_payload, score_path, track_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    payload = {"ok": False, "error": "TalkNet-ASD bridge failed"}

    try:
        repo_root = _repo_root(model_dir)
        pretrain_path = _pretrain_model_path(model_dir, repo_root)

        with tempfile.TemporaryDirectory(prefix="talknet_bridge_") as temp_root_raw:
            temp_root = Path(temp_root_raw)
            video_path = Path(args.video)
            staged_video = temp_root / f"{video_path.stem}{video_path.suffix}"
            shutil.copy2(video_path, staged_video)

            command = [
                sys.executable,
                str(repo_root / "demoTalkNet.py"),
                "--videoFolder",
                str(temp_root),
                "--videoName",
                video_path.stem,
                "--pretrainModel",
                str(pretrain_path),
                "--nDataLoaderThread",
                "1",
            ]
            completed = subprocess.run(command, cwd=str(repo_root), capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"demoTalkNet.py exited with {completed.returncode}: {(completed.stderr or completed.stdout or '').strip()}"
                )

            save_dir = temp_root / video_path.stem
            score_payload, track_payload, score_path, track_path = _load_demo_outputs(save_dir)

            track_summaries = []
            merged_segments = []
            best_probability = 0.0
            best_ratio = 0.0

            for index, (track_item, score_item) in enumerate(zip(track_payload, score_payload), start=1):
                frames = list(track_item.get("track", {}).get("frame", []))
                scores = [float(value) for value in score_item]
                summary = _summarize_scores(scores, frames if frames else range(len(scores)))
                summary["track_index"] = index
                summary["frame_count"] = len(scores)
                track_summaries.append(summary)
                best_probability = max(best_probability, float(summary["active_probability"]))
                best_ratio = max(best_ratio, float(summary["positive_frame_ratio"]))
                merged_segments.extend(summary["active_segments"])

            payload = {
                "ok": True,
                "active_probability": round(best_probability, 4),
                "positive_frame_ratio": round(best_ratio, 4),
                "active_segments": merged_segments,
                "track_summaries": track_summaries,
                "score_file": str(score_path),
                "track_file": str(track_path),
            }
    except Exception as exc:
        payload = {
            "ok": False,
            "error": (
                "TalkNet-ASD bridge could not finish inference. "
                "Please confirm the official repo is available under model_dir/repo and "
                "pretrain_TalkSet.model has been downloaded. "
                f"Original error: {exc}"
            ),
        }

    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
