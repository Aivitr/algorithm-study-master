import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import settings


def _safe_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_vector(vector: Optional[List[float]]) -> Optional[List[float]]:
    if not vector:
        return None
    try:
        raw = [float(x) for x in vector]
    except Exception:
        return None
    if not raw:
        return None
    norm = math.sqrt(sum(x * x for x in raw))
    if norm <= 1e-8:
        return None
    return [x / norm for x in raw]


def _cosine_similarity(left: Optional[List[float]], right: Optional[List[float]]) -> Optional[float]:
    a = _normalize_vector(left)
    b = _normalize_vector(right)
    if not a or not b or len(a) != len(b):
        return None
    return float(sum(x * y for x, y in zip(a, b)))


def _mean_vectors(vectors: List[List[float]]) -> Optional[List[float]]:
    clean = [_normalize_vector(vector) for vector in vectors if vector]
    clean = [vector for vector in clean if vector]
    if not clean:
        return None
    size = min(len(vector) for vector in clean)
    merged = [0.0] * size
    for vector in clean:
        for index in range(size):
            merged[index] += vector[index]
    merged = [value / len(clean) for value in merged]
    return _normalize_vector(merged)


def _blend_vectors(current: Optional[List[float]], new: Optional[List[float]], alpha: float) -> Optional[List[float]]:
    current_norm = _normalize_vector(current)
    new_norm = _normalize_vector(new)
    if not current_norm:
        return new_norm
    if not new_norm:
        return current_norm
    size = min(len(current_norm), len(new_norm))
    merged = [((1.0 - alpha) * current_norm[i]) + (alpha * new_norm[i]) for i in range(size)]
    return _normalize_vector(merged)


def _extract_probability(payload: Optional[Dict]) -> float:
    payload = payload or {}
    for key in ("active_probability", "speaking_probability", "score", "confidence"):
        try:
            return float(payload.get(key, 0.0))
        except Exception:
            continue
    return 0.0


def _extract_keywords(texts: List[str], limit: int = 6) -> List[str]:
    stopwords = {
        "我们",
        "你们",
        "他们",
        "这个",
        "那个",
        "然后",
        "但是",
        "因为",
        "所以",
        "就是",
        "可以",
        "应该",
        "如果",
        "已经",
        "还有",
        "一下",
        "进行",
        "一个",
        "一些",
        "以及",
        "对于",
        "比较",
        "还是",
        "不是",
        "什么",
        "怎么",
        "这样",
        "那个",
        "需要",
    }
    counter: Counter = Counter()
    for text in texts:
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", _safe_text(text)):
            if token in stopwords:
                continue
            counter[token] += 1
    return [item for item, _ in counter.most_common(limit)]


def _cue_ratio(text: str, cues: Tuple[str, ...]) -> float:
    sentence = _safe_text(text)
    if not sentence:
        return 0.0
    hits = sum(sentence.count(cue) for cue in cues)
    return _clamp(hits / max(1.0, len(sentence) / 18.0), 0.0, 1.0)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", _safe_text(left)))
    right_tokens = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", _safe_text(right)))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


class ResearchBackboneManager:
    def __init__(self, model_root: Path):
        self.model_root = Path(model_root)
        self._text_models: Dict[str, object] = {}
        self._load_errors: Dict[str, str] = {}

    def _model_dir(self, key: str) -> Path:
        return self.model_root / key

    def _has_real_files(self, path: Path) -> bool:
        if not path.exists():
            return False
        ignored = {"PLACE_MODEL_FILES_HERE.txt", "bridge.py", "__pycache__"}
        for item in path.iterdir():
            if item.name in ignored:
                continue
            return True
        return False

    def _load_sentence_transformer(self, key: str):
        if key in self._text_models:
            return self._text_models[key]
        model_dir = self._model_dir(key)
        if not self._has_real_files(model_dir):
            self._load_errors[key] = "local model files missing"
            return None
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(str(model_dir), device="cpu")
            self._text_models[key] = model
            return model
        except Exception as exc:
            self._load_errors[key] = str(exc)
            return None

    def _hash_embedding(self, text: str, dim: int = 256, salt: str = "") -> List[float]:
        text = f"{salt}|{_safe_text(text)}"
        if not text:
            text = f"{salt}|<empty>"
        values: List[float] = []
        for index in range(dim):
            digest = hashlib.sha256(f"{text}|{index}".encode("utf-8")).digest()
            number = int.from_bytes(digest[:4], "big", signed=False)
            values.append((number / 4294967295.0) * 2.0 - 1.0)
        normalized = _normalize_vector(values)
        return normalized or [0.0] * dim

    def encode_text(self, text: str, preferred: str = "bge_m3") -> Dict:
        sentence = _safe_text(text)
        model = self._load_sentence_transformer(preferred)
        if model is not None:
            try:
                vector = model.encode([sentence or "<empty>"], normalize_embeddings=True)[0]
                return {
                    "vector": [float(x) for x in vector],
                    "backbone": preferred,
                    "backend": "sentence_transformers_local",
                }
            except Exception as exc:
                self._load_errors[preferred] = str(exc)

        return {
            "vector": self._hash_embedding(sentence, salt=preferred),
            "backbone": preferred,
            "backend": "hash_fallback",
        }

    def get_backbone_status(self) -> Dict[str, Dict]:
        return {
            "clip_vit_b16": {
                "configured_path": str(self._model_dir("clip_vit_b16")),
                "available": self._has_real_files(self._model_dir("clip_vit_b16")),
                "runtime_backend": "external_embedding_fusion",
                "intended_role": "One-Shot MVG / CCM / CDL classroom adaptation backbone",
                "source_model_id": settings.research.clip_model_id,
            },
            "bge_m3": {
                "configured_path": str(self._model_dir("bge_m3")),
                "available": self._has_real_files(self._model_dir("bge_m3")),
                "runtime_backend": "sentence_transformers_local"
                if self._load_sentence_transformer("bge_m3") is not None
                else "hash_fallback",
                "intended_role": "PDL&CLPC viewpoint/text embedding backbone",
                "source_model_id": settings.research.bge_model_id,
                "load_error": self._load_errors.get("bge_m3", ""),
            },
        }


class PDLScorer:
    REASONING_CUES = ("因为", "所以", "例如", "比如", "首先", "其次", "说明", "推导", "由此", "证明")
    CREATIVE_CUES = ("也许", "如果", "换个角度", "可以尝试", "设想", "创新", "不如", "扩展")
    EXPRESSION_CUES = ("我认为", "我的观点", "总结", "结论", "一方面", "另一方面")

    def __init__(self, backbones: ResearchBackboneManager):
        self.backbones = backbones

    def score(
        self,
        text: str,
        topic: str,
        base_dimensions: Optional[Dict] = None,
        base_score: float = 50.0,
        relevance: float = 50.0,
        emotion_tag: str = "",
        body_action: str = "",
        audio_tone: str = "",
    ) -> Dict:
        dimensions = dict(base_dimensions or {})
        text_value = _safe_text(text)
        topic_value = _safe_text(topic)
        text_embedding = self.backbones.encode_text(text_value, preferred="bge_m3")
        topic_embedding = self.backbones.encode_text(topic_value or "课堂主题", preferred="bge_m3")
        topic_similarity = _cosine_similarity(text_embedding["vector"], topic_embedding["vector"]) or 0.0
        overlap = _token_overlap(text_value, topic_value)
        reasoning_ratio = _cue_ratio(text_value, self.REASONING_CUES)
        creative_ratio = _cue_ratio(text_value, self.CREATIVE_CUES)
        expression_ratio = _cue_ratio(text_value, self.EXPRESSION_CUES)
        length_bonus = _clamp(len(text_value) / 90.0, 0.0, 1.0)

        emotion_bonus = 0.0
        if _safe_text(audio_tone).lower() == "loud" and _safe_text(emotion_tag).lower() in {"happy", "excited", "surprised"}:
            emotion_bonus = 0.05
        elif _safe_text(audio_tone).lower() == "quiet" and _safe_text(emotion_tag).lower() in {"calm", "thinking", "confused"}:
            emotion_bonus = 0.03

        action_bonus = 0.04 if _safe_text(body_action).lower() in {"focused", "writing", "listening", "active"} else 0.0

        base_relevance = float(dimensions.get("relevance", relevance or base_score))
        base_depth = float(dimensions.get("depth", base_score))
        base_creativity = float(dimensions.get("creativity", base_score))
        base_expression = float(dimensions.get("expression", base_score))

        raw_relevance = _clamp(
            0.72 * base_relevance + 18.0 * topic_similarity + 12.0 * overlap + 6.0 * action_bonus,
            25.0,
            98.0,
        )
        raw_depth = _clamp(
            0.72 * base_depth + 16.0 * reasoning_ratio + 10.0 * length_bonus + 5.0 * topic_similarity,
            25.0,
            98.0,
        )
        raw_creativity = _clamp(
            0.70 * base_creativity + 14.0 * creative_ratio + 8.0 * max(0.0, 1.0 - overlap) + 6.0 * reasoning_ratio,
            20.0,
            97.0,
        )
        raw_expression = _clamp(
            0.74 * base_expression + 12.0 * expression_ratio + 10.0 * length_bonus + 8.0 * emotion_bonus + 6.0 * action_bonus,
            25.0,
            98.0,
        )

        relevance_score = round(_clamp((0.68 * base_relevance) + (0.32 * raw_relevance), 25.0, 98.0))
        depth_score = round(_clamp((0.68 * base_depth) + (0.32 * raw_depth), 25.0, 98.0))
        creativity_score = round(_clamp((0.68 * base_creativity) + (0.32 * raw_creativity), 20.0, 97.0))
        expression_score = round(_clamp((0.68 * base_expression) + (0.32 * raw_expression), 25.0, 98.0))

        updated_dimensions = {
            "relevance": relevance_score,
            "depth": depth_score,
            "creativity": creativity_score,
            "expression": expression_score,
        }
        weighted_score = round(
            _clamp(
                0.4 * relevance_score + 0.3 * depth_score + 0.1 * creativity_score + 0.2 * expression_score,
                25.0,
                99.0,
            )
        )
        dim_sum = max(1.0, float(sum(updated_dimensions.values())))
        soft_distribution = {
            key: round(value / dim_sum, 4) for key, value in updated_dimensions.items()
        }

        strong = sum(1 for value in updated_dimensions.values() if value >= 75)
        weak = sum(1 for value in updated_dimensions.values() if value < 55)
        performance_distribution = {
            "strong": round(_clamp(strong / 4.0, 0.0, 1.0), 4),
            "developing": round(_clamp((4 - strong - weak) / 4.0, 0.0, 1.0), 4),
            "needs_support": round(_clamp(weak / 4.0, 0.0, 1.0), 4),
        }
        weakest_dimension = min(updated_dimensions, key=updated_dimensions.get)
        strongest_dimension = max(updated_dimensions, key=updated_dimensions.get)
        feedback_suffix = f"PDL判定当前优势维度为{strongest_dimension}，建议继续补强{weakest_dimension}。"

        return {
            "score": weighted_score,
            "dimensions": updated_dimensions,
            "soft_distribution": soft_distribution,
            "performance_distribution": performance_distribution,
            "strongest_dimension": strongest_dimension,
            "weakest_dimension": weakest_dimension,
            "feedback_suffix": feedback_suffix,
            "backbone": {
                "key": text_embedding["backbone"],
                "backend": text_embedding["backend"],
            },
        }


class OneShotMVGEngine:
    def __init__(self):
        self._memory: Dict[int, Dict[str, Dict]] = defaultdict(dict)

    def restore(
        self,
        meeting_id: int,
        identity_key: str,
        username: str,
        face_embedding: Optional[List[float]] = None,
        voice_embedding: Optional[List[float]] = None,
        talknet_probability: float = 0.0,
        gallery_match: Optional[Dict] = None,
    ) -> Dict:
        identity_bucket = self._memory.setdefault(meeting_id, {})
        track = identity_bucket.setdefault(
            identity_key,
            {
                "username": username,
                "face_prototype": None,
                "voice_prototype": None,
                "face_updates": 0,
                "voice_updates": 0,
                "relink_count": 0,
            },
        )
        notes: List[str] = []

        face_similarity = _cosine_similarity(face_embedding, track.get("face_prototype"))
        voice_similarity = _cosine_similarity(voice_embedding, track.get("voice_prototype"))

        weights = []
        scores = []
        if face_similarity is not None:
            weights.append(0.45)
            scores.append(face_similarity)
        if voice_similarity is not None:
            weights.append(0.35)
            scores.append(voice_similarity)
        if talknet_probability > 0:
            weights.append(0.10)
            scores.append(talknet_probability)

        gallery_identity = _safe_text((gallery_match or {}).get("identity"))
        gallery_score = 0.0
        if gallery_identity and gallery_identity == identity_key:
            gallery_score = max(0.0, float((gallery_match or {}).get("score", 0.82)))
            weights.append(0.10)
            scores.append(gallery_score)

        if not weights:
            continuity_score = 0.58
        else:
            continuity_score = sum(weight * score for weight, score in zip(weights, scores)) / max(1e-6, sum(weights))

        continuity_score = _clamp(continuity_score, 0.35, 0.98)

        if track.get("face_prototype") is None and face_embedding:
            track["face_prototype"] = _normalize_vector(face_embedding)
            track["face_updates"] = 1
            notes.append("One-Shot MVG已建立首个视觉锚点。")
        elif face_embedding and continuity_score >= 0.60:
            alpha = 0.18 if continuity_score >= 0.75 else 0.10
            track["face_prototype"] = _blend_vectors(track.get("face_prototype"), face_embedding, alpha)
            track["face_updates"] = int(track.get("face_updates", 0)) + 1

        if track.get("voice_prototype") is None and voice_embedding:
            track["voice_prototype"] = _normalize_vector(voice_embedding)
            track["voice_updates"] = 1
            notes.append("One-Shot MVG已建立首个语音锚点。")
        elif voice_embedding and continuity_score >= 0.60:
            alpha = 0.15 if continuity_score >= 0.75 else 0.08
            track["voice_prototype"] = _blend_vectors(track.get("voice_prototype"), voice_embedding, alpha)
            track["voice_updates"] = int(track.get("voice_updates", 0)) + 1

        relink_status = "initialized"
        confidence_delta = 0.0
        if continuity_score >= 0.80:
            relink_status = "stable_restored"
            track["relink_count"] = int(track.get("relink_count", 0)) + 1
            confidence_delta = 0.05
            notes.append("One-Shot MVG判定身份状态连续性较高，可用于片段重连。")
        elif continuity_score >= 0.68:
            relink_status = "soft_restored"
            confidence_delta = 0.03
            notes.append("One-Shot MVG完成渐进式状态恢复。")
        elif continuity_score <= 0.48:
            relink_status = "relink_pending_review"
            confidence_delta = -0.05
            notes.append("One-Shot MVG检测到连续性偏弱，建议保守处理身份重连。")

        return {
            "continuity_score": round(continuity_score, 4),
            "relink_status": relink_status,
            "confidence_delta": confidence_delta,
            "notes": notes,
            "prototype_state": {
                "face_updates": int(track.get("face_updates", 0)),
                "voice_updates": int(track.get("voice_updates", 0)),
                "relink_count": int(track.get("relink_count", 0)),
            },
        }


class CCMEngine:
    def match(
        self,
        identity_key: str,
        voice_cluster: Optional[Dict],
        face_cluster: Optional[Dict],
        talknet_result: Optional[Dict],
        gallery_match: Optional[Dict],
        pyannote_result: Optional[Dict],
        mvg_result: Optional[Dict],
    ) -> Dict:
        score = 0.55
        notes: List[str] = []
        conflicts: List[str] = []

        def _cluster_vote(cluster: Optional[Dict], label: str, positive: float, negative: float) -> None:
            nonlocal score
            cluster = cluster or {}
            majority_identity = _safe_text(cluster.get("majority_identity"))
            similarity = float(cluster.get("similarity", 0.0) or 0.0)
            if majority_identity and majority_identity == identity_key:
                score += positive + max(0.0, similarity - 0.7) * 0.08
                notes.append(f"CCM确认{label}聚类与当前身份一致。")
            elif majority_identity and majority_identity != identity_key:
                score -= negative
                conflicts.append(label)
                notes.append(f"CCM发现{label}聚类更接近 {majority_identity}。")

        _cluster_vote(voice_cluster, "语音", 0.12, 0.16)
        _cluster_vote(face_cluster, "视觉", 0.12, 0.16)

        gallery_identity = _safe_text((gallery_match or {}).get("identity"))
        if gallery_identity:
            if gallery_identity == identity_key:
                score += 0.12
                notes.append("CCM接收到InsightFace图库一致性支持。")
            else:
                score -= 0.18
                conflicts.append("gallery")
                notes.append(f"CCM发现图库匹配更接近 {gallery_identity}。")

        active_probability = _extract_probability(talknet_result)
        if active_probability >= 0.65:
            score += 0.06
            notes.append("CCM确认说话嘴型同步较好。")
        elif active_probability <= 0.35 and active_probability > 0:
            score -= 0.07
            conflicts.append("talknet")
            notes.append("CCM检测到画面说话同步偏弱。")

        speaker_count = int((pyannote_result or {}).get("speaker_count", 0) or 0)
        dominant_ratio = float((pyannote_result or {}).get("dominant_ratio", 0.0) or 0.0)
        if speaker_count <= 1 and dominant_ratio >= 0.75:
            score += 0.05
        elif speaker_count >= 3:
            score -= 0.05
            conflicts.append("pyannote")

        continuity_score = float((mvg_result or {}).get("continuity_score", 0.0) or 0.0)
        if continuity_score >= 0.75:
            score += 0.07
        elif continuity_score <= 0.5 and continuity_score > 0:
            score -= 0.05
            conflicts.append("mvg")

        score = _clamp(score, 0.20, 0.98)
        if score >= 0.82 and not conflicts:
            status = "enhanced_review_completed"
            binding_source = "ccm_locked_cross_modal_identity"
            confidence_delta = 0.06
        elif score >= 0.70 and len(conflicts) <= 1:
            status = "enhanced_review_completed"
            binding_source = "ccm_soft_cross_modal_identity"
            confidence_delta = 0.03
        else:
            status = "enhanced_review_warning"
            binding_source = "ccm_pending_manual_review"
            confidence_delta = -0.06 if conflicts else -0.03
            notes.append("CCM保守降级为待复核状态，避免错误绑定写入主链路。")

        return {
            "lock_score": round(score, 4),
            "confidence_delta": confidence_delta,
            "binding_source": binding_source,
            "status": status,
            "conflicts": conflicts,
            "notes": notes,
        }


class CDLEngine:
    REASONING_CUES = ("因为", "所以", "例如", "比如", "说明", "推理", "比较", "结论", "首先", "其次")

    def correct(
        self,
        text: str,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
        voice_cluster: Optional[Dict],
        face_cluster: Optional[Dict],
        talknet_result: Optional[Dict],
        pyannote_result: Optional[Dict],
        mvg_result: Optional[Dict],
        baseline_consistency: float,
    ) -> Dict:
        sentence = _safe_text(text)
        emotion = _safe_text(emotion_tag).lower()
        action = _safe_text(body_action).lower()
        tone = _safe_text(audio_tone).lower()

        semantic_strength = _clamp(0.35 + 0.45 * _cue_ratio(sentence, self.REASONING_CUES) + 0.20 * _clamp(len(sentence) / 120.0, 0.0, 1.0), 0.20, 0.98)
        emotion_alignment = 0.55
        if tone == "loud" and emotion in {"happy", "excited", "surprised"}:
            emotion_alignment = 0.88
        elif tone == "quiet" and emotion in {"calm", "thinking", "confused", "sad"}:
            emotion_alignment = 0.82
        elif tone in {"normal", "steady"}:
            emotion_alignment = 0.74

        action_alignment = 0.60 if action in {"focused", "writing", "listening", "active"} else 0.48
        active_speaker_alignment = _extract_probability(talknet_result) or 0.50
        identity_alignment = 0.62
        voice_identity = _safe_text((voice_cluster or {}).get("majority_identity"))
        face_identity = _safe_text((face_cluster or {}).get("majority_identity"))
        if voice_identity and face_identity and voice_identity == face_identity:
            identity_alignment = 0.86
        elif voice_identity and face_identity and voice_identity != face_identity:
            identity_alignment = 0.36
        elif voice_identity or face_identity:
            identity_alignment = 0.70

        continuity_score = float((mvg_result or {}).get("continuity_score", baseline_consistency) or baseline_consistency)
        diarization_ratio = float((pyannote_result or {}).get("dominant_ratio", 0.65) or 0.65)

        corrected_consistency = _clamp(
            0.22 * baseline_consistency
            + 0.18 * semantic_strength
            + 0.16 * emotion_alignment
            + 0.14 * action_alignment
            + 0.12 * active_speaker_alignment
            + 0.10 * identity_alignment
            + 0.08 * continuity_score,
            0.25,
            0.99,
        )
        participation_weight = _clamp(
            0.55 * semantic_strength + 0.25 * corrected_consistency + 0.20 * diarization_ratio,
            0.20,
            0.98,
        )

        notes: List[str] = []
        confidence_delta = 0.0
        if corrected_consistency >= 0.80:
            confidence_delta = 0.03
            notes.append("CDL确认语义、视觉与上下文证据基本一致。")
        elif corrected_consistency <= 0.52:
            confidence_delta = -0.05
            notes.append("CDL检测到跨模态冲突，已下调该条记录可信权重。")
        if participation_weight <= 0.45:
            notes.append("CDL认为该条发言更像低强度参与，建议结合后续证据复核。")

        return {
            "corrected_consistency": round(corrected_consistency, 4),
            "participation_weight": round(participation_weight, 4),
            "confidence_delta": confidence_delta,
            "notes": notes,
            "modality_weights": {
                "semantic_strength": round(semantic_strength, 4),
                "emotion_alignment": round(emotion_alignment, 4),
                "action_alignment": round(action_alignment, 4),
                "active_speaker_alignment": round(active_speaker_alignment, 4),
                "identity_alignment": round(identity_alignment, 4),
                "continuity_score": round(continuity_score, 4),
            },
        }


class CLPCRefiner:
    def __init__(self, backbones: ResearchBackboneManager, pdl: PDLScorer):
        self.backbones = backbones
        self.pdl = pdl

    def _embedding(self, text: str) -> List[float]:
        return self.backbones.encode_text(text, preferred="bge_m3")["vector"]

    def _build_seed_centers(self, viewpoints: List[Dict], items: List[Dict], topic: str) -> List[Optional[List[float]]]:
        centers: List[Optional[List[float]]] = []
        for viewpoint in viewpoints:
            supporters = {_safe_text(name) for name in viewpoint.get("supporters") or [] if _safe_text(name)}
            related_texts = [
                item["content"]
                for item in items
                if item["username"] in supporters and _safe_text(item["content"])
            ]
            seed_text = " ".join(
                part
                for part in [
                    _safe_text(viewpoint.get("title")),
                    _safe_text(viewpoint.get("description")),
                    _safe_text(topic),
                ]
                if part
            )
            vectors = [self._embedding(seed_text)] if seed_text else []
            vectors.extend(self._embedding(text) for text in related_texts[:8] if _safe_text(text))
            centers.append(_mean_vectors(vectors))
        return centers

    def _speaker_consensus(self, labels: List[int], items: List[Dict]) -> Dict[str, int]:
        speaker_votes: Dict[str, Counter] = defaultdict(Counter)
        for label, item in zip(labels, items):
            if label >= 0:
                speaker_votes[item["username"]][label] += 1
        consensus = {}
        for username, counter in speaker_votes.items():
            if not counter:
                continue
            label, count = counter.most_common(1)[0]
            if count >= 2 or count / max(1, sum(counter.values())) >= 0.6:
                consensus[username] = label
        return consensus

    def _recompute_centers(self, viewpoints: List[Dict], items: List[Dict], labels: List[int], topic: str) -> List[Optional[List[float]]]:
        centers = []
        for index, viewpoint in enumerate(viewpoints):
            texts = [
                items[item_index]["content"]
                for item_index, label in enumerate(labels)
                if label == index and _safe_text(items[item_index]["content"])
            ]
            seed_text = " ".join(
                part
                for part in [
                    _safe_text(viewpoint.get("title")),
                    _safe_text(viewpoint.get("description")),
                    _safe_text(topic),
                ]
                if part
            )
            vectors = [self._embedding(seed_text)] if seed_text else []
            vectors.extend(self._embedding(text) for text in texts[:12])
            centers.append(_mean_vectors(vectors))
        return centers

    def refine(
        self,
        all_transcripts: List[Dict],
        topic: str,
        base_result: Dict,
        deployment_profile: str,
        runtime_mode: str,
        enhanced_stack_ready: bool,
    ) -> Dict:
        result = dict(base_result or {})
        viewpoints = [dict(item) for item in (result.get("viewpoints") or [])]
        items = [
            {
                "username": _safe_text(entry.get("username")),
                "content": _safe_text(entry.get("content")),
            }
            for entry in (all_transcripts or [])
            if _safe_text(entry.get("username")) and _safe_text(entry.get("content"))
        ]
        if not viewpoints:
            result["research"] = {
                **(result.get("research") or {}),
                "algorithms": ["pdl_clpc"],
                "status": "no_viewpoints",
            }
            return result

        if not items:
            for index, viewpoint in enumerate(viewpoints, start=1):
                viewpoint["id"] = viewpoint.get("id") or index
                viewpoint["supporters"] = list(dict.fromkeys([_safe_text(name) for name in viewpoint.get("supporters") or [] if _safe_text(name)]))
                viewpoint["support_count"] = len(viewpoint["supporters"])
                viewpoint["evidence_count"] = 0
                viewpoint["refinement_stage"] = "llm_seed_only"
            result["viewpoints"] = viewpoints
            result["research"] = {
                **(result.get("research") or {}),
                "algorithms": ["pdl_clpc"],
                "status": "no_transcripts",
            }
            return result

        item_embeddings = [self._embedding(item["content"]) for item in items]
        centers = self._build_seed_centers(viewpoints, items, topic)
        labels = [-1] * len(items)
        assignment_notes: List[str] = ["unassigned"] * len(items)

        for item_index, item in enumerate(items):
            supporter_hit = None
            for view_index, viewpoint in enumerate(viewpoints):
                supporters = {_safe_text(name) for name in viewpoint.get("supporters") or [] if _safe_text(name)}
                if item["username"] in supporters:
                    supporter_hit = view_index
                    break
            if supporter_hit is not None:
                labels[item_index] = supporter_hit
                assignment_notes[item_index] = "speaker_seed"
                continue

            best_label = -1
            best_similarity = -1.0
            second_best = -1.0
            for view_index, center in enumerate(centers):
                similarity = _cosine_similarity(item_embeddings[item_index], center) or -1.0
                if similarity > best_similarity:
                    second_best = best_similarity
                    best_similarity = similarity
                    best_label = view_index
                elif similarity > second_best:
                    second_best = similarity
            if best_label >= 0 and best_similarity >= 0.52 and (best_similarity - second_best) >= 0.02:
                labels[item_index] = best_label
                assignment_notes[item_index] = "semantic_seed"

        speaker_consensus = self._speaker_consensus(labels, items)
        for item_index, item in enumerate(items):
            if labels[item_index] >= 0:
                continue
            consensus_label = speaker_consensus.get(item["username"])
            if consensus_label is None:
                continue
            similarity = _cosine_similarity(item_embeddings[item_index], centers[consensus_label]) or 0.0
            if similarity >= 0.42:
                labels[item_index] = consensus_label
                assignment_notes[item_index] = "speaker_consensus"

        centers = self._recompute_centers(viewpoints, items, labels, topic)
        for item_index, item in enumerate(items):
            if labels[item_index] >= 0:
                continue
            best_label = -1
            best_similarity = -1.0
            second_best = -1.0
            for view_index, center in enumerate(centers):
                similarity = _cosine_similarity(item_embeddings[item_index], center) or -1.0
                if similarity > best_similarity:
                    second_best = best_similarity
                    best_similarity = similarity
                    best_label = view_index
                elif similarity > second_best:
                    second_best = similarity
            if best_label >= 0 and best_similarity >= 0.48 and (best_similarity - second_best) >= 0.015:
                labels[item_index] = best_label
                assignment_notes[item_index] = "pseudo_label_mining"

        refined_viewpoints: List[Dict] = []
        labeled_count = sum(1 for label in labels if label >= 0)
        pdl_scores: List[int] = []
        for view_index, viewpoint in enumerate(viewpoints):
            cluster_items = [
                items[item_index]
                for item_index, label in enumerate(labels)
                if label == view_index
            ]
            cluster_texts = [item["content"] for item in cluster_items if _safe_text(item["content"])]
            cluster_supporters = list(dict.fromkeys([item["username"] for item in cluster_items] + [_safe_text(name) for name in viewpoint.get("supporters") or [] if _safe_text(name)]))
            avg_dimensions = {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50}
            soft_distribution = {"relevance": 0.25, "depth": 0.25, "creativity": 0.25, "expression": 0.25}
            pdl_cluster_score = 50
            if cluster_texts:
                pdl_results = [self.pdl.score(text, topic) for text in cluster_texts[:12]]
                pdl_cluster_score = round(sum(item["score"] for item in pdl_results) / len(pdl_results))
                pdl_scores.append(pdl_cluster_score)
                for key in avg_dimensions:
                    avg_dimensions[key] = round(sum(item["dimensions"][key] for item in pdl_results) / len(pdl_results))
                    soft_distribution[key] = round(sum(item["soft_distribution"][key] for item in pdl_results) / len(pdl_results), 4)

            cluster_confidence = 0.0
            if cluster_items and centers[view_index]:
                similarities = [
                    _cosine_similarity(item_embeddings[item_index], centers[view_index]) or 0.0
                    for item_index, label in enumerate(labels)
                    if label == view_index
                ]
                if similarities:
                    cluster_confidence = round(sum(similarities) / len(similarities), 4)

            merged = dict(viewpoint)
            merged["id"] = merged.get("id") or (view_index + 1)
            merged["supporters"] = cluster_supporters
            merged["support_count"] = len(cluster_supporters)
            merged["evidence_count"] = len(cluster_items)
            merged["keywords"] = _extract_keywords(cluster_texts + [_safe_text(merged.get("title")), _safe_text(merged.get("description"))])
            merged["cluster_confidence"] = cluster_confidence
            merged["pseudo_label_support"] = sum(1 for label, note in zip(labels, assignment_notes) if label == view_index and note == "pseudo_label_mining")
            merged["speaker_consensus_support"] = sum(1 for label, note in zip(labels, assignment_notes) if label == view_index and note == "speaker_consensus")
            merged["pdl_cluster_score"] = pdl_cluster_score
            merged["pdl_dimensions"] = avg_dimensions
            merged["pdl_distribution"] = soft_distribution
            merged["refinement_stage"] = "llm_seed_bge_clpc_refined"
            refined_viewpoints.append(merged)

        refined_viewpoints.sort(key=lambda item: (item.get("support_count", 0), item.get("evidence_count", 0), item.get("cluster_confidence", 0.0)), reverse=True)
        result["viewpoints"] = refined_viewpoints
        result["research"] = {
            **(result.get("research") or {}),
            "status": "pdl_clpc_refined",
            "deployment_profile": deployment_profile,
            "runtime_mode": runtime_mode,
            "enhanced_stack_ready": enhanced_stack_ready,
            "algorithms": ["pdl_clpc"],
            "backbones": self.backbones.get_backbone_status(),
            "pseudo_labeling": {
                "labeled_items": labeled_count,
                "total_items": len(items),
                "speaker_consensus_count": len(speaker_consensus),
                "unassigned_items": len(items) - labeled_count,
            },
            "soft_label_distribution": {
                "average_cluster_score": round(sum(pdl_scores) / len(pdl_scores), 2) if pdl_scores else 50.0,
                "cluster_count": len(refined_viewpoints),
            },
            "pipeline": [
                "LLM seed viewpoints",
                "BGE/hash text embedding",
                "speaker prior assignment",
                "CLPC-style pseudo label refinement",
                "PDL cluster distribution scoring",
            ],
        }
        return result


class IPAEngine:
    REASONING_CUES = ("因为", "所以", "例如", "比如", "总结", "结论", "先", "再", "如果")

    def build_profiles(
        self,
        meeting_topic: str,
        all_transcripts: List[Dict],
        student_performances: List[Dict],
        emotion_stats: Dict,
        course_report: Optional[Dict] = None,
    ) -> Dict:
        course_report = course_report or {}
        grouped_texts: Dict[str, List[str]] = defaultdict(list)
        for item in all_transcripts or []:
            username = _safe_text(item.get("username"))
            content = _safe_text(item.get("content"))
            if username and content:
                grouped_texts[username].append(content)

        performance_map = {
            _safe_text(item.get("username")): dict(item)
            for item in (student_performances or [])
            if _safe_text(item.get("username"))
        }
        viewpoint_support: Dict[str, int] = defaultdict(int)
        for viewpoint in course_report.get("viewpoints") or []:
            for supporter in viewpoint.get("supporters") or []:
                username = _safe_text(supporter)
                if username:
                    viewpoint_support[username] += 1

        usernames = sorted(set(grouped_texts) | set(performance_map))
        speech_counts = [len(grouped_texts.get(username, [])) for username in usernames] or [0]
        avg_speech_count = sum(speech_counts) / max(1, len(speech_counts))

        profiles = []
        for username in usernames:
            texts = grouped_texts.get(username, [])
            performance = performance_map.get(username, {})
            speech_count = int(performance.get("speech_count", len(texts)))
            avg_relevance = float(performance.get("avg_relevance", 50.0))
            avg_length = (sum(len(text) for text in texts) / len(texts)) if texts else 0.0
            reasoning = (
                sum(_cue_ratio(text, self.REASONING_CUES) for text in texts) / len(texts)
                if texts
                else 0.0
            )
            question_ratio = (
                sum(1 for text in texts if any(token in text for token in ("?", "？", "为什么", "如何", "是否"))) / len(texts)
                if texts
                else 0.0
            )
            viewpoint_hits = viewpoint_support.get(username, 0)

            participation_score = _clamp(0.55 + 0.15 * (speech_count / max(1.0, avg_speech_count)) + 0.15 * reasoning + 0.10 * (avg_relevance / 100.0) + 0.05 * min(1.0, viewpoint_hits / 2.0), 0.20, 0.99)
            ipa_score = round(participation_score * 100)

            diagnostic_tags: List[str] = []
            if speech_count <= max(1, int(avg_speech_count * 0.5)):
                diagnostic_tags.append("参与偏少")
            if reasoning >= 0.35:
                diagnostic_tags.append("论证较强")
            if avg_length >= 30:
                diagnostic_tags.append("表达较完整")
            if avg_relevance < 45:
                diagnostic_tags.append("主题聚焦待加强")
            if viewpoint_hits >= 1:
                diagnostic_tags.append("观点构建积极")
            if not diagnostic_tags:
                diagnostic_tags.append("状态平稳")

            if speech_count == 0:
                diagnosis = "课堂中几乎没有有效发言，当前更接近旁听型参与。"
                suggestion = "建议从复述同伴观点、回答小问题开始，逐步增加有效表达次数。"
            elif "主题聚焦待加强" in diagnostic_tags:
                diagnosis = "具备参与意愿，但发言与课堂目标之间的对齐度仍需提升。"
                suggestion = "建议先围绕课堂主题复述关键概念，再补充自己的理由和例子。"
            elif "参与偏少" in diagnostic_tags:
                diagnosis = "发言质量基本可用，但参与频次仍偏低，容易被群体讨论边缘化。"
                suggestion = "建议在每轮讨论至少主动发起一次回应，形成稳定参与节奏。"
            else:
                diagnosis = "整体表现较稳定，已经能够围绕主题进行较完整表达。"
                suggestion = "建议继续提升论证深度，把观点进一步转化为可验证的证据和案例。"

            profiles.append(
                {
                    "student_name": username,
                    "ipa_score": ipa_score,
                    "speech_count": speech_count,
                    "avg_relevance": round(avg_relevance, 2),
                    "avg_length": round(avg_length, 2),
                    "reasoning_ratio": round(reasoning, 4),
                    "question_ratio": round(question_ratio, 4),
                    "viewpoint_support_count": viewpoint_hits,
                    "diagnostic_tags": diagnostic_tags,
                    "diagnosis": diagnosis,
                    "suggestion": suggestion,
                }
            )

        emotion_summary = {
            "dominant_emotion": "",
            "emotion_total": int(sum((emotion_stats or {}).values())) if emotion_stats else 0,
        }
        if emotion_stats:
            emotion_summary["dominant_emotion"] = max(emotion_stats, key=emotion_stats.get)

        return {
            "profiles": profiles,
            "class_summary": {
                "meeting_topic": _safe_text(meeting_topic),
                "average_ipa_score": round(sum(item["ipa_score"] for item in profiles) / len(profiles), 2) if profiles else 0.0,
                "emotion_summary": emotion_summary,
            },
        }


class ResearchAlgorithmFusion:
    def __init__(self, model_root: Path):
        self.model_root = Path(model_root)
        self.backbones = ResearchBackboneManager(self.model_root)
        self.pdl = PDLScorer(self.backbones)
        self.one_shot_mvg = OneShotMVGEngine()
        self.ccm = CCMEngine()
        self.cdl = CDLEngine()
        self.clpc = CLPCRefiner(self.backbones, self.pdl)
        self.ipa = IPAEngine()

    def get_runtime_status(self) -> Dict:
        return {
            "algorithms": {
                "one_shot_mvg": "runtime_adapted",
                "ccm": "runtime_adapted",
                "cdl": "runtime_adapted",
                "pdl_clpc": "runtime_adapted",
                "ipa": "runtime_adapted",
            },
            "backbones": self.backbones.get_backbone_status(),
        }

    def apply_pdl(
        self,
        text: str,
        topic: str,
        base_dimensions: Optional[Dict],
        base_score: float,
        relevance: float,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
        quality_feedback: str,
    ) -> Dict:
        result = self.pdl.score(
            text=text,
            topic=topic,
            base_dimensions=base_dimensions,
            base_score=base_score,
            relevance=relevance,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
        )
        feedback_parts = [_safe_text(quality_feedback), result["feedback_suffix"]]
        return {
            "score": result["score"],
            "dimensions": result["dimensions"],
            "quality_feedback": " ".join(part for part in feedback_parts if part),
            "soft_distribution": result["soft_distribution"],
            "performance_distribution": result["performance_distribution"],
            "research": {
                "algorithm": "PDL",
                "backbone": result["backbone"],
                "strongest_dimension": result["strongest_dimension"],
                "weakest_dimension": result["weakest_dimension"],
            },
        }

    def apply_identity_algorithms(
        self,
        meeting_id: int,
        identity_key: str,
        username: str,
        text: str,
        emotion_tag: str,
        body_action: str,
        audio_tone: str,
        voice_embedding: Optional[List[float]],
        face_embedding: Optional[List[float]],
        voice_cluster: Optional[Dict],
        face_cluster: Optional[Dict],
        pyannote_result: Optional[Dict],
        talknet_result: Optional[Dict],
        gallery_match: Optional[Dict],
        baseline_consistency: float,
    ) -> Dict:
        mvg_result = self.one_shot_mvg.restore(
            meeting_id=meeting_id,
            identity_key=identity_key,
            username=username,
            face_embedding=face_embedding,
            voice_embedding=voice_embedding,
            talknet_probability=_extract_probability(talknet_result),
            gallery_match=gallery_match,
        )
        ccm_result = self.ccm.match(
            identity_key=identity_key,
            voice_cluster=voice_cluster,
            face_cluster=face_cluster,
            talknet_result=talknet_result,
            gallery_match=gallery_match,
            pyannote_result=pyannote_result,
            mvg_result=mvg_result,
        )
        cdl_result = self.cdl.correct(
            text=text,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
            voice_cluster=voice_cluster,
            face_cluster=face_cluster,
            talknet_result=talknet_result,
            pyannote_result=pyannote_result,
            mvg_result=mvg_result,
            baseline_consistency=baseline_consistency,
        )

        return {
            "confidence_delta": round(
                float(mvg_result.get("confidence_delta", 0.0))
                + float(ccm_result.get("confidence_delta", 0.0))
                + float(cdl_result.get("confidence_delta", 0.0)),
                4,
            ),
            "binding_source": ccm_result.get("binding_source", "ccm_pending_manual_review"),
            "status": ccm_result.get("status", "enhanced_review_warning"),
            "consistency_override": cdl_result.get("corrected_consistency", baseline_consistency),
            "notes": list(mvg_result.get("notes", [])) + list(ccm_result.get("notes", [])) + list(cdl_result.get("notes", [])),
            "algorithm_outputs": {
                "one_shot_mvg": mvg_result,
                "ccm": ccm_result,
                "cdl": cdl_result,
            },
        }

    def refine_viewpoints(
        self,
        all_transcripts: List[Dict],
        topic: str,
        base_result: Dict,
        deployment_profile: str,
        runtime_mode: str,
        enhanced_stack_ready: bool,
    ) -> Dict:
        return self.clpc.refine(
            all_transcripts=all_transcripts,
            topic=topic,
            base_result=base_result,
            deployment_profile=deployment_profile,
            runtime_mode=runtime_mode,
            enhanced_stack_ready=enhanced_stack_ready,
        )

    def enrich_course_report(
        self,
        meeting_topic: str,
        all_transcripts: List[Dict],
        student_performances: List[Dict],
        emotion_stats: Dict,
        course_report: Dict,
    ) -> Dict:
        report = dict(course_report or {})
        ipa_result = self.ipa.build_profiles(
            meeting_topic=meeting_topic,
            all_transcripts=all_transcripts,
            student_performances=student_performances,
            emotion_stats=emotion_stats,
            course_report=report,
        )
        profile_map = {item["student_name"]: item for item in ipa_result.get("profiles", [])}
        enriched_reviews = []
        for review in report.get("student_reviews") or []:
            merged = dict(review)
            student_name = _safe_text(merged.get("student_name"))
            profile = profile_map.get(student_name)
            if profile:
                merged["ipa_profile"] = profile
                merged["diagnostic_tags"] = profile.get("diagnostic_tags", [])
                merged["suggestions"] = _safe_text(merged.get("suggestions")) or profile.get("suggestion", "")
            enriched_reviews.append(merged)
        report["student_reviews"] = enriched_reviews
        research_block = dict(report.get("research") or {})
        research_block.update(
            {
                "ipa_profiles": ipa_result.get("profiles", []),
                "ipa_class_summary": ipa_result.get("class_summary", {}),
                "algorithm_runtime": self.get_runtime_status(),
            }
        )
        report["research"] = research_block
        return report
