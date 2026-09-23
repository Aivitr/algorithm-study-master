import argparse
import json
import os
import sys
from pathlib import Path

BRIDGE_READY = True


def _normalize_vector(vector):
    if vector is None:
        return None
    try:
        import numpy as np

        arr = np.asarray(vector, dtype="float32").reshape(-1)
        if arr.size == 0:
            return None
        norm = float(np.linalg.norm(arr))
        if norm <= 1e-6:
            return None
        return (arr / norm).astype("float32").tolist()
    except Exception:
        try:
            raw = [float(x) for x in vector]
            norm = sum(x * x for x in raw) ** 0.5
            if norm <= 1e-6:
                return None
            return [x / norm for x in raw]
        except Exception:
            return None


def _load_metadata(model_dir: Path) -> dict:
    metadata_path = model_dir / "model_meta.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _prepare_import_path(model_dir: Path) -> None:
    candidates = [
        model_dir / "repo",
        model_dir / "repo" / "wespeaker",
        model_dir / "wespeaker",
    ]
    for candidate in candidates:
        if candidate.exists():
            sys.path.insert(0, str(candidate))


def _load_model(wespeaker_module, model_dir: Path):
    metadata = _load_metadata(model_dir)
    model_name = (
        os.getenv("RESEARCH_WESPEAKER_MODEL_NAME")
        or metadata.get("model_name")
        or "chinese"
    )
    os.environ.setdefault("WESPEAKER_HOME", str(model_dir / "pretrained"))

    if hasattr(wespeaker_module, "load_model"):
        return wespeaker_module.load_model(model_name)
    if hasattr(wespeaker_module, "load_model_local"):
        return wespeaker_module.load_model_local(str(model_dir))
    if hasattr(wespeaker_module, "Speaker"):
        return wespeaker_module.Speaker(str(model_dir))
    return wespeaker_module


def _extract_embedding(wespeaker_module, model, audio_path: str):
    if hasattr(model, "extract_embedding"):
        return model.extract_embedding(audio_path)
    if hasattr(model, "embedding"):
        return model.embedding(audio_path)
    if hasattr(wespeaker_module, "extract_embedding"):
        return wespeaker_module.extract_embedding(audio_path, model=model)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    payload = {"ok": False, "error": "wespeaker bridge failed"}

    try:
        _prepare_import_path(model_dir)
        import wespeaker

        model = _load_model(wespeaker, model_dir)
        embedding = _extract_embedding(wespeaker, model, args.audio)
        normalized = _normalize_vector(embedding)

        if normalized:
            payload = {"ok": True, "embedding": normalized}
        else:
            payload = {"ok": False, "error": "No embedding returned from WeSpeaker"}
    except Exception as exc:
        payload = {
            "ok": False,
            "error": (
                "WeSpeaker bridge could not finish inference. "
                "Please confirm the official repo is available under model_dir/repo "
                "and the model has been warmed by download_enhanced_open_models.py. "
                f"Original error: {exc}"
            ),
        }

    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
