"""实时链路里的情绪/画面判定辅助。

这里放的是**纯判定**：给一段标签、一段音频或一帧画面，判断"这是什么情绪"。

    get_analyzer()                  惰性建一次画面分析器（内部缓存，见下）
    map_silent_emotion(label)       静音时段的标签归一
    map_speaking_emotion(label)     说话时段的标签归一
    is_speaking(...)                音量/静音判据
    analyze_audio_tone(...)         从 wav 读音量包络
    _emotion_selection_key / _body_action_key / _detect_visual_state_from_video
                                    画面侧的状态判定

`get_analyzer()` 用 `global analyzer` 做惰性单例缓存，`analyzer` 必须与它同在本
模块——拆开不会报错，只会每次重新建分析器、缓存永远不生效。

本模块不含跨模块共享状态。
"""

import wave

import numpy as np

analyzer = None

def get_analyzer():
    """🔊 analyzer🔊"""
    global analyzer
    if analyzer is None:
        from app.services.video_processor import VideoEmotionAnalyzer
        analyzer = VideoEmotionAnalyzer()
    return analyzer


# 再导出 app/services/user_lookup.py 的 resolve_user_by_identifier（调用点保持不变）。
# 它被实时链路、情绪统计、快照三块共用，不能只跟着其中一块走。
from app.services.user_lookup import resolve_user_by_identifier


# 再导出 app/core/emotions.py 的 normalize_emotion_label（调用点保持不变）。
# 它横跨实时链路、报告生成、情绪统计多个域，必须只有一份实现。
from app.core.emotions import normalize_emotion_label




def map_silent_emotion(face_emotion: str) -> str:
    e = normalize_emotion_label(face_emotion)
    if e in ("happy", "excited", "surprised"):
        return "happy"
    if e in ("sad", "angry"):
        return e
    if e in ("confused", "thinking"):
        return "sad"
    if e in ("calm", "neutral", "relaxed"):
        return "calm"
    return "calm"


def map_speaking_emotion(face_emotion: str, tone: str) -> str:
    fe = normalize_emotion_label(face_emotion)
    t = (tone or "").strip().lower()

    if fe in ("happy", "excited", "surprised"):
        return "excited" if t == "loud" else ("happy" if fe == "happy" else fe)
    if fe in ("angry", "sad", "confused"):
        return fe

    if t == "loud":
        return "excited"

    if t == "quiet":
        if fe in ("thinking",):
            return "thinking"
        if fe in ("neutral", "calm"):
            return "calm"
        return fe or "calm"

    if fe and fe != "neutral":
        return fe
    return "neutral"


# 🎙 ?80
def is_speaking(audio_path, threshold=20):  #  ?🎙 ?0🎙 ?0🎙 ?
    try:
        with wave.open(audio_path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            data = np.frombuffer(frames, dtype=np.int16)
            if len(data) == 0: return False
            rms = np.sqrt(np.mean(data.astype(np.float64) ** 2))
            is_speech = rms > threshold
            result_text = "🎤" if is_speech else "😶"
            print(f"[AUDIO] 🎙 ? RMS={int(rms)}, 🎙 ?{threshold}, 🎙 ?{result_text}")
            return is_speech
    except Exception as e:
        print(f"[ERROR] VAD🎙 ? {e}")
        return False


def analyze_audio_tone(audio_path):
    try:
        with wave.open(audio_path, 'rb') as wf:
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            if len(data) == 0: return False, "silent"
            rms = np.sqrt(np.mean(data.astype(np.float64) ** 2))
            if rms > 2000: return True, "loud"
            if rms > 500: return True, "normal"
            if rms > 20: return True, "quiet"
            return False, "silent"
    except:
        return False, "silent"


def _emotion_selection_key(emotion: str, confidence: float):
    emotion = normalize_emotion_label(emotion)
    priority = {
        "excited": 8,
        "happy": 7,
        "surprised": 6,
        "angry": 5,
        "sad": 4,
        "confused": 3,
        "thinking": 2,
        "calm": 1,
        "neutral": 0,
    }.get(emotion, 0)
    try:
        conf = float(confidence or 0.0)
    except Exception:
        conf = 0.0
    expressive = 1 if priority >= 2 else 0
    return expressive, priority, conf


def _body_action_key(action: str, score: float = 0.0):
    priority = {
        "high_activity": 3,
        "normal_gesture": 2,
        "calm": 1,
        "static": 0,
    }.get(str(action or "").strip().lower(), 0)
    try:
        movement = float(score or 0.0)
    except Exception:
        movement = 0.0
    return priority, movement


def _detect_visual_state_from_video(video_path: str, max_samples: int = 3):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, None, "neutral", 0.0, "static"

    sampled = 0
    first_frame = None
    best_frame = None
    best_emotion = "neutral"
    best_confidence = 0.0
    best_key = _emotion_selection_key(best_emotion, best_confidence)
    best_action = "static"
    best_action_key = _body_action_key(best_action, 0.0)

    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frames = []
        if frame_count > 3:
            sample_indices = sorted(set([
                max(0, min(frame_count - 1, int(frame_count * 0.15))),
                max(0, min(frame_count - 1, int(frame_count * 0.50))),
                max(0, min(frame_count - 1, int(frame_count * 0.85))),
            ]))[:max_samples]
            for idx in sample_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if ret and frame is not None:
                    frames.append(frame)
        else:
            for _ in range(max_samples):
                ret, frame = cap.read()
                if ret and frame is not None:
                    frames.append(frame)
                for _ in range(8):
                    if not cap.grab():
                        break

        if not frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            for _ in range(max_samples):
                ret, frame = cap.read()
                if ret and frame is not None:
                    frames.append(frame)
                for _ in range(8):
                    if not cap.grab():
                        break

        analyzer_ref = get_analyzer()
        for frame in frames:
            sampled += 1
            if first_frame is None:
                first_frame = frame

            e_type, e_conf, _ = analyzer_ref.detect_emotion(frame)
            emotion = normalize_emotion_label(e_type)
            emotion_key = _emotion_selection_key(emotion, e_conf)
            if emotion_key > best_key:
                best_key = emotion_key
                best_emotion = emotion
                best_confidence = float(e_conf or 0.0)
                best_frame = frame

            movement_score, movement_desc = analyzer_ref.detect_body_movement(frame)
            action_key = _body_action_key(movement_desc, movement_score)
            if action_key > best_action_key:
                best_action_key = action_key
                best_action = movement_desc or best_action

        if best_frame is None:
            best_frame = first_frame

        # 如果最终结果是 neutral/calm，强制用 MediaPipe 复核
        if best_emotion in ("neutral", "calm") and best_frame is not None:
            try:
                # 直接调用 MediaPipe 复核
                import cv2
                face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                gray = cv2.cvtColor(best_frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                if len(faces) > 0:
                    x, y, w, h = faces[0]
                    face_rgb = cv2.cvtColor(best_frame[y:y+h, x:x+w], cv2.COLOR_BGR2RGB)
                    refined_emotion, refined_conf = analyzer_ref._mediapipe_refine(face_rgb)
                    if refined_emotion:
                        print(f"[EmotionState] MediaPipe 复核覆盖: {best_emotion} -> {refined_emotion} ({refined_conf:.2f})")
                        best_emotion = refined_emotion
                        best_confidence = refined_conf
            except Exception as e:
                print(f"[EmotionState] MediaPipe 复核失败: {e}")

        if sampled:
            print(f"[EmotionState] sampled={sampled}, emotion={best_emotion}, confidence={best_confidence:.2f}, action={best_action}")
        return best_frame is not None, best_frame, best_emotion, best_confidence, best_action
    finally:
        cap.release()
