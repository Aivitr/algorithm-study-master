import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _normalize_vector(vector) -> Optional[List[float]]:
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
        arr = arr / norm
        return arr.astype("float32").tolist()
    except Exception:
        try:
            raw = [float(x) for x in vector]
            size = sum(x * x for x in raw) ** 0.5
            if size <= 1e-6:
                return None
            return [x / size for x in raw]
        except Exception:
            return None


def cosine_similarity(vec_a, vec_b) -> Optional[float]:
    left = _normalize_vector(vec_a)
    right = _normalize_vector(vec_b)
    if not left or not right or len(left) != len(right):
        return None
    return float(sum(a * b for a, b in zip(left, right)))


@dataclass(frozen=True)
class AdapterStatus:
    key: str
    name: str
    dependency_available: bool
    model_available: bool
    ready: bool
    uses_bridge: bool
    detail: str

    def to_dict(self) -> Dict:
        return asdict(self)


class BaseAdapter:
    key = "base"
    name = "Base Adapter"

    def __init__(
        self,
        model_dir: Path,
        gallery_root: Optional[Path] = None,
        hf_token: str = "",
        python_executable: str = "",
    ):
        self.model_dir = model_dir
        self.gallery_root = gallery_root
        self.hf_token = hf_token
        self.python_executable = python_executable or sys.executable
        self._status_cache: Optional[AdapterStatus] = None

    def _model_exists(self) -> bool:
        if not self.model_dir.exists():
            return False
        ignored = {"PLACE_MODEL_FILES_HERE.txt", "bridge.py", "__pycache__"}
        for item in self.model_dir.iterdir():
            if item.name in ignored:
                continue
            return True
        return False

    def _bridge_path(self) -> Path:
        return self.model_dir / "bridge.py"

    def _bridge_exists(self) -> bool:
        return self._bridge_path().exists()

    def _bridge_marked_ready(self) -> bool:
        bridge = self._bridge_path()
        if not bridge.exists():
            return False
        try:
            text = bridge.read_text(encoding="utf-8", errors="ignore")
            return "BRIDGE_READY = True" in text or "BRIDGE_READY=True" in text
        except Exception:
            return False

    def status(self) -> Dict:
        if self._status_cache is None:
            self._status_cache = self._build_status()
        return self._status_cache.to_dict()

    def _build_status(self) -> AdapterStatus:
        return AdapterStatus(
            key=self.key,
            name=self.name,
            dependency_available=False,
            model_available=self._model_exists(),
            ready=False,
            uses_bridge=False,
            detail="adapter not implemented",
        )

    def _run_bridge(self, args: List[str]) -> Dict:
        bridge = self._bridge_path()
        if not bridge.exists():
            return {"ok": False, "error": f"bridge not found: {bridge}"}

        temp_file = tempfile.NamedTemporaryFile(prefix=f"{self.key}_", suffix=".json", delete=False)
        temp_file.close()
        output_path = Path(temp_file.name)
        command = [
            self.python_executable,
            str(bridge),
            "--model-dir",
            str(self.model_dir),
            "--output",
            str(output_path),
        ] + args

        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            if completed.returncode != 0:
                return {
                    "ok": False,
                    "error": f"bridge exit code={completed.returncode}",
                    "stdout": stdout,
                    "stderr": stderr,
                }

            if not output_path.exists():
                return {"ok": False, "error": "bridge did not produce output json", "stdout": stdout, "stderr": stderr}

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            payload.setdefault("stdout", stdout)
            payload.setdefault("stderr", stderr)
            return payload
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass


class PyannoteAdapter(BaseAdapter):
    key = "pyannote"
    name = "pyannote speaker diarization"

    def __init__(
        self,
        model_dir: Path,
        gallery_root: Optional[Path] = None,
        hf_token: str = "",
        python_executable: str = "",
    ):
        super().__init__(
            model_dir=model_dir,
            gallery_root=gallery_root,
            hf_token=hf_token,
            python_executable=python_executable,
        )
        self._pipeline = None
        self._load_error = ""

    def _build_status(self) -> AdapterStatus:
        dependency_available = _has_module("pyannote.audio")
        model_available = self._model_exists()
        ready = dependency_available and model_available
        detail = "ready for local diarization" if ready else "requires pyannote.audio + local model directory"
        return AdapterStatus(
            key=self.key,
            name=self.name,
            dependency_available=dependency_available,
            model_available=model_available,
            ready=ready,
            uses_bridge=False,
            detail=detail,
        )

    def _ensure_loaded(self) -> bool:
        if self._pipeline is not None:
            return True
        try:
            from pyannote.audio import Pipeline
            import torch

            self._pipeline = Pipeline.from_pretrained(str(self.model_dir), use_auth_token=self.hf_token or None)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            if hasattr(self._pipeline, "to"):
                self._pipeline.to(device)
            return True
        except Exception as exc:
            self._load_error = str(exc)
            self._pipeline = None
            return False

    def diarize(self, audio_path: str) -> Dict:
        status = self.status()
        if not status["ready"]:
            return {"ok": False, "reason": status["detail"]}
        if not audio_path or not Path(audio_path).exists():
            return {"ok": False, "reason": "audio_path missing"}
        if not self._ensure_loaded():
            return {"ok": False, "reason": self._load_error or "pipeline load failed"}

        try:
            diarization = self._pipeline(audio_path)
            segments = []
            durations: Dict[str, float] = {}
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                start = float(turn.start)
                end = float(turn.end)
                duration = max(0.0, end - start)
                segments.append(
                    {
                        "start": start,
                        "end": end,
                        "speaker": str(speaker),
                        "duration": duration,
                    }
                )
                durations[str(speaker)] = durations.get(str(speaker), 0.0) + duration

            total_duration = sum(item["duration"] for item in segments) or 0.0
            dominant_speaker = None
            dominant_ratio = 0.0
            if durations:
                dominant_speaker = max(durations, key=durations.get)
                dominant_ratio = (durations[dominant_speaker] / total_duration) if total_duration > 0 else 0.0

            return {
                "ok": True,
                "segments": segments,
                "speaker_count": len(durations),
                "dominant_speaker": dominant_speaker,
                "dominant_ratio": round(float(dominant_ratio), 4),
                "total_duration": round(float(total_duration), 4),
            }
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}


class WeSpeakerAdapter(BaseAdapter):
    key = "wespeaker"
    name = "WeSpeaker speaker embedding"

    def __init__(
        self,
        model_dir: Path,
        gallery_root: Optional[Path] = None,
        hf_token: str = "",
        python_executable: str = "",
    ):
        super().__init__(
            model_dir=model_dir,
            gallery_root=gallery_root,
            hf_token=hf_token,
            python_executable=python_executable,
        )
        self._module = None
        self._model = None
        self._load_error = ""

    def _build_status(self) -> AdapterStatus:
        dependency_available = _has_module("wespeaker")
        repo_present = (self.model_dir / "repo").exists()
        downloaded_assets_present = (self.model_dir / "pretrained").exists() or (self.model_dir / "model_meta.json").exists()
        model_available = downloaded_assets_present or self._model_exists()
        uses_bridge = self._bridge_exists()
        bridge_ready = self._bridge_marked_ready()
        ready = (dependency_available and model_available) or (
            uses_bridge and bridge_ready and model_available and (dependency_available or repo_present)
        )
        detail = (
            "ready via direct package"
            if dependency_available and model_available
            else "ready via bridge.py"
            if uses_bridge and bridge_ready and model_available and (dependency_available or repo_present)
            else "requires a downloaded wespeaker model plus package support or a ready bridge.py with the official repo"
        )
        return AdapterStatus(
            key=self.key,
            name=self.name,
            dependency_available=dependency_available,
            model_available=model_available,
            ready=ready,
            uses_bridge=uses_bridge,
            detail=detail,
        )

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        try:
            import wespeaker

            self._module = wespeaker
            if hasattr(wespeaker, "load_model_local"):
                self._model = wespeaker.load_model_local(str(self.model_dir))
            elif hasattr(wespeaker, "load_model"):
                self._model = wespeaker.load_model(str(self.model_dir))
            elif hasattr(wespeaker, "Speaker"):
                self._model = wespeaker.Speaker(str(self.model_dir))
            else:
                self._model = wespeaker
            return True
        except Exception as exc:
            self._load_error = str(exc)
            self._model = None
            return False

    def extract_embedding(self, audio_path: str) -> Dict:
        status = self.status()
        if not status["ready"]:
            return {"ok": False, "reason": status["detail"]}
        if not audio_path or not Path(audio_path).exists():
            return {"ok": False, "reason": "audio_path missing"}

        if status["uses_bridge"] and not status["dependency_available"]:
            return self._run_bridge(["--audio", audio_path])

        if not self._ensure_loaded():
            return {"ok": False, "reason": self._load_error or "wespeaker load failed"}

        try:
            model = self._model
            vector = None

            if hasattr(model, "extract_embedding"):
                vector = model.extract_embedding(audio_path)
            elif hasattr(model, "embedding"):
                vector = model.embedding(audio_path)
            elif hasattr(self._module, "extract_embedding"):
                vector = self._module.extract_embedding(audio_path, model=model)

            normalized = _normalize_vector(vector)
            if not normalized:
                return {"ok": False, "reason": "no embedding returned"}
            return {"ok": True, "embedding": normalized}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}


class TalkNetASDAdapter(BaseAdapter):
    key = "talknet_asd"
    name = "TalkNet-ASD"

    def _build_status(self) -> AdapterStatus:
        repo_present = (self.model_dir / "repo").exists()
        weight_present = (self.model_dir / "pretrain_TalkSet.model").exists()
        model_available = repo_present and weight_present
        uses_bridge = self._bridge_exists()
        bridge_ready = self._bridge_marked_ready()
        ready = model_available and uses_bridge and bridge_ready
        detail = (
            "ready via bridge.py"
            if ready
            else "requires official TalkNet-ASD repo, pretrain_TalkSet.model and a ready bridge.py"
        )
        return AdapterStatus(
            key=self.key,
            name=self.name,
            dependency_available=uses_bridge,
            model_available=model_available,
            ready=ready,
            uses_bridge=uses_bridge,
            detail=detail,
        )

    def analyze_video(self, video_path: str) -> Dict:
        status = self.status()
        if not status["ready"]:
            return {"ok": False, "reason": status["detail"]}
        if not video_path or not Path(video_path).exists():
            return {"ok": False, "reason": "video_path missing"}
        return self._run_bridge(["--video", video_path])


class InsightFaceAdapter(BaseAdapter):
    key = "insightface"
    name = "InsightFace"

    def __init__(
        self,
        model_dir: Path,
        gallery_root: Optional[Path] = None,
        hf_token: str = "",
        python_executable: str = "",
    ):
        super().__init__(
            model_dir=model_dir,
            gallery_root=gallery_root,
            hf_token=hf_token,
            python_executable=python_executable,
        )
        self._app = None
        self._load_error = ""

    def _build_status(self) -> AdapterStatus:
        dependency_available = _has_module("insightface")
        model_available = self._model_exists()
        ready = dependency_available and model_available
        detail = "ready for direct face embedding" if ready else "requires insightface package + local model pack"
        return AdapterStatus(
            key=self.key,
            name=self.name,
            dependency_available=dependency_available,
            model_available=model_available,
            ready=ready,
            uses_bridge=False,
            detail=detail,
        )

    def _resolve_pack_name(self) -> str:
        candidates = ["buffalo_l", "buffalo_sc", "antelopev2", self.model_dir.name]
        for name in candidates:
            if (self.model_dir / "models" / name).exists():
                return name
            if (self.model_dir / name).exists():
                return name
        return "buffalo_l"

    def _resolve_root_dir(self) -> Path:
        pack_name = self._resolve_pack_name()
        if (self.model_dir / "models" / pack_name).exists():
            return self.model_dir
        if (self.model_dir / pack_name).exists():
            return self.model_dir
        if (self.model_dir.parent / "models" / pack_name).exists():
            return self.model_dir.parent
        if (self.model_dir.parent / pack_name).exists():
            return self.model_dir.parent
        return self.model_dir

    def _ensure_loaded(self) -> bool:
        if self._app is not None:
            return True
        try:
            from insightface.app import FaceAnalysis
            import torch

            pack_name = self._resolve_pack_name()
            root_dir = self._resolve_root_dir()
            ctx_id = 0 if torch.cuda.is_available() else -1
            self._app = FaceAnalysis(name=pack_name, root=str(root_dir))
            self._app.prepare(ctx_id=ctx_id, det_size=(640, 640))
            return True
        except Exception as exc:
            self._load_error = str(exc)
            self._app = None
            return False

    def extract_face_embedding(self, image_path: str) -> Dict:
        status = self.status()
        if not status["ready"]:
            return {"ok": False, "reason": status["detail"]}
        if not image_path or not Path(image_path).exists():
            return {"ok": False, "reason": "image_path missing"}
        if not self._ensure_loaded():
            return {"ok": False, "reason": self._load_error or "insightface load failed"}

        try:
            import cv2

            image = cv2.imread(str(image_path))
            if image is None:
                return {"ok": False, "reason": "failed to read image"}
            faces = self._app.get(image)
            if not faces:
                return {"ok": False, "reason": "no face detected"}
            best = max(faces, key=lambda item: getattr(item, "det_score", 0.0))
            embedding = _normalize_vector(getattr(best, "embedding", None))
            bbox = getattr(best, "bbox", None)
            return {
                "ok": bool(embedding),
                "embedding": embedding,
                "det_score": float(getattr(best, "det_score", 0.0)),
                "bbox": [float(x) for x in bbox] if bbox is not None else None,
            }
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def match_gallery(self, image_path: str) -> Dict:
        if self.gallery_root is None or not self.gallery_root.exists():
            return {"ok": False, "reason": "gallery_root missing"}

        face_result = self.extract_face_embedding(image_path)
        if not face_result.get("ok"):
            return face_result

        probe = face_result.get("embedding")
        best_identity = None
        best_score = -1.0
        comparisons = 0

        for identity_dir in sorted(self.gallery_root.iterdir()):
            if not identity_dir.is_dir():
                continue
            scores = []
            for image_file in identity_dir.iterdir():
                if image_file.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
                    continue
                enrolled = self.extract_face_embedding(str(image_file))
                if not enrolled.get("ok"):
                    continue
                score = cosine_similarity(probe, enrolled.get("embedding"))
                if score is None:
                    continue
                scores.append(score)
                comparisons += 1
            if scores:
                average = sum(scores) / len(scores)
                if average > best_score:
                    best_score = average
                    best_identity = identity_dir.name

        if best_identity is None:
            return {"ok": False, "reason": "no valid gallery embeddings", "comparisons": comparisons}

        return {
            "ok": True,
            "identity": best_identity,
            "score": round(float(best_score), 4),
            "comparisons": comparisons,
            "det_score": face_result.get("det_score"),
        }


def build_enhanced_adapters(
    model_root: Path,
    gallery_root: Optional[Path],
    hf_token: str = "",
    python_executable: str = "",
) -> Dict[str, BaseAdapter]:
    return {
        "pyannote": PyannoteAdapter(
            model_dir=model_root / "pyannote",
            gallery_root=gallery_root,
            hf_token=hf_token,
            python_executable=python_executable,
        ),
        "wespeaker": WeSpeakerAdapter(
            model_dir=model_root / "wespeaker",
            gallery_root=gallery_root,
            hf_token=hf_token,
            python_executable=python_executable,
        ),
        "talknet_asd": TalkNetASDAdapter(
            model_dir=model_root / "talknet_asd",
            gallery_root=gallery_root,
            hf_token=hf_token,
            python_executable=python_executable,
        ),
        "insightface": InsightFaceAdapter(
            model_dir=model_root / "insightface",
            gallery_root=gallery_root,
            hf_token=hf_token,
            python_executable=python_executable,
        ),
    }


def get_adapter_statuses(adapters: Dict[str, BaseAdapter]) -> Dict[str, Dict]:
    return {key: adapter.status() for key, adapter in adapters.items()}
