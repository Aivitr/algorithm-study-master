import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock, Thread
from typing import Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.paths import PROJECT_ROOT
from app.models import Transcript
from app.services.research_enhanced_adapters import build_enhanced_adapters, cosine_similarity, get_adapter_statuses
from app.services.research_registry import (
    get_algorithm_registry,
    get_backbone_registry,
    get_classroom_dataset_registry,
)


AUTO_DOWNLOAD_IMPLEMENTED = True


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_text(value: Optional[str]) -> str:
    return (value or "").strip()


@dataclass(frozen=True)
class TranscriptResearchState:
    binding_source: str
    binding_confidence: float
    identity_review_status: str
    identity_review_note: str
    cross_modal_consistency: float

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass(frozen=True)
class ResearchModelSlot:
    key: str
    name: str
    expected_subdir: str
    role: str
    required_in_enhanced: bool = True
    auto_download_supported: bool = False


MODEL_SLOTS = (
    ResearchModelSlot(
        key="pyannote",
        name="pyannote speaker diarization",
        expected_subdir="pyannote",
        role="说话人分离与切分",
    ),
    ResearchModelSlot(
        key="wespeaker",
        name="WeSpeaker speaker embedding",
        expected_subdir="wespeaker",
        role="说话人表征与身份对齐",
    ),
    ResearchModelSlot(
        key="talknet_asd",
        name="TalkNet-ASD",
        expected_subdir="talknet_asd",
        role="谁在画面里说话",
    ),
    ResearchModelSlot(
        key="insightface",
        name="InsightFace",
        expected_subdir="insightface",
        role="人脸识别与用户ID绑定",
    ),
    ResearchModelSlot(
        key="clip_vit_b16",
        name="CLIP ViT-B/16",
        expected_subdir="clip_vit_b16",
        role="One-Shot MVG / CCM / CDL 跨模态基座",
    ),
    ResearchModelSlot(
        key="bge_m3",
        name="BGE-M3",
        expected_subdir="bge_m3",
        role="CLPC 风格观点聚类增强基座",
    ),
)


class ResearchRuntime:
    """
    standard profile:
      - keeps the current low-GPU pipeline
      - suitable for judges' local deployment

    enhanced profile:
      - keeps the current real-time path
      - stages assets for async enhancement
      - loads pyannote / WeSpeaker / TalkNet-ASD / InsightFace when available
    """

    def __init__(self):
        self._lock = Lock()
        self._transcript_reviews: Dict[int, Dict] = {}
        self._meeting_clusters: Dict[int, Dict[str, List[Dict]]] = {}
        self._adapters = None

    @property
    def deployment_profile(self) -> str:
        value = _safe_text(getattr(settings.research, "deployment_profile", "standard")).lower()
        return value if value in {"standard", "enhanced"} else "standard"

    @property
    def runtime_mode(self) -> str:
        return (_safe_text(settings.research.runtime_mode) or "documented_only").lower()

    @property
    def enabled(self) -> bool:
        return bool(settings.research.enabled)

    @property
    def model_root(self) -> Path:
        return Path(getattr(settings.research, "model_root", "storage/research_models"))

    @property
    def gallery_root(self) -> Path:
        return Path(getattr(settings.research, "gallery_root", "storage/research_gallery"))

    @property
    def cache_root(self) -> Path:
        return Path(getattr(settings.research, "cache_root", "storage/research_runtime_cache"))

    @property
    def model_source(self) -> str:
        return _safe_text(getattr(settings.research, "model_source", "manual_local")).lower() or "manual_local"

    @property
    def auto_download_requested(self) -> bool:
        return bool(getattr(settings.research, "auto_download_allowed", False))

    @property
    def hf_token(self) -> str:
        return _safe_text(getattr(settings.research, "hf_token", ""))

    @property
    def enhanced_python(self) -> str:
        return _safe_text(getattr(settings.research, "enhanced_python", "")) or "python"

    @property
    def standard_profile_active(self) -> bool:
        return self.deployment_profile == "standard"

    @property
    def enhanced_profile_selected(self) -> bool:
        return self.deployment_profile == "enhanced"

    @property
    def adapters(self):
        if self._adapters is None:
            self._adapters = build_enhanced_adapters(
                model_root=self.model_root,
                gallery_root=self.gallery_root if self.gallery_root.exists() else None,
                hf_token=self.hf_token,
                python_executable=self.enhanced_python,
            )
        return self._adapters

    def get_model_manifest(self) -> List[Dict]:
        adapter_statuses = get_adapter_statuses(self.adapters)
        manifest = []
        for slot in MODEL_SLOTS:
            expected_path = self.model_root / slot.expected_subdir
            has_real_files = self._slot_has_real_files(expected_path)
            item = {
                "key": slot.key,
                "name": slot.name,
                "role": slot.role,
                "expected_path": str(expected_path),
                "required_in_enhanced": slot.required_in_enhanced,
                "available": has_real_files,
                "auto_download_supported": slot.auto_download_supported,
            }
            if slot.key in adapter_statuses:
                item["adapter_status"] = adapter_statuses[slot.key]
                item["runtime_ready"] = adapter_statuses[slot.key].get("ready", False)
            else:
                item["runtime_ready"] = item["available"]
            manifest.append(item)
        return manifest

    def get_missing_required_models(self) -> List[Dict]:
        missing = []
        for item in self.get_model_manifest():
            if not item.get("required_in_enhanced"):
                continue
            if item.get("runtime_ready"):
                continue
            reason = ""
            adapter_status = item.get("adapter_status")
            if adapter_status:
                reason = adapter_status.get("detail", "")
            elif not item.get("available"):
                expected_path = Path(item.get("expected_path", ""))
                reason = "model files missing" if expected_path.exists() else "model directory missing"
            missing.append(
                {
                    "key": item.get("key"),
                    "name": item.get("name"),
                    "expected_path": item.get("expected_path"),
                    "reason": reason or "not ready",
                }
            )
        return missing

    @property
    def enhanced_stack_ready(self) -> bool:
        if not self.enhanced_profile_selected or not self.enabled:
            return False
        return len(self.get_missing_required_models()) == 0

    def get_profile_options(self) -> List[Dict]:
        return [
            {
                "key": "standard",
                "label": "标准版",
                "recommended_for": "评委本地快速部署、普通演示、低GPU环境",
                "gpu_requirement": "低",
                "pipeline": [
                    "沿用现有 Aliyun ASR / 视觉情绪识别 / LLM 分析主链路",
                    "研究算法仅保留轻量接入层和状态记录",
                    "无需额外部署增强版模型目录",
                ],
            },
            {
                "key": "enhanced",
                "label": "精确增强版",
                "recommended_for": "4090 等独立 GPU 服务器、精度展示、课后精修",
                "gpu_requirement": "中到高",
                "pipeline": [
                    "保留现有实时主链路，避免课堂实时性明显下降",
                    "启用 pyannote + WeSpeaker + TalkNet-ASD + InsightFace 的增强分支",
                    "支持后续与 One-Shot MVG / CCM / CDL / CLPC 的更深层集成",
                ],
            },
        ]

    def get_model_manifest(self) -> List[Dict]:
        adapter_statuses = get_adapter_statuses(self.adapters)
        auto_downloadable = {"pyannote", "wespeaker", "talknet_asd", "insightface", "clip_vit_b16", "bge_m3"}
        manifest = []
        for slot in MODEL_SLOTS:
            expected_path = self.model_root / slot.expected_subdir
            has_real_files = self._slot_has_real_files(expected_path)
            item = {
                "key": slot.key,
                "name": slot.name,
                "role": slot.role,
                "expected_path": str(expected_path),
                "required_in_enhanced": slot.required_in_enhanced,
                "available": has_real_files,
                "auto_download_supported": slot.key in auto_downloadable or slot.auto_download_supported,
            }
            if slot.key in adapter_statuses:
                item["adapter_status"] = adapter_statuses[slot.key]
                item["runtime_ready"] = adapter_statuses[slot.key].get("ready", False)
            else:
                item["runtime_ready"] = item["available"]
            manifest.append(item)
        return manifest

    def get_runtime_summary(self) -> Dict:
        missing_models = self.get_missing_required_models()
        effective_mode = self._resolve_effective_mode(missing_models)
        adapter_statuses = get_adapter_statuses(self.adapters)

        return {
            "deployment_profile": self.deployment_profile,
            "profile_label": "精确增强版" if self.enhanced_profile_selected else "标准版",
            "effective_mode": effective_mode,
            "enabled": self.enabled,
            "hook_layer_active": True,
            "enhanced_profile_selected": self.enhanced_profile_selected,
            "enhanced_stack_ready": self.enhanced_stack_ready,
            "gpu_inference_worker_enabled": self.enhanced_stack_ready,
            "gpu_inference_worker_note": (
                "增强版运行时已经能在模型目录和依赖齐备时真实调用 "
                "pyannote / WeSpeaker / TalkNet-ASD / InsightFace。"
            ),
            "model_root": str(self.model_root),
            "gallery_root": str(self.gallery_root),
            "cache_root": str(self.cache_root),
            "model_source": self.model_source,
            "auto_download_requested": self.auto_download_requested,
            "auto_download_implemented": AUTO_DOWNLOAD_IMPLEMENTED,
            "missing_required_models": missing_models,
            "adapter_statuses": adapter_statuses,
            "profile_options": self.get_profile_options(),
            "selection_guide": [
                "评委本地部署默认推荐标准版：对 GPU 要求低，可以直接按现有流程运行。",
                "如果要展示高精度说话人绑定和观点精修能力，可切换到精确增强版。",
                "精确增强版当前采用手动本地部署模型目录，不会自动联网下载研究模型。",
            ],
            "live_pipeline": [
                "Aliyun ASR / 现有实时识别主链路",
                "登录用户种子绑定",
                "轻量 CDL 一致性评分",
            ],
            "async_pipeline": [
                "pyannote 说话人切分",
                "WeSpeaker 语音原型聚合",
                "TalkNet-ASD 屏幕说话检测",
                "InsightFace 人脸原型聚合与图库匹配",
            ],
            "post_class_pipeline": [
                "CLPC 风格观点聚类增强挂载点",
                "课后高置信身份回放校验",
            ],
            "model_manifest": self.get_model_manifest(),
            "backbones": get_backbone_registry(),
            "algorithms": get_algorithm_registry(),
            "classroom_datasets": get_classroom_dataset_registry(),
        }

    def stage_runtime_assets(
        self,
        meeting_id: int,
        transcript_id: int,
        audio_path: Optional[str] = None,
        video_path: Optional[str] = None,
        snapshot_path: Optional[str] = None,
    ) -> Dict:
        if not self.enhanced_profile_selected:
            return {}

        staged = {}
        target_dir = self.cache_root / str(meeting_id) / str(transcript_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        for key, path_value in {
            "audio_path": audio_path,
            "video_path": video_path,
            "snapshot_path": snapshot_path,
        }.items():
            source = Path(path_value) if path_value else None
            if not source or not source.exists():
                continue
            destination = target_dir / source.name
            try:
                shutil.copy2(source, destination)
                staged[key] = str(destination)
            except Exception as exc:
                print(f"[RESEARCH] failed to stage {key}: {exc}")
        return staged

    def build_initial_transcript_state(
        self,
        username: str,
        text: str,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
    ) -> Dict:
        confidence = 0.84
        text_value = _safe_text(text)
        tone_value = _safe_text(audio_tone).lower()
        emotion_value = _safe_text(emotion_tag).lower()

        if len(text_value) >= 20:
            confidence += 0.06
        elif len(text_value) >= 8:
            confidence += 0.03

        if tone_value and tone_value not in {"unknown", "none"}:
            confidence += 0.03
        if emotion_value and emotion_value not in {"neutral", "calm"}:
            confidence += 0.02

        status, binding_source, note = self._build_profile_note(username)
        if self.enhanced_stack_ready:
            confidence += 0.02

        payload = TranscriptResearchState(
            binding_source=binding_source,
            binding_confidence=round(_clamp(confidence, 0.55, 0.99), 3),
            identity_review_status=status,
            identity_review_note=note,
            cross_modal_consistency=round(
                self._estimate_cross_modal_consistency(text_value, emotion_tag, body_action, audio_tone),
                3,
            ),
        )
        return payload.to_dict()

    def enqueue_transcript_enhancement(
        self,
        transcript_id: int,
        meeting_id: int,
        user_id: int,
        username: str,
        text: str,
        topic: str,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
        student_id: str = "",
        audio_path: str = "",
        video_path: str = "",
        snapshot_path: str = "",
    ) -> Dict:
        initial_state = self.build_initial_transcript_state(
            username=username,
            text=text,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
        )
        self._cache_review(transcript_id, initial_state)
        self._persist_transcript_state(transcript_id, initial_state)

        worker = Thread(
            target=self._run_async_review,
            kwargs={
                "transcript_id": transcript_id,
                "meeting_id": meeting_id,
                "user_id": user_id,
                "student_id": student_id,
                "username": username,
                "text": text,
                "topic": topic,
                "emotion_tag": emotion_tag,
                "body_action": body_action,
                "audio_tone": audio_tone,
                "audio_path": audio_path,
                "video_path": video_path,
                "snapshot_path": snapshot_path,
            },
            daemon=True,
        )
        worker.start()
        return initial_state

    def get_transcript_review(self, transcript_id: int) -> Optional[Dict]:
        with self._lock:
            cached = self._transcript_reviews.get(transcript_id)
            return dict(cached) if cached else None

    def refine_viewpoint_clusters(
        self,
        all_transcripts: List[Dict],
        topic: str,
        base_result: Dict,
    ) -> Dict:
        result = dict(base_result or {})
        viewpoints = result.get("viewpoints") or []
        speaker_pool = sorted(
            {_safe_text(item.get("username")) for item in all_transcripts if _safe_text(item.get("username"))}
        )

        refined_viewpoints = []
        for index, viewpoint in enumerate(viewpoints, start=1):
            supporters = []
            seen = set()
            for name in viewpoint.get("supporters") or []:
                clean_name = _safe_text(name)
                if clean_name and clean_name not in seen:
                    supporters.append(clean_name)
                    seen.add(clean_name)

            evidence_count = sum(
                1
                for item in all_transcripts
                if _safe_text(item.get("username")) in seen and _safe_text(item.get("content"))
            )

            merged = dict(viewpoint)
            merged["id"] = merged.get("id") or index
            merged["supporters"] = supporters
            merged["support_count"] = len(supporters)
            merged["evidence_count"] = evidence_count
            merged["refinement_stage"] = "llm_seed_then_clpc_hook"
            merged["deployment_profile"] = self.deployment_profile
            refined_viewpoints.append(merged)

        result["viewpoints"] = refined_viewpoints
        result["research"] = {
            "status": self._resolve_effective_mode(self.get_missing_required_models()),
            "deployment_profile": self.deployment_profile,
            "runtime_mode": self.runtime_mode,
            "enhanced_stack_ready": self.enhanced_stack_ready,
            "topic": _safe_text(topic),
            "algorithms": [
                "clpc_viewpoint_refinement",
            ],
            "candidate_backbones": [
                "bge_m3",
                "clip_vit_b16",
            ],
            "dataset_requirement": "classroom_viewpoint_cluster",
            "pipeline": [
                "LLM seed clustering",
                "speaker consensus cleanup",
                "CLPC-style pseudo label refinement hook",
            ],
            "speaker_pool": speaker_pool,
        }
        return result

    def _build_profile_note(self, username: str) -> Tuple[str, str, str]:
        if self.standard_profile_active:
            return (
                "standard_profile_active",
                "logged_in_user_seed+standard_profile",
                (
                    f"当前使用标准版部署策略，实时链路直接沿用现有流程运行；"
                    f"发言先绑定到登录身份种子 {username}，研究算法仅保留轻量增强记录，"
                    f"不要求高性能 GPU。"
                ),
            )

        missing_models = self.get_missing_required_models()
        if missing_models:
            missing_names = "、".join(item["name"] for item in missing_models)
            return (
                "enhanced_profile_pending_models",
                "logged_in_user_seed+enhanced_profile_pending",
                (
                    f"当前已选择精确增强版，但增强模型或依赖尚未就绪；"
                    f"待补齐项包括：{missing_names}。系统会先沿用现有实时主链路，"
                    f"待模型放入 {self.model_root} 并完成依赖安装后，再进入高精度增强版路径。"
                ),
            )

        return (
            "enhanced_profile_selected",
            "logged_in_user_seed+enhanced_profile",
            (
                f"当前已选择精确增强版，增强模型目录与依赖校验通过；"
                f"系统保留现有实时主链路，同时启用 pyannote + WeSpeaker、"
                f"TalkNet-ASD + InsightFace 的增强评估分支。"
            ),
        )

    def _resolve_effective_mode(self, missing_models: List[Dict]) -> str:
        if self.standard_profile_active:
            return "standard_runtime"
        if not self.enabled:
            return "enhanced_profile_disabled"
        if missing_models:
            return "enhanced_profile_waiting_models"
        return "enhanced_profile_stack_ready"

    def _run_async_review(
        self,
        transcript_id: int,
        meeting_id: int,
        user_id: int,
        student_id: str,
        username: str,
        text: str,
        topic: str,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
        audio_path: str,
        video_path: str,
        snapshot_path: str,
    ) -> None:
        initial = self.build_initial_transcript_state(
            username=username,
            text=text,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
        )

        consistency = self._estimate_cross_modal_consistency(text, emotion_tag, body_action, audio_tone)
        adjusted_confidence = initial["binding_confidence"]
        status = initial["identity_review_status"]
        binding_source = initial["binding_source"]
        notes = [initial["identity_review_note"]]
        identity_key = student_id or username or str(user_id)
        evidence: Dict[str, Dict] = {}

        if consistency >= 0.82:
            adjusted_confidence += 0.03
        elif consistency <= 0.55:
            adjusted_confidence -= 0.06

        if self.standard_profile_active:
            notes.append("异步阶段仅做轻量一致性复核，以保证本地部署时无需额外模型和高性能 GPU。")
        else:
            enhanced_summary = self._run_enhanced_stack(
                meeting_id=meeting_id,
                user_id=user_id,
                identity_key=identity_key,
                username=username,
                audio_path=audio_path,
                video_path=video_path,
                snapshot_path=snapshot_path,
            )
            evidence = enhanced_summary.get("evidence", {})
            adjusted_confidence += enhanced_summary.get("confidence_delta", 0.0)
            if enhanced_summary.get("status"):
                status = enhanced_summary["status"]
            if enhanced_summary.get("binding_source"):
                binding_source = enhanced_summary["binding_source"]
            notes.extend(enhanced_summary.get("notes", []))

        final_state = TranscriptResearchState(
            binding_source=binding_source,
            binding_confidence=round(_clamp(adjusted_confidence, 0.5, 0.995), 3),
            identity_review_status=status,
            identity_review_note=self._merge_notes(notes, evidence),
            cross_modal_consistency=round(consistency, 3),
        ).to_dict()

        self._cache_review(transcript_id, final_state)
        self._persist_transcript_state(transcript_id, final_state)

    def _run_enhanced_stack(
        self,
        meeting_id: int,
        user_id: int,
        identity_key: str,
        username: str,
        audio_path: str,
        video_path: str,
        snapshot_path: str,
    ) -> Dict:
        notes = []
        confidence_delta = 0.0
        status = "enhanced_review_completed"
        binding_source = "logged_in_user_seed+enhanced_runtime"
        evidence = {}
        adapters = self.adapters

        pyannote_result = adapters["pyannote"].diarize(audio_path) if audio_path else {"ok": False, "reason": "audio_path missing"}
        evidence["pyannote"] = pyannote_result
        if pyannote_result.get("ok"):
            speaker_count = int(pyannote_result.get("speaker_count", 0))
            dominant_ratio = float(pyannote_result.get("dominant_ratio", 0.0))
            if speaker_count <= 1:
                confidence_delta += 0.05
                notes.append("pyannote 检测到单说话人片段，语音归属更稳定。")
            else:
                confidence_delta -= min(0.12, 0.04 * (speaker_count - 1))
                notes.append(f"pyannote 检测到 {speaker_count} 个说话人，需警惕串音或多人同时发言。")
            if dominant_ratio >= 0.78:
                confidence_delta += 0.03
                notes.append("dominant speaker 占比高，主导发言片段较明确。")

        wespeaker_result = adapters["wespeaker"].extract_embedding(audio_path) if audio_path else {"ok": False, "reason": "audio_path missing"}
        evidence["wespeaker"] = wespeaker_result
        voice_cluster = None
        if wespeaker_result.get("ok") and wespeaker_result.get("embedding"):
            voice_cluster = self._update_cluster(
                meeting_id=meeting_id,
                modality="voice",
                embedding=wespeaker_result["embedding"],
                identity_key=identity_key,
                username=username,
                threshold=0.72,
            )
            evidence["wespeaker"]["cluster"] = voice_cluster
            delta, cluster_note = self._evaluate_cluster_alignment(voice_cluster, identity_key, "语音")
            confidence_delta += delta
            if cluster_note:
                notes.append(cluster_note)
            if voice_cluster.get("majority_identity") and voice_cluster.get("majority_identity") != identity_key:
                status = "enhanced_review_warning"
                binding_source = "logged_in_user_seed+enhanced_runtime_voice_warning"

        insightface_result = (
            adapters["insightface"].extract_face_embedding(snapshot_path)
            if snapshot_path
            else {"ok": False, "reason": "snapshot_path missing"}
        )
        evidence["insightface"] = insightface_result
        face_cluster = None
        gallery_match = None
        if insightface_result.get("ok") and insightface_result.get("embedding"):
            face_cluster = self._update_cluster(
                meeting_id=meeting_id,
                modality="face",
                embedding=insightface_result["embedding"],
                identity_key=identity_key,
                username=username,
                threshold=0.62,
            )
            evidence["insightface"]["cluster"] = face_cluster
            delta, cluster_note = self._evaluate_cluster_alignment(face_cluster, identity_key, "人脸")
            confidence_delta += delta
            if cluster_note:
                notes.append(cluster_note)

            gallery_match = adapters["insightface"].match_gallery(snapshot_path)
            evidence["insightface"]["gallery_match"] = gallery_match
            if gallery_match.get("ok"):
                matched_identity = _safe_text(gallery_match.get("identity"))
                if matched_identity and matched_identity == identity_key:
                    confidence_delta += 0.08
                    notes.append("InsightFace 图库匹配与当前用户一致。")
                elif matched_identity:
                    confidence_delta -= 0.10
                    status = "enhanced_review_warning"
                    binding_source = "logged_in_user_seed+enhanced_runtime_face_warning"
                    notes.append(f"InsightFace 图库匹配更接近 {matched_identity}，需复核用户绑定。")

        talknet_result = (
            adapters["talknet_asd"].analyze_video(video_path)
            if video_path
            else {"ok": False, "reason": "video_path missing"}
        )
        evidence["talknet_asd"] = talknet_result
        if talknet_result.get("ok"):
            active_probability = self._extract_probability(talknet_result)
            if active_probability >= 0.65:
                confidence_delta += 0.05
                notes.append("TalkNet-ASD 判断画面主体与语音同步度较高。")
            elif active_probability <= 0.35:
                confidence_delta -= 0.05
                status = "enhanced_review_warning"
                notes.append("TalkNet-ASD 提示画面主体说话一致性偏弱。")

        if voice_cluster and face_cluster:
            if voice_cluster.get("majority_identity") == face_cluster.get("majority_identity"):
                confidence_delta += 0.04
                notes.append("语音原型与人脸原型聚类结果一致。")
            else:
                confidence_delta -= 0.06
                status = "enhanced_review_warning"
                binding_source = "logged_in_user_seed+enhanced_runtime_cross_modal_warning"
                notes.append("语音原型与人脸原型聚类结果存在冲突。")

        if not any(item.get("ok") for item in evidence.values() if isinstance(item, dict)):
            status = "enhanced_review_waiting_runtime"
            binding_source = "logged_in_user_seed+enhanced_runtime_unavailable"
            notes.append("增强版 profile 已启用，但当前样本未成功触发增强模型推理。")

        return {
            "status": status,
            "binding_source": binding_source,
            "confidence_delta": confidence_delta,
            "notes": notes,
            "evidence": evidence,
        }

    def _update_cluster(
        self,
        meeting_id: int,
        modality: str,
        embedding: List[float],
        identity_key: str,
        username: str,
        threshold: float,
    ) -> Dict:
        normalized = self._normalize_embedding(embedding)
        if not normalized:
            return {}

        with self._lock:
            meeting_bucket = self._meeting_clusters.setdefault(meeting_id, {"voice": [], "face": []})
            clusters = meeting_bucket.setdefault(modality, [])

            best_cluster = None
            best_score = -1.0
            for cluster in clusters:
                score = cosine_similarity(normalized, cluster.get("prototype"))
                if score is not None and score > best_score:
                    best_score = score
                    best_cluster = cluster

            if best_cluster is None or best_score < threshold:
                cluster_id = f"{modality}_{len(clusters) + 1}"
                best_cluster = {
                    "cluster_id": cluster_id,
                    "prototype": normalized,
                    "count": 0,
                    "identity_votes": {},
                    "username_votes": {},
                }
                clusters.append(best_cluster)
                best_score = 1.0

            best_cluster["prototype"] = self._blend_embeddings(
                current=best_cluster.get("prototype"),
                new=normalized,
                count=int(best_cluster.get("count", 0)),
            )
            best_cluster["count"] = int(best_cluster.get("count", 0)) + 1
            if identity_key:
                votes = best_cluster.setdefault("identity_votes", {})
                votes[identity_key] = votes.get(identity_key, 0) + 1
            if username:
                user_votes = best_cluster.setdefault("username_votes", {})
                user_votes[username] = user_votes.get(username, 0) + 1

            majority_identity = self._get_majority_key(best_cluster.get("identity_votes", {}))
            majority_username = self._get_majority_key(best_cluster.get("username_votes", {}))

            return {
                "cluster_id": best_cluster["cluster_id"],
                "similarity": round(float(best_score), 4),
                "cluster_size": best_cluster["count"],
                "majority_identity": majority_identity,
                "majority_username": majority_username,
            }

    def _evaluate_cluster_alignment(self, cluster: Dict, identity_key: str, modality_label: str) -> Tuple[float, str]:
        if not cluster:
            return 0.0, ""

        cluster_size = int(cluster.get("cluster_size", 0))
        majority_identity = _safe_text(cluster.get("majority_identity"))
        similarity = float(cluster.get("similarity", 0.0))
        if cluster_size <= 1:
            return 0.0, f"{modality_label}原型已建立，后续样本可继续增强稳定性。"
        if majority_identity == identity_key:
            return 0.05, f"{modality_label}原型与当前用户历史聚类一致。"
        if majority_identity and majority_identity != identity_key and similarity >= 0.78:
            return -0.10, f"{modality_label}原型更接近 {majority_identity}，存在潜在错绑风险。"
        return 0.0, ""

    def _merge_notes(self, notes: List[str], evidence: Dict) -> str:
        merged = [item for item in (_safe_text(note) for note in notes) if item]
        if evidence:
            summary_tokens = []
            for key, payload in evidence.items():
                if not isinstance(payload, dict):
                    continue
                if payload.get("ok"):
                    summary_tokens.append(key)
            if summary_tokens:
                merged.append(f"增强证据链已触发: {', '.join(summary_tokens)}。")
        return " ".join(merged)[:980]

    def _extract_probability(self, payload: Dict) -> float:
        for key in ("active_probability", "speaking_probability", "score", "confidence"):
            value = payload.get(key)
            try:
                return float(value)
            except Exception:
                continue
        return 0.0

    def _normalize_embedding(self, embedding: List[float]) -> Optional[List[float]]:
        if not embedding:
            return None
        length = sum(float(x) * float(x) for x in embedding) ** 0.5
        if length <= 1e-6:
            return None
        return [float(x) / length for x in embedding]

    def _blend_embeddings(self, current: Optional[List[float]], new: List[float], count: int) -> List[float]:
        if not current or count <= 0:
            return list(new)
        mixed = [((current[i] * count) + new[i]) / (count + 1) for i in range(min(len(current), len(new)))]
        normalized = self._normalize_embedding(mixed)
        return normalized or list(new)

    def _get_majority_key(self, votes: Dict[str, int]) -> str:
        if not votes:
            return ""
        return max(votes, key=votes.get)

    def _slot_has_real_files(self, path: Path) -> bool:
        if not path.exists():
            return False
        ignored = {"PLACE_MODEL_FILES_HERE.txt", "bridge.py", "__pycache__"}
        for item in path.iterdir():
            if item.name in ignored:
                continue
            return True
        return False

    def _persist_transcript_state(self, transcript_id: int, payload: Dict) -> None:
        db = SessionLocal()
        try:
            transcript = db.query(Transcript).filter(Transcript.id == transcript_id).first()
            if not transcript:
                return

            transcript.binding_source = payload.get("binding_source")
            transcript.binding_confidence = payload.get("binding_confidence")
            transcript.identity_review_status = payload.get("identity_review_status")
            transcript.identity_review_note = payload.get("identity_review_note")
            transcript.cross_modal_consistency = payload.get("cross_modal_consistency")
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"[RESEARCH] transcript state persist skipped: {exc}")
        finally:
            db.close()

    def _cache_review(self, transcript_id: int, payload: Dict) -> None:
        with self._lock:
            self._transcript_reviews[transcript_id] = dict(payload)

    def _estimate_cross_modal_consistency(
        self,
        text: str,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
    ) -> float:
        text_value = _safe_text(text)
        emotion_value = _safe_text(emotion_tag).lower()
        action_value = _safe_text(body_action).lower()
        tone_value = _safe_text(audio_tone).lower()

        score = 0.62
        if tone_value == "loud" and emotion_value in {"excited", "happy", "angry", "surprised"}:
            score += 0.14
        elif tone_value == "quiet" and emotion_value in {"sad", "confused", "thinking", "calm"}:
            score += 0.14
        elif tone_value in {"normal", "steady", "medium"}:
            score += 0.06

        if action_value in {"static", "focused", "writing", "listening"}:
            score += 0.05
        elif action_value in {"high_activity", "gesturing", "active"}:
            score += 0.03

        if len(text_value) >= 20:
            score += 0.05
        elif len(text_value) <= 5:
            score -= 0.05

        confusion_cues = ("?", "？", "为什么", "怎么", "不理解", "疑问")
        if any(token in text_value for token in confusion_cues) and emotion_value in {"confused", "thinking", "sad"}:
            score += 0.06

        assertive_cues = ("我认为", "我觉得", "因为", "所以", "例如", "首先")
        if any(token in text_value for token in assertive_cues) and emotion_value not in {"sad"}:
            score += 0.04

        return _clamp(score, 0.35, 0.98)

    def _setup_scripts_summary(self) -> Dict:
        # 锚点取自 app/core/paths.py，不用 `Path(__file__)` 推导：本文件在
        # app/services/ 下，`__file__` 的父目录会指错（脚本实际都在仓库根）。
        repo_root = PROJECT_ROOT
        return {
            "prepare_layout": str(repo_root / "prepare_enhanced_model_layout.ps1"),
            "setup_enhanced_runtime": str(repo_root / "setup_enhanced_runtime.ps1"),
            "download_open_models": str(repo_root / "download_enhanced_open_models.py"),
            "check_runtime": str(repo_root / "check_enhanced_runtime.ps1"),
            "requirements_file": str(repo_root / "requirements_enhanced_runtime.txt"),
        }

    def get_profile_options(self) -> List[Dict]:
        return [
            {
                "key": "standard",
                "label": "标准版",
                "recommended_for": "评委本地部署、普通演示、低GPU环境",
                "gpu_requirement": "low",
                "pipeline": [
                    "沿用当前系统现有实时主链路",
                    "不要求额外部署研究增强模型",
                    "适合开箱即用的本地运行场景",
                ],
            },
            {
                "key": "enhanced",
                "label": "加强版",
                "recommended_for": "4090等独立GPU服务器、精度展示、课后精修",
                "gpu_requirement": "medium_to_high",
                "pipeline": [
                    "保留当前实时主链路，避免课堂实时性明显下降",
                    "启用 pyannote + WeSpeaker + TalkNet-ASD + InsightFace",
                    "要求同时准备 CLIP 与 BGE 作为研究算法资产目录",
                ],
            },
        ]

    def get_runtime_summary(self) -> Dict:
        missing_models = self.get_missing_required_models()
        effective_mode = self._resolve_effective_mode(missing_models)
        adapter_statuses = get_adapter_statuses(self.adapters)

        return {
            "deployment_profile": self.deployment_profile,
            "profile_label": "enhanced" if self.enhanced_profile_selected else "standard",
            "runtime_mode": self.runtime_mode,
            "effective_mode": effective_mode,
            "enabled": self.enabled,
            "hook_layer_active": True,
            "enhanced_profile_selected": self.enhanced_profile_selected,
            "enhanced_stack_ready": self.enhanced_stack_ready,
            "gpu_inference_worker_enabled": self.enhanced_stack_ready,
            "gpu_inference_worker_note": (
                "Enhanced deployment becomes active only after the full open-source stack is ready: "
                "pyannote, WeSpeaker, TalkNet-ASD, InsightFace, CLIP and BGE."
            ),
            "model_root": str(self.model_root),
            "gallery_root": str(self.gallery_root),
            "cache_root": str(self.cache_root),
            "enhanced_python": self.enhanced_python,
            "model_source": self.model_source,
            "auto_download_requested": self.auto_download_requested,
            "auto_download_implemented": AUTO_DOWNLOAD_IMPLEMENTED,
            "setup_scripts": self._setup_scripts_summary(),
            "strict_enhanced_policy": (
                "When deployment_profile=enhanced, the system will not treat the enhanced path as active "
                "until all required open-source models and dependencies are ready."
            ),
            "missing_required_models": missing_models,
            "adapter_statuses": adapter_statuses,
            "profile_options": self.get_profile_options(),
            "selection_guide": [
                "Use the standard profile for judge laptops and low-GPU environments.",
                "Use the enhanced profile only after running setup_enhanced_runtime.ps1 on the target machine.",
                "Verify /api/research-runtime or check_enhanced_runtime.ps1 shows enhanced_stack_ready=true.",
            ],
            "live_pipeline": [
                "current ASR and classroom analysis main path",
                "logged-in user seed binding",
                "lightweight cross-modal consistency scoring",
            ],
            "async_pipeline": [
                "pyannote diarization",
                "WeSpeaker embedding clustering",
                "TalkNet-ASD active speaker verification",
                "InsightFace face identity correction",
            ],
            "post_class_pipeline": [
                "CLPC-style viewpoint refinement hooks",
                "One-Shot MVG / CCM / CDL backbone asset registry",
            ],
            "model_manifest": self.get_model_manifest(),
            "backbones": get_backbone_registry(),
            "algorithms": get_algorithm_registry(),
            "classroom_datasets": get_classroom_dataset_registry(),
        }

    def _build_profile_note(self, username: str) -> Tuple[str, str, str]:
        if self.standard_profile_active:
            return (
                "standard_profile_active",
                "logged_in_user_seed+standard_profile",
                (
                    f"当前处于标准版部署模式，系统继续沿用现有低门槛实时链路。"
                    f"发言先绑定到登录身份种子 {username}，研究算法仅保留轻量记录层。"
                ),
            )

        missing_models = self.get_missing_required_models()
        if missing_models:
            missing_names = ", ".join(item["name"] for item in missing_models)
            return (
                "enhanced_profile_blocked_missing_models",
                "logged_in_user_seed+enhanced_profile_blocked",
                (
                    f"当前已选择加强版，但完整增强栈尚未部署完成。缺失或未就绪项包括：{missing_names}。"
                    f"请先完成 {self.model_root} 下的模型与依赖安装，再以加强版模式运行。"
                ),
            )

        return (
            "enhanced_profile_active",
            "logged_in_user_seed+enhanced_profile",
            (
                "当前已进入加强版部署模式，系统会在保留现有实时主链路的同时，"
                "启用 pyannote、WeSpeaker、TalkNet-ASD 和 InsightFace 的增强校验链路。"
            ),
        )

    def _resolve_effective_mode(self, missing_models: List[Dict]) -> str:
        if self.standard_profile_active:
            return "standard_runtime"
        if not self.enabled:
            return "enhanced_profile_disabled"
        if missing_models:
            return "enhanced_profile_blocked_missing_models"
        return "enhanced_profile_active"

    def _run_async_review(
        self,
        transcript_id: int,
        meeting_id: int,
        user_id: int,
        student_id: str,
        username: str,
        text: str,
        topic: str,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
        audio_path: str,
        video_path: str,
        snapshot_path: str,
    ) -> None:
        initial = self.build_initial_transcript_state(
            username=username,
            text=text,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
        )

        consistency = self._estimate_cross_modal_consistency(text, emotion_tag, body_action, audio_tone)
        adjusted_confidence = initial["binding_confidence"]
        status = initial["identity_review_status"]
        binding_source = initial["binding_source"]
        notes = [initial["identity_review_note"]]
        identity_key = student_id or username or str(user_id)
        evidence: Dict[str, Dict] = {}

        if consistency >= 0.82:
            adjusted_confidence += 0.03
        elif consistency <= 0.55:
            adjusted_confidence -= 0.06

        if self.standard_profile_active:
            notes.append("标准版异步阶段只做轻量一致性复核，不启用高负载增强模型。")
        elif not self.enhanced_stack_ready:
            status = "enhanced_profile_blocked_missing_models"
            binding_source = "logged_in_user_seed+enhanced_profile_blocked"
            notes.append("加强版已被选中，但完整增强模型栈尚未就绪，因此当前记录仍按基线路径处理。")
        else:
            enhanced_summary = self._run_enhanced_stack(
                meeting_id=meeting_id,
                user_id=user_id,
                identity_key=identity_key,
                username=username,
                audio_path=audio_path,
                video_path=video_path,
                snapshot_path=snapshot_path,
            )
            evidence = enhanced_summary.get("evidence", {})
            adjusted_confidence += enhanced_summary.get("confidence_delta", 0.0)
            if enhanced_summary.get("status"):
                status = enhanced_summary["status"]
            if enhanced_summary.get("binding_source"):
                binding_source = enhanced_summary["binding_source"]
            notes.extend(enhanced_summary.get("notes", []))

        final_state = TranscriptResearchState(
            binding_source=binding_source,
            binding_confidence=round(_clamp(adjusted_confidence, 0.5, 0.995), 3),
            identity_review_status=status,
            identity_review_note=self._merge_notes(notes, evidence),
            cross_modal_consistency=round(consistency, 3),
        ).to_dict()

        self._cache_review(transcript_id, final_state)
        self._persist_transcript_state(transcript_id, final_state)


research_runtime = ResearchRuntime()


from app.services.research_algorithm_fusion import ResearchAlgorithmFusion


_ORIGINAL_GET_RUNTIME_SUMMARY = ResearchRuntime.get_runtime_summary
_ORIGINAL_REFINE_VIEWPOINT_CLUSTERS = ResearchRuntime.refine_viewpoint_clusters
_ORIGINAL_RUN_ENHANCED_STACK = ResearchRuntime._run_enhanced_stack


def _research_runtime_get_fusion(self) -> ResearchAlgorithmFusion:
    fusion = getattr(self, "_fusion", None)
    if fusion is None:
        fusion = ResearchAlgorithmFusion(self.model_root)
        self._fusion = fusion
    return fusion


def _research_runtime_refine_speech_assessment(
    self,
    text: str,
    topic: str,
    dimensions: Optional[Dict],
    quality_score: float,
    quality_feedback: str,
    relevance: float,
    emotion_tag: str,
    body_action: str,
    audio_tone: str,
) -> Dict:
    if not self.enhanced_profile_selected or not self.enabled:
        return {
            "score": quality_score,
            "dimensions": dict(dimensions or {}),
            "quality_feedback": quality_feedback,
            "research": {},
        }
    return self.fusion.apply_pdl(
        text=text,
        topic=topic,
        base_dimensions=dimensions,
        base_score=quality_score,
        relevance=relevance,
        emotion_tag=emotion_tag,
        body_action=body_action,
        audio_tone=audio_tone,
        quality_feedback=quality_feedback,
    )


def _research_runtime_enrich_course_report(
    self,
    meeting_topic: str,
    all_transcripts: List[Dict],
    emotion_stats: Dict,
    student_performances: List[Dict],
    course_report: Dict,
) -> Dict:
    if not self.enhanced_profile_selected or not self.enabled:
        return dict(course_report or {})
    return self.fusion.enrich_course_report(
        meeting_topic=meeting_topic,
        all_transcripts=all_transcripts,
        student_performances=student_performances,
        emotion_stats=emotion_stats,
        course_report=course_report,
    )


def _research_runtime_refine_viewpoint_clusters(
    self,
    all_transcripts: List[Dict],
    topic: str,
    base_result: Dict,
) -> Dict:
    seed_result = _ORIGINAL_REFINE_VIEWPOINT_CLUSTERS(self, all_transcripts, topic, base_result)
    if not self.enhanced_profile_selected or not self.enabled:
        return seed_result
    return self.fusion.refine_viewpoints(
        all_transcripts=all_transcripts,
        topic=topic,
        base_result=seed_result,
        deployment_profile=self.deployment_profile,
        runtime_mode=self.runtime_mode,
        enhanced_stack_ready=self.enhanced_stack_ready,
    )


def _research_runtime_run_enhanced_stack(
    self,
    meeting_id: int,
    user_id: int,
    identity_key: str,
    username: str,
    audio_path: str,
    video_path: str,
    snapshot_path: str,
    text: str = "",
    emotion_tag: str = "",
    body_action: str = "",
    audio_tone: str = "",
    baseline_consistency: float = 0.65,
) -> Dict:
    base_summary = _ORIGINAL_RUN_ENHANCED_STACK(
        self,
        meeting_id=meeting_id,
        user_id=user_id,
        identity_key=identity_key,
        username=username,
        audio_path=audio_path,
        video_path=video_path,
        snapshot_path=snapshot_path,
    )
    evidence = dict(base_summary.get("evidence") or {})
    wespeaker_evidence = dict(evidence.get("wespeaker") or {})
    insightface_evidence = dict(evidence.get("insightface") or {})

    algorithm_summary = self.fusion.apply_identity_algorithms(
        meeting_id=meeting_id,
        identity_key=identity_key,
        username=username,
        text=text,
        emotion_tag=emotion_tag,
        body_action=body_action,
        audio_tone=audio_tone,
        voice_embedding=wespeaker_evidence.get("embedding"),
        face_embedding=insightface_evidence.get("embedding"),
        voice_cluster=wespeaker_evidence.get("cluster"),
        face_cluster=insightface_evidence.get("cluster"),
        pyannote_result=evidence.get("pyannote"),
        talknet_result=evidence.get("talknet_asd"),
        gallery_match=insightface_evidence.get("gallery_match"),
        baseline_consistency=baseline_consistency,
    )

    merged_notes = list(base_summary.get("notes") or []) + list(algorithm_summary.get("notes") or [])
    merged_status = base_summary.get("status") or "enhanced_review_completed"
    if algorithm_summary.get("status") and algorithm_summary.get("status") != "enhanced_review_completed":
        merged_status = algorithm_summary["status"]
    merged_binding_source = base_summary.get("binding_source") or "logged_in_user_seed+enhanced_runtime"
    if algorithm_summary.get("binding_source"):
        merged_binding_source = algorithm_summary["binding_source"]

    evidence["algorithm_fusion"] = algorithm_summary.get("algorithm_outputs", {})
    return {
        "status": merged_status,
        "binding_source": merged_binding_source,
        "confidence_delta": float(base_summary.get("confidence_delta", 0.0)) + float(algorithm_summary.get("confidence_delta", 0.0)),
        "notes": merged_notes,
        "evidence": evidence,
        "consistency_override": algorithm_summary.get("consistency_override", baseline_consistency),
    }


def _research_runtime_run_async_review(
    self,
    transcript_id: int,
    meeting_id: int,
    user_id: int,
    student_id: str,
    username: str,
    text: str,
    topic: str,
    emotion_tag: str,
    body_action: str,
    audio_tone: str,
    audio_path: str,
    video_path: str,
    snapshot_path: str,
) -> None:
    initial = self.build_initial_transcript_state(
        username=username,
        text=text,
        emotion_tag=emotion_tag,
        body_action=body_action,
        audio_tone=audio_tone,
    )

    consistency = self._estimate_cross_modal_consistency(text, emotion_tag, body_action, audio_tone)
    adjusted_confidence = initial["binding_confidence"]
    status = initial["identity_review_status"]
    binding_source = initial["binding_source"]
    notes = [initial["identity_review_note"]]
    identity_key = student_id or username or str(user_id)
    evidence: Dict[str, Dict] = {}

    if consistency >= 0.82:
        adjusted_confidence += 0.03
    elif consistency <= 0.55:
        adjusted_confidence -= 0.06

    if self.standard_profile_active:
        notes.append("标准版保持低门槛实时链路，不启用高负载增强身份模型。")
    elif not self.enhanced_stack_ready:
        status = "enhanced_profile_blocked_missing_models"
        binding_source = "logged_in_user_seed+enhanced_profile_blocked"
        notes.append("已选择加强版，但增强模型或依赖尚未就绪，当前记录按基线流程处理。")
    else:
        enhanced_summary = self._run_enhanced_stack(
            meeting_id=meeting_id,
            user_id=user_id,
            identity_key=identity_key,
            username=username,
            audio_path=audio_path,
            video_path=video_path,
            snapshot_path=snapshot_path,
            text=text,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
            baseline_consistency=consistency,
        )
        evidence = enhanced_summary.get("evidence", {})
        adjusted_confidence += enhanced_summary.get("confidence_delta", 0.0)
        if enhanced_summary.get("status"):
            status = enhanced_summary["status"]
        if enhanced_summary.get("binding_source"):
            binding_source = enhanced_summary["binding_source"]
        if enhanced_summary.get("consistency_override") is not None:
            consistency = round(
                (
                    float(consistency)
                    + float(enhanced_summary.get("consistency_override", consistency))
                )
                / 2.0,
                4,
            )
        notes.extend(enhanced_summary.get("notes", []))

    final_state = TranscriptResearchState(
        binding_source=binding_source,
        binding_confidence=round(_clamp(adjusted_confidence, 0.5, 0.995), 3),
        identity_review_status=status,
        identity_review_note=self._merge_notes(notes, evidence),
        cross_modal_consistency=round(consistency, 3),
    ).to_dict()

    self._cache_review(transcript_id, final_state)
    self._persist_transcript_state(transcript_id, final_state)


def _research_runtime_get_runtime_summary(self) -> Dict:
    summary = _ORIGINAL_GET_RUNTIME_SUMMARY(self)
    summary["algorithm_fusion"] = self.fusion.get_runtime_status()
    post_class_pipeline = list(summary.get("post_class_pipeline") or [])
    for item in [
        "PDL soft distribution scoring",
        "CLPC-style viewpoint refinement",
        "IPA personalized diagnosis",
        "One-Shot MVG / CCM / CDL runtime adaptation",
    ]:
        if item not in post_class_pipeline:
            post_class_pipeline.append(item)
    summary["post_class_pipeline"] = post_class_pipeline
    return summary


def _research_runtime_research_algorithms_active(self) -> bool:
    return bool(self.enhanced_profile_selected and self.enabled)


ResearchRuntime.fusion = property(_research_runtime_get_fusion)
ResearchRuntime.research_algorithms_active = property(_research_runtime_research_algorithms_active)
ResearchRuntime.refine_speech_assessment = _research_runtime_refine_speech_assessment
ResearchRuntime.enrich_course_report = _research_runtime_enrich_course_report
ResearchRuntime.refine_viewpoint_clusters = _research_runtime_refine_viewpoint_clusters
ResearchRuntime._run_enhanced_stack = _research_runtime_run_enhanced_stack
ResearchRuntime._run_async_review = _research_runtime_run_async_review
ResearchRuntime.get_runtime_summary = _research_runtime_get_runtime_summary
