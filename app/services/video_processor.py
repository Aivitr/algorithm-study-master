import cv2
import numpy as np
from pathlib import Path

from app.core.paths import PROJECT_ROOT
import threading


def _extract_face_features_from_mediapipe(face_rgb, face_mesh_result):
    """
    从 MediaPipe 结果中提取面部特征

    Returns:
        dict: {mouth_open, smile_lift, brow_raise, eye_open}
    """
    import numpy as np

    if face_mesh_result is None or not getattr(face_mesh_result, "multi_face_landmarks", None):
        return None

    lm = face_mesh_result.multi_face_landmarks[0].landmark
    h, w = face_rgb.shape[:2] if len(face_rgb.shape) == 3 else (100, 100)

    def pt(i):
        p = lm[i]
        return p.x * w, p.y * h

    def dist(a, b):
        return float(np.hypot(a[0] - b[0], a[1] - b[1]))

    # 嘴巴特征
    mouth_top = pt(13)
    mouth_bottom = pt(14)
    mouth_left = pt(61)
    mouth_right = pt(291)
    mouth_center = ((mouth_left[0] + mouth_right[0]) / 2.0, (mouth_left[1] + mouth_right[1]) / 2.0)

    mouth_width = max(1e-6, dist(mouth_left, mouth_right))
    mouth_open = dist(mouth_top, mouth_bottom) / mouth_width
    smile_lift = (mouth_center[1] - mouth_left[1] + mouth_center[1] - mouth_right[1]) / max(1.0, h)

    # 眉毛特征
    left_brow = pt(65)
    right_brow = pt(295)
    left_eye_upper = pt(159)
    right_eye_upper = pt(386)
    brow_raise = ((left_eye_upper[1] - left_brow[1]) + (right_eye_upper[1] - right_brow[1])) / max(1.0, h)

    # 眼睛特征
    left_eye_top = pt(160)
    left_eye_bottom = pt(158)
    right_eye_top = pt(385)
    right_eye_bottom = pt(387)

    left_eye_open = dist(left_eye_top, left_eye_bottom) / max(1e-6, mouth_width)
    right_eye_open = dist(right_eye_top, right_eye_bottom) / max(1e-6, mouth_width)
    eye_open = (left_eye_open + right_eye_open) / 2.0

    # 归一化处理
    features = {
        "mouth_open": min(1.0, max(0.0, mouth_open * 2)),  # 0-1
        "smile_lift": max(-1.0, min(1.0, smile_lift * 50)),  # -1 to 1
        "brow_raise": max(0.0, min(1.0, brow_raise * 30)),  # 0-1
        "eye_open": max(0.0, min(1.0, eye_open * 3))  # 0-1
    }

    return features


def _extract_simple_face_features(face_roi_bgr, face_roi_gray):
    """
    使用 OpenCV 简单特征提取（备用方案，当 MediaPipe 不可用时）

    Returns:
        dict: {mouth_open, smile_lift, brow_raise, eye_open}
    """
    if face_roi_bgr is None or face_roi_bgr.size == 0:
        return None

    h, w = face_roi_bgr.shape[:2]
    if h <= 0 or w <= 0:
        return None

    try:
        # 转换为灰度和 HSV
        gray = face_roi_gray if face_roi_gray is not None else cv2.cvtColor(face_roi_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(face_roi_bgr, cv2.COLOR_BGR2HSV)

        # 分割人脸区域（粗略估算）
        # 眼睛区域：上部 1/4
        # 嘴巴区域：下部 1/4

        eye_region = gray[0:h//3, :]
        mouth_region = gray[2*h//3:, :]
        upper_region = gray[0:h//2, :]
        lower_region = gray[h//2:, :]

        # 计算嘴巴张开程度（使用下1/3区域的亮度变化）
        mouth_edges = cv2.Canny(mouth_region, 50, 150)
        mouth_edge_ratio = np.sum(mouth_edges) / (max(1, mouth_region.shape[0] * mouth_region.shape[1]) * 255)

        # 简单嘴巴张开估算
        mouth_open = min(1.0, mouth_edge_ratio * 10)

        # 计算微笑上扬（比较上下半部分的平均亮度）
        upper_brightness = np.mean(upper_region) / 255.0
        lower_brightness = np.mean(lower_region) / 255.0
        smile_lift = (lower_brightness - upper_brightness) * 2  # -1 到 1

        # 眉毛抬高（使用上1/3区域的边缘密度）
        brow_edges = cv2.Canny(eye_region, 50, 150)
        brow_edge_ratio = np.sum(brow_edges) / (max(1, eye_region.shape[0] * eye_region.shape[1]) * 255)
        brow_raise = min(1.0, brow_edge_ratio * 15)

        # 眼睛睁开程度（使用中1/3区域）
        eye_mid_region = gray[h//4:2*h//4, :]
        eye_brightness = np.mean(eye_mid_region) / 255.0
        eye_open = eye_brightness * 1.5  # 归一化

        features = {
            "mouth_open": max(0.0, min(1.0, mouth_open)),
            "smile_lift": max(-1.0, min(1.0, smile_lift)),
            "brow_raise": max(0.0, min(1.0, brow_raise)),
            "eye_open": max(0.0, min(1.0, eye_open))
        }

        return features
    except Exception as e:
        print(f"[DEBUG] 简单特征提取失败: {e}")
        return None


class VideoEmotionAnalyzer:
    def __init__(self):
        cascade = cv2.CascadeClassifier()
        cascade_path = None

        candidates = []
        # 1) 项目内兜底（仓库已内置 xml 时优先可用）
        #    锚点取自 app/core/paths.py，不用 `Path(__file__)` 推导：本文件在
        #    app/services/ 下，`__file__` 的父目录找不到仓库根的 xml。
        try:
            candidates.append(PROJECT_ROOT / "haarcascade_frontalface_default.xml")
        except Exception:
            pass

        haar_dir = getattr(getattr(cv2, "data", None), "haarcascades", None)
        if haar_dir:
            candidates.append(Path(haar_dir) / "haarcascade_frontalface_default.xml")

        try:
            cv2_file = Path(cv2.__file__).resolve()
            candidates.append(cv2_file.parent / "data" / "haarcascade_frontalface_default.xml")
            candidates.append(cv2_file.parent / "data" / "haarcascades" / "haarcascade_frontalface_default.xml")
        except Exception:
            pass

        for p in candidates:
            try:
                if p and p.exists():
                    c = cv2.CascadeClassifier(str(p))
                    if not c.empty():
                        cascade = c
                        cascade_path = str(p)
                        break
            except Exception:
                continue

        if cascade.empty():
            print("[WARN] OpenCV haarcascade 未加载成功，将跳过人脸/情绪识别")
        else:
            print(f"[OK] OpenCV haarcascade loaded: {cascade_path}")

        self.face_cascade = cascade
        self.prev_gray = None  # [EMOJI]
        self._ai_pipeline = None
        self._ai_error = None
        self._ai_lock = threading.Lock()
        self._mp_face_mesh = None
        self._mp_error = None

        # Gemma 客户端初始化
        self._gemma_client = None
        self._gemma_enabled = False
        self._gemma_lock = threading.Lock()

        t = threading.Thread(target=self._load_ai_pipeline, daemon=True)
        t.start()

    def _init_gemma(self):
        """延迟初始化 Gemma 客户端"""
        with self._gemma_lock:
            if self._gemma_client is not None:
                return

            try:
                from app.services.gemma_emotion_client import get_gemma_client
                self._gemma_client = get_gemma_client()
                if self._gemma_client is not None:
                    self._gemma_enabled = True
                    print("[OK] Gemma 4 情绪识别已启用")
                else:
                    print("[WARN] Gemma 客户端连接失败，将使用原有方案")
            except ImportError:
                print("[WARN] gemma_emotion_client 模块未找到，跳过 Gemma")
            except Exception as e:
                print(f"[WARN] Gemma 初始化失败: {e}")

    def _load_ai_pipeline(self):
        try:
            from modelscope.pipelines import pipeline as ms_pipeline
            try:
                from modelscope.utils.constant import Tasks
                task = getattr(Tasks, "facial_expression_recognition", "facial-expression-recognition")
            except Exception:
                task = "facial-expression-recognition"
            p = ms_pipeline(task=task, model="damo/cv_vgg19_facial-expression-recognition_fer")
            with self._ai_lock:
                self._ai_pipeline = p
        except Exception as e:
            with self._ai_lock:
                self._ai_error = e
            print(f"[ERROR] AI pipeline 加载失败: {e}")

    def _ensure_mediapipe(self):
        if self._mp_face_mesh is not None or self._mp_error is not None:
            return
        try:
            import mediapipe as mp
            print("[DEBUG] MediaPipe 模块已导入，正在初始化 FaceMesh...")
            self._mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            print("[DEBUG] MediaPipe FaceMesh 初始化成功!")
        except ImportError as e:
            self._mp_error = e
            print(f"[WARN] MediaPipe 未安装: {e}")
        except Exception as e:
            self._mp_error = e
            print(f"[WARN] MediaPipe 初始化失败: {e}")

    def _map_ai_label(self, label: str) -> str:
        if label is None:
            return "neutral"
        if isinstance(label, (int, np.integer)):
            idx = int(label)
            order = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]
            if 0 <= idx < len(order):
                label = order[idx]
        k = str(label).strip().lower().replace(" ", "_").replace("-", "_")
        if k.isdigit():
            try:
                idx = int(k)
                order = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]
                if 0 <= idx < len(order):
                    k = order[idx]
            except Exception:
                pass
        mapping = {
            "happy": "happy",
            "happiness": "happy",
            "neutral": "neutral",
            "sad": "sad",
            "sadness": "sad",
            "angry": "angry",
            "anger": "angry",
            "surprise": "surprised",
            "surprised": "surprised",
            "fear": "confused",
            "disgust": "confused",
            "contempt": "confused",
        }
        mapped = mapping.get(k)
        if mapped:
            return mapped
        # 如果未知情绪，尽量保留原标签，而不是直接置 neutral
        if k:
            return k
        return "neutral"

    def _parse_ai_output(self, result):
        if result is None:
            return None, 0.0
        # modelscope 有时返回 {"output": [...]} / {"output": {"label":..., "score":...}}
        if isinstance(result, dict):
            out = result.get("output") or result.get("outputs")
            if out is not None:
                return self._parse_ai_output(out)

            labels = result.get("labels") or result.get("label") or result.get("classes")
            scores = result.get("scores") or result.get("score") or result.get("probs")
            if isinstance(scores, dict) and scores:
                pairs = [(k, v) for k, v in scores.items()]
                pairs.sort(key=lambda x: float(x[1] or 0), reverse=True)
                return pairs[0][0], float(pairs[0][1] or 0)
            if isinstance(labels, list) and labels:
                if isinstance(scores, list) and scores:
                    pairs = list(zip(labels, scores))
                    pairs.sort(key=lambda x: float(x[1] or 0), reverse=True)
                    return pairs[0][0], float(pairs[0][1] or 0)
                return labels[0], float(scores[0] or 0) if isinstance(scores, list) and scores else 0.0
            if isinstance(labels, str):
                try:
                    return labels, float(scores or 0)
                except Exception:
                    return labels, 0.0
            # 下探直接转 label/score
            if "label" in result or "score" in result:
                label = result.get("label") or result.get("labels")
                score = result.get("score") or result.get("scores") or 0.0
                try:
                    return label, float(score or 0)
                except Exception:
                    return label, 0.0

        if isinstance(result, list) and result:
            top = result[0]
            if isinstance(top, dict):
                label = top.get("label") or top.get("labels")
                score = top.get("score") or top.get("scores")
                try:
                    return label, float(score or 0)
                except Exception:
                    return label, 0.0
        if isinstance(result, tuple) and len(result) >= 2:
            try:
                return result[0], float(result[1] or 0)
            except Exception:
                return result[0], 0.0
        return None, 0.0

    def _basic_emotion_from_gray_face(self, face_roi_gray, w: int, h: int):
        edges = cv2.Canny(face_roi_gray, 100, 200)
        edge_ratio = np.sum(edges) / (max(1, w) * max(1, h))
        brightness = float(np.mean(face_roi_gray)) if face_roi_gray.size else 0.0

        upper_half = face_roi_gray[0:h // 2, :]
        lower_half = face_roi_gray[h // 2:, :]
        upper_edges = cv2.Canny(upper_half, 100, 200) if upper_half.size else np.array([])
        lower_edges = cv2.Canny(lower_half, 100, 200) if lower_half.size else np.array([])
        upper_ratio = np.sum(upper_edges) / max(1, upper_half.shape[0] * upper_half.shape[1]) if upper_half.size else 0.0
        lower_ratio = np.sum(lower_edges) / max(1, lower_half.shape[0] * lower_half.shape[1]) if lower_half.size else 0.0

        emotion = "neutral"
        score = 0.5

        if edge_ratio > 20:
            emotion = "excited"
            score = 0.95
        elif edge_ratio > 15:
            if brightness > 120:
                emotion = "happy"
                score = 0.85
            else:
                emotion = "surprised"
                score = 0.8
        elif edge_ratio > 10:
            if lower_ratio > upper_ratio * 1.2:
                emotion = "happy"
                score = 0.75
            else:
                emotion = "confused"
                score = 0.65
        elif edge_ratio > 6:
            if upper_ratio > lower_ratio * 1.1:
                emotion = "angry"
                score = 0.6
            else:
                emotion = "thinking"
                score = 0.5
        elif edge_ratio > 3:
            if brightness < 100:
                emotion = "sad"
                score = 0.4
            elif lower_ratio > upper_ratio:
                emotion = "happy"
                score = 0.45
            else:
                emotion = "calm"
                score = 0.45
        else:
            emotion = "neutral"
            score = 0.3

        return emotion, score

    def _mediapipe_refine(self, face_rgb):
        self._ensure_mediapipe()
        if self._mp_face_mesh is None:
            return None, 0.0
        h, w = face_rgb.shape[:2]
        if h <= 0 or w <= 0:
            return None, 0.0
        try:
            res = self._mp_face_mesh.process(face_rgb)
        except Exception:
            return None, 0.0
        if not getattr(res, "multi_face_landmarks", None):
            return None, 0.0
        lm = res.multi_face_landmarks[0].landmark

        def pt(i):
            p = lm[i]
            return p.x * w, p.y * h

        def dist(a, b):
            return float(np.hypot(a[0] - b[0], a[1] - b[1]))

        mouth_top = pt(13)
        mouth_bottom = pt(14)
        mouth_left = pt(61)
        mouth_right = pt(291)
        mouth_center = ((mouth_left[0] + mouth_right[0]) / 2.0, (mouth_left[1] + mouth_right[1]) / 2.0)

        mouth_width = max(1e-6, dist(mouth_left, mouth_right))
        mouth_open = dist(mouth_top, mouth_bottom) / mouth_width
        smile_lift = (mouth_center[1] - mouth_left[1] + mouth_center[1] - mouth_right[1]) / max(1.0, h)

        left_brow = pt(65)
        right_brow = pt(295)
        left_eye_upper = pt(159)
        right_eye_upper = pt(386)
        brow_to_eye = ((left_eye_upper[1] - left_brow[1]) + (right_eye_upper[1] - right_brow[1])) / max(1.0, h)

        # 阈值偏低，使检测更敏感
        if smile_lift > 0.01 and mouth_open < 0.18:  # 笑脸：嘴角上扬且嘴巴不太张开
            return "happy", 0.75
        if mouth_open > 0.15:  # 惊讶：嘴巴张开
            return "surprised", 0.72
        if brow_to_eye < 0.015:  # 生气：眉毛压低
            return "angry", 0.68
        if mouth_open > 0.08 and smile_lift < -0.005:  # 悲伤：嘴角下垂且微张
            return "sad", 0.65
        return None, 0.0

    def detect_emotion(self, frame):
        """[EMOJI] 情绪识别 - Gemma 4 优先方案"""
        if frame is None: return None, 0.0, None
        if self.face_cascade is None or self.face_cascade.empty():
            return None, 0.0, None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
        if len(faces) == 0: return None, 0.0, None

        (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
        face_roi_gray = gray[y:y + h, x:x + w]

        pad = int(max(w, h) * 0.18)
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(frame.shape[1], x + w + pad)
        y2 = min(frame.shape[0], y + h + pad)
        face_roi_bgr = frame[y1:y2, x1:x2]

        face_rgb = None
        if face_roi_bgr is not None and face_roi_bgr.size:
            face_rgb = cv2.cvtColor(face_roi_bgr, cv2.COLOR_BGR2RGB)

        # ========== 优先级 1: Gemma 4 ==========
        gemma_result = self._try_gemma_analysis(face_rgb, face_roi_gray, face_roi_bgr)
        if gemma_result:
            print(f"[Emotion] Gemma: {gemma_result[0]} ({gemma_result[1]:.2f})")
            return gemma_result[0], gemma_result[1], (x, y, w, h)

        # ========== 优先级 2: ModelScope ==========
        ai_pipeline = None
        with self._ai_lock:
            ai_pipeline = self._ai_pipeline

        if ai_pipeline is not None and face_rgb is not None:
            try:
                out = None
                try:
                    out = ai_pipeline(face_rgb)
                except Exception:
                    try:
                        from PIL import Image
                        out = ai_pipeline(Image.fromarray(face_rgb))
                    except Exception:
                        out = ai_pipeline(face_roi_bgr)

                label, score = self._parse_ai_output(out)
                emotion = self._map_ai_label(label)
                score = float(score or 0.0)

                # 置信度阈值 0.35，让更多情绪能通过
                if emotion and score > 0.35:
                    if emotion in ("neutral", "calm") and face_rgb is not None:
                        refined, r_score = self._mediapipe_refine(face_rgb)
                        if refined:
                            print(f"[Emotion] MediaPipe override: {refined} ({r_score:.2f})")
                            return refined, float(r_score or 0.0), (x, y, w, h)
                    print(f"[Emotion] ModelScope: {emotion} ({score:.2f})")
                    return emotion, score, (x, y, w, h)

                # ModelScope 低置信度时，尝试 MediaPipe 精细化
                refined, r_score = self._mediapipe_refine(face_rgb)
                if refined:
                    print(f"[Emotion] MediaPipe: {refined} ({r_score:.2f})")
                    return refined, float(r_score or 0.0), (x, y, w, h)

            except Exception:
                pass

        # ========== 优先级 3: OpenCV 启发式 ==========
        if face_rgb is not None:
            refined, r_score = self._mediapipe_refine(face_rgb)
            if refined:
                print(f"[Emotion] MediaPipe: {refined} ({r_score:.2f})")
                return refined, float(r_score or 0.0), (x, y, w, h)

        base_emotion, base_score = self._basic_emotion_from_gray_face(face_roi_gray, w, h)
        print(f"[Emotion] OpenCV Fallback: {base_emotion} ({base_score:.2f})")
        return base_emotion, float(base_score), (x, y, w, h)

    def _try_gemma_analysis(self, face_rgb, face_roi_gray=None, face_roi_bgr=None):
        """
        尝试使用 Gemma 进行情绪分析

        Returns:
            (emotion, confidence) 或 None（失败时）
        """
        # 延迟初始化 Gemma
        if self._gemma_client is None:
            print("[DEBUG] 正在初始化 Gemma...")
            self._init_gemma()
            print(f"[DEBUG] Gemma 初始化完成: enabled={self._gemma_enabled}")

        if not self._gemma_enabled or self._gemma_client is None:
            print("[DEBUG] Gemma 未启用或客户端为空")
            return None

        if face_rgb is None:
            print("[DEBUG] face_rgb 为空，跳过 Gemma 分析")
            return None

        features = None

        try:
            # 优先使用 MediaPipe
            self._ensure_mediapipe()
            if self._mp_face_mesh is not None:
                # 使用 MediaPipe 提取特征
                mp_result = self._mp_face_mesh.process(face_rgb)
                if getattr(mp_result, "multi_face_landmarks", None):
                    print("[DEBUG] MediaPipe 检测到人脸，开始提取特征...")
                    features = _extract_face_features_from_mediapipe(face_rgb, mp_result)
                    if features:
                        print(f"[DEBUG] MediaPipe 特征提取成功: {features}")

            # 如果 MediaPipe 失败，使用简单特征提取
            if features is None:
                print("[DEBUG] 使用 OpenCV 简单特征提取...")
                features = _extract_simple_face_features(face_roi_bgr, face_roi_gray)
                if features:
                    print(f"[DEBUG] 简单特征提取成功: {features}")
                else:
                    print("[DEBUG] 特征提取失败")
                    return None

            # 调用 Gemma 分析
            print("[DEBUG] 正在调用 Gemma...")
            emotion, confidence = self._gemma_client.analyze_emotion(features)
            if emotion and confidence > 0.3:
                print(f"[GemmaEmotion] 分析结果: {emotion} (置信度: {confidence:.2f})")
                return emotion, confidence
            else:
                print(f"[DEBUG] Gemma 返回无效结果: emotion={emotion}, confidence={confidence}")

        except Exception as e:
            print(f"[GemmaEmotion] 分析失败: {e}")
            import traceback
            traceback.print_exc()

        return None

    def detect_body_movement(self, frame):
        """
        [EMOJI] ([EMOJI])
        [EMOJI]: movement_level (0.0 - 1.0), description
        """
        if frame is None or frame.size == 0:
            return 0.0, "static"
            
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        movement_score = 0.0
        desc = "static"

        if self.prev_gray is not None:
            # [EMOJI]
            if self.prev_gray.shape != gray.shape:
                # [EMOJI],[EMOJI]
                self.prev_gray = gray
                return 0.0, "static"
            
            # [EMOJI]
            delta_frame = cv2.absdiff(self.prev_gray, gray)
            thresh = cv2.threshold(delta_frame, 25, 255, cv2.THRESH_BINARY)[1]

            # [EMOJI]
            movement_score = np.sum(thresh) / (frame.shape[0] * frame.shape[1] * 255)
            # [EMOJI]
            movement_score = min(movement_score * 10, 1.0)

        self.prev_gray = gray

        if movement_score > 0.3:
            desc = "high_activity"  # [EMOJI]
        elif movement_score > 0.1:
            desc = "normal_gesture"  # [EMOJI]
        else:
            desc = "calm"

        return movement_score, desc
