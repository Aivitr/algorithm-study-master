import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional


REPO_ROOT = Path(__file__).resolve().parent
TALKNET_PRETRAIN_URL = "https://drive.google.com/uc?id=1AbN9fCf9IexMxEKXLQY2KYBlb-IhSEea"


def run(command, cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> None:
    completed = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, check=False)
    if completed.returncode != 0:
        rendered = " ".join(str(item) for item in command)
        raise RuntimeError(f"command failed ({completed.returncode}): {rendered}")


def ensure_layout(repo_root: Path, model_root: Path, gallery_root: Path, force: bool = False) -> None:
    slots = ["pyannote", "wespeaker", "talknet_asd", "insightface", "clip_vit_b16", "bge_m3"]
    templates = {
        "wespeaker": repo_root / "enhanced_bridge_templates" / "wespeaker_bridge.py",
        "talknet_asd": repo_root / "enhanced_bridge_templates" / "talknet_asd_bridge.py",
    }

    model_root.mkdir(parents=True, exist_ok=True)
    gallery_root.mkdir(parents=True, exist_ok=True)

    for slot in slots:
        slot_dir = model_root / slot
        slot_dir.mkdir(parents=True, exist_ok=True)
        placeholder = slot_dir / "PLACE_MODEL_FILES_HERE.txt"
        if force or not placeholder.exists():
            placeholder.write_text(
                "\n".join(
                    [
                        f"Model slot: {slot}",
                        "",
                        "This directory is prepared for the enhanced deployment profile.",
                        "Run setup_enhanced_runtime.ps1 or download_enhanced_open_models.py to populate it.",
                    ]
                ),
                encoding="utf-8",
            )

    for slot, template_path in templates.items():
        target = model_root / slot / "bridge.py"
        if force or not target.exists():
            shutil.copy2(template_path, target)


def clone_or_update_git_repo(repo_url: str, target_dir: Path) -> None:
    git_executable = shutil.which("git")
    if not git_executable:
        raise RuntimeError("git is required to clone the official open-source repositories for enhanced mode")

    if (target_dir / ".git").exists():
        run([git_executable, "-C", str(target_dir), "pull", "--ff-only"])
        return

    if target_dir.exists() and any(target_dir.iterdir()):
        return

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    run([git_executable, "clone", "--depth", "1", repo_url, str(target_dir)])


def download_pyannote_snapshot(target_dir: Path, model_id: str, hf_token: str) -> None:
    if not hf_token:
        raise RuntimeError("pyannote model download requires --hf-token or RESEARCH_HF_TOKEN")

    from huggingface_hub import snapshot_download

    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=model_id,
        token=hf_token,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        resume_download=True,
    )


def install_wespeaker_repo(python_executable: str, repo_dir: Path) -> None:
    run([python_executable, "-m", "pip", "install", "-e", str(repo_dir)])


def warm_wespeaker_model(python_executable: str, model_dir: Path, model_name: str) -> None:
    env = os.environ.copy()
    env["WESPEAKER_HOME"] = str(model_dir / "pretrained")
    code = (
        "import os; "
        f"os.environ['WESPEAKER_HOME'] = r'{env['WESPEAKER_HOME']}'; "
        "import wespeaker; "
        f"model = wespeaker.load_model('{model_name}'); "
        "print(type(model).__name__)"
    )
    run([python_executable, "-c", code], env=env)
    metadata_path = model_dir / "model_meta.json"
    metadata_path.write_text(
        json.dumps(
            {
                "model_name": model_name,
                "pretrained_home": env["WESPEAKER_HOME"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def download_talknet_pretrain(python_executable: str, target_path: Path) -> None:
    if target_path.exists():
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import gdown; "
        f"gdown.download('{TALKNET_PRETRAIN_URL}', r'{target_path}', quiet=False)"
    )
    run([python_executable, "-c", code])


def warm_insightface_pack(python_executable: str, model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    code = (
        "from insightface.app import FaceAnalysis; "
        f"app = FaceAnalysis(name='buffalo_l', root=r'{model_dir}'); "
        "app.prepare(ctx_id=-1, det_size=(640, 640)); "
        "print('buffalo_l ready')"
    )
    run([python_executable, "-c", code])

    expected_dir = model_dir / "models" / "buffalo_l"
    default_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
    if not expected_dir.exists() and default_dir.exists():
        expected_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(default_dir, expected_dir, dirs_exist_ok=True)


def download_hf_model(target_dir: Path, model_id: str) -> None:
    from huggingface_hub import snapshot_download

    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=model_id,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        resume_download=True,
    )


def write_summary(model_root: Path, summary: Dict) -> None:
    summary_path = model_root / "enhanced_setup_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and prepare open-source assets for enhanced deployment.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--model-root", default="")
    parser.add_argument("--gallery-root", default="")
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--hf-token", default=os.getenv("RESEARCH_HF_TOKEN", ""))
    parser.add_argument("--pyannote-model-id", default=os.getenv("RESEARCH_PYANNOTE_MODEL_ID", "pyannote/speaker-diarization-3.1"))
    parser.add_argument("--wespeaker-model-name", default=os.getenv("RESEARCH_WESPEAKER_MODEL_NAME", "chinese"))
    parser.add_argument("--clip-model-id", default=os.getenv("RESEARCH_CLIP_MODEL_ID", "openai/clip-vit-base-patch16"))
    parser.add_argument("--bge-model-id", default=os.getenv("RESEARCH_BGE_MODEL_ID", "BAAI/bge-m3"))
    parser.add_argument("--wespeaker-repo-url", default=os.getenv("RESEARCH_WESPEAKER_REPO_URL", "https://github.com/wenet-e2e/wespeaker.git"))
    parser.add_argument("--talknet-repo-url", default=os.getenv("RESEARCH_TALKNET_REPO_URL", "https://github.com/TaoRuijie/TalkNet-ASD.git"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-pyannote", action="store_true")
    parser.add_argument("--skip-wespeaker", action="store_true")
    parser.add_argument("--skip-talknet", action="store_true")
    parser.add_argument("--skip-insightface", action="store_true")
    parser.add_argument("--skip-clip", action="store_true")
    parser.add_argument("--skip-bge", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    model_root = Path(args.model_root).resolve() if args.model_root else repo_root / "storage" / "research_models"
    gallery_root = Path(args.gallery_root).resolve() if args.gallery_root else repo_root / "storage" / "research_gallery"
    python_executable = args.python_exe

    ensure_layout(repo_root, model_root, gallery_root, force=args.force)

    summary = {
        "repo_root": str(repo_root),
        "model_root": str(model_root),
        "gallery_root": str(gallery_root),
        "python_executable": python_executable,
        "steps": [],
    }

    if not args.skip_pyannote:
        target_dir = model_root / "pyannote"
        download_pyannote_snapshot(target_dir, args.pyannote_model_id, args.hf_token)
        summary["steps"].append({"slot": "pyannote", "status": "downloaded", "target": str(target_dir)})

    if not args.skip_wespeaker:
        target_dir = model_root / "wespeaker"
        repo_dir = target_dir / "repo"
        clone_or_update_git_repo(args.wespeaker_repo_url, repo_dir)
        install_wespeaker_repo(python_executable, repo_dir)
        warm_wespeaker_model(python_executable, target_dir, args.wespeaker_model_name)
        summary["steps"].append({"slot": "wespeaker", "status": "ready", "repo": str(repo_dir)})

    if not args.skip_talknet:
        target_dir = model_root / "talknet_asd"
        repo_dir = target_dir / "repo"
        clone_or_update_git_repo(args.talknet_repo_url, repo_dir)
        pretrain_path = target_dir / "pretrain_TalkSet.model"
        download_talknet_pretrain(python_executable, pretrain_path)
        summary["steps"].append(
            {"slot": "talknet_asd", "status": "ready", "repo": str(repo_dir), "pretrain_model": str(pretrain_path)}
        )

    if not args.skip_insightface:
        target_dir = model_root / "insightface"
        warm_insightface_pack(python_executable, target_dir)
        summary["steps"].append({"slot": "insightface", "status": "ready", "target": str(target_dir)})

    if not args.skip_clip:
        target_dir = model_root / "clip_vit_b16"
        download_hf_model(target_dir, args.clip_model_id)
        summary["steps"].append({"slot": "clip_vit_b16", "status": "downloaded", "target": str(target_dir)})

    if not args.skip_bge:
        target_dir = model_root / "bge_m3"
        download_hf_model(target_dir, args.bge_model_id)
        summary["steps"].append({"slot": "bge_m3", "status": "downloaded", "target": str(target_dir)})

    write_summary(model_root, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
