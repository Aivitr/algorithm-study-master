"""实时语音分析段：产物落库、转写记录、分析主流程与事件流。

四个函数首尾相接：

    _persist_speech_emotion_artifacts      把一轮分析的情绪/画面产物落库
    _create_realtime_transcript_entry      生成一条实时转写记录
    _run_realtime_speech_analysis          跑一轮完整分析
    _stream_realtime_speech_analysis_events 把分析过程按事件流吐给 WebSocket

它们只被 WebSocket 侧调用，彼此之间也互相调用，不要中途拆开。

## 关于这堆 import

模块级全局必须显式、完整地导入，少一个要到执行到那条分支才 NameError。
`tests_safe/test_module_free_names.py` 用 symtable 判据守住这一点，本模块的头
必须让它保持空集。
"""

import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import cv2
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.emotions import normalize_emotion_label
from app.core.oss import USE_OSS, get_oss_manager
from app.core.paths import PROJECT_ROOT
from app.models import AIInsight, EmotionLog, Meeting, Transcript, User
from app.realtime.knowledge_graph import update_knowledge_graph
from app.realtime.registry import manager
from app.realtime.state import (
    _attach_recent_speech_transcript,
    _get_recent_media_state,
    _reserve_recent_speech_by_volume,
    _storage_relative_path,
    kg_counter,
)
from app.services.knowledge_graph_service import kg_service
from app.services.llm_service import llm
from app.services.research_runtime import research_runtime
from app.services.user_lookup import resolve_user_by_identifier

# 直接由 PROJECT_ROOT 重算，不复制字面量路径，免得锚点随文件位置漂移
# （见 tests_safe/test_paths_anchor.py）。
ROOT_DIR = str(PROJECT_ROOT)

def _persist_speech_emotion_artifacts(
    db: Session,
    *,
    user: User,
    meeting_id: int,
    username: str,
    timestamp: int,
    v_name: str,
    v_path: str,
    frame,
    ret: bool,
    vis_emotion: str,
    body_action: str,
) -> Dict[str, Any]:
    video_url = f"storage/video_chunks/{v_name}"
    snapshot_url = None
    snapshot_path = None

    if ret:
        s_name = f"{meeting_id}_{username}_{timestamp}.jpg"
        snapshot_path = os.path.join(ROOT_DIR, "storage", "snapshots", s_name)
        cv2.imwrite(snapshot_path, frame)
        snapshot_url = f"storage/snapshots/{s_name}"

    if USE_OSS:
        _v_path = v_path
        _user_id = user.id
        _meeting_id = meeting_id
        _snapshot_path = snapshot_path if ret else None
        _video_url = video_url
        _has_snapshot = ret

        def async_upload():
            try:
                oss_mgr = get_oss_manager()

                print("[FAST] 上传视频到OSS...")
                oss_video_url = oss_mgr.upload_video(_v_path, _user_id, _meeting_id)

                oss_snapshot_url = None
                if _has_snapshot and _snapshot_path and os.path.exists(_snapshot_path):
                    print("[FAST] 上传快照到OSS...")
                    oss_snapshot_url = oss_mgr.upload_snapshot(_snapshot_path, _user_id, _meeting_id)

                    try:
                        os.remove(_snapshot_path)
                    except Exception as e:
                        print(f"[WARN] 删除快照失败: {e}")

                db_update = SessionLocal()
                try:
                    emotion_log = db_update.query(EmotionLog).filter(
                        EmotionLog.meeting_id == _meeting_id,
                        EmotionLog.user_id == _user_id,
                        EmotionLog.video_url == _video_url
                    ).order_by(EmotionLog.id.desc()).first()

                    if emotion_log:
                        emotion_log.video_url = oss_video_url
                        if oss_snapshot_url:
                            emotion_log.snapshot_path = oss_snapshot_url
                        db_update.commit()
                        print("[OK] OSS链接已更新")
                    else:
                        print("[WARN] 未找到待更新的EmotionLog记录")
                except Exception as db_err:
                    print(f"[ERROR] 数据库更新失败: {db_err}")
                    db_update.rollback()
                finally:
                    db_update.close()

            except Exception as e:
                print(f"[ERROR] 上传到OSS失败: {e}")
                import traceback
                traceback.print_exc()

        threading.Thread(target=async_upload, daemon=True).start()

    vis_emotion = normalize_emotion_label(vis_emotion)
    emo_str = f"{vis_emotion}|{body_action}"
    if len(emo_str) > 90:
        emo_str = emo_str[:90]

    db.add(EmotionLog(
        meeting_id=meeting_id,
        user_id=user.id,
        emotion_type=emo_str,
        intensity=0.8,
        video_url=video_url,
        snapshot_path=snapshot_url
    ))
    db.commit()

    return {
        "video_url": video_url,
        "snapshot_url": snapshot_url,
        "snapshot_path": snapshot_path,
    }


def _create_realtime_transcript_entry(
    username: str,
    meeting_id: int,
    text: str,
    audio_volume: Optional[float] = None,
    asr_sentence_id: Optional[str] = None,
    asr_index: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    clean_text = str(text or "").strip()
    if not clean_text:
        return None

    dedup_decision = _reserve_recent_speech_by_volume(meeting_id, username, clean_text, audio_volume=audio_volume)
    if dedup_decision.get("skip"):
        return None

    db = SessionLocal()
    try:
        user = resolve_user_by_identifier(db, username)
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not user or not meeting:
            print(f"[WARN] 用户或课堂不存在: username={username}, meeting_id={meeting_id}")
            return None

        media_state = _get_recent_media_state(meeting_id, username)
        emotion_tag = normalize_emotion_label(media_state.get("emotion_tag", "neutral"))
        body_action = media_state.get("body_action", "static")
        audio_tone = media_state.get("audio_tone", "")
        audio_path = media_state.get("audio_path", "")
        video_path = media_state.get("video_path", "")
        snapshot_path = media_state.get("snapshot_path", "")

        manager.record_speech(meeting_id, username)
        enhanced_runtime_active = research_runtime.research_algorithms_active
        research_binding = research_runtime.build_initial_transcript_state(
            username=username,
            text=clean_text,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
        )

        trans = Transcript(
            meeting_id=meeting_id,
            user_id=user.id,
            content=clean_text,
            audio_file_path=None,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone or None,
            binding_source=research_binding.get("binding_source") if research_binding else None,
            binding_confidence=research_binding.get("binding_confidence") if research_binding else None,
            identity_review_status=research_binding.get("identity_review_status") if research_binding else None,
            identity_review_note=research_binding.get("identity_review_note") if research_binding else None,
            cross_modal_consistency=research_binding.get("cross_modal_consistency") if research_binding else None,
            timestamp=datetime.now(),
            quality_score=50,
            quality_feedback="评估中..."
        )
        trans.quality_feedback = "已断句，正在评分..."
        trans.audio_file_path = _storage_relative_path(audio_path)
        db.add(trans)
        db.commit()
        db.refresh(trans)

        if enhanced_runtime_active:
            staged_assets = research_runtime.stage_runtime_assets(
                meeting_id=meeting_id,
                transcript_id=trans.id,
                audio_path=audio_path,
                video_path=video_path,
                snapshot_path=snapshot_path,
            )
            research_binding = research_runtime.enqueue_transcript_enhancement(
                transcript_id=trans.id,
                meeting_id=meeting_id,
                user_id=user.id,
                student_id=getattr(user, "student_id", ""),
                username=username,
                text=clean_text,
                topic=meeting.topic,
                emotion_tag=emotion_tag,
                body_action=body_action,
                audio_tone=audio_tone,
                audio_path=staged_assets.get("audio_path", audio_path),
                video_path=staged_assets.get("video_path", video_path),
                snapshot_path=staged_assets.get("snapshot_path", snapshot_path),
            )

        timestamp = int(time.time() * 1000) + (trans.id % 997)
        _attach_recent_speech_transcript(meeting_id, username, clean_text, trans.id, timestamp)
        replaced = dedup_decision.get("replace") or {}
        if replaced.get("transcript_id"):
            old_trans = db.query(Transcript).filter(Transcript.id == int(replaced["transcript_id"])).first()
            if old_trans:
                db.delete(old_trans)
                db.commit()

        goals_snapshot = json.loads(json.dumps(meeting.knowledge_points or [], ensure_ascii=False))
        fast_payload = {
            "type": "new_speech_fast",
            "transcript_id": trans.id,
            "username": username,
            "text": clean_text,
            "tags": {"emotion": emotion_tag, "action": body_action},
            "timestamp": timestamp,
            "goals": goals_snapshot,
            "quality_score": 50,
            "quality_feedback": "评估中..."
        }
        if asr_sentence_id:
            fast_payload["asr_sentence_id"] = asr_sentence_id
        if asr_index is not None:
            fast_payload["asr_index"] = asr_index
        if replaced.get("transcript_id"):
            fast_payload["replaces_transcript_id"] = replaced.get("transcript_id")
            fast_payload["replaces_username"] = replaced.get("username")
            fast_payload["replaces_text"] = replaced.get("text")
            fast_payload["replaces_timestamp"] = replaced.get("timestamp")
        if audio_tone:
            fast_payload["audio_tone"] = audio_tone
        if research_binding:
            fast_payload["research_binding"] = research_binding

        fast_payload["quality_feedback"] = "已断句，正在评分..."

        return {
            "meeting_id": meeting_id,
            "transcript_id": trans.id,
            "timestamp": timestamp,
            "username": username,
            "topic": meeting.topic,
            "text": clean_text,
            "asr_sentence_id": asr_sentence_id,
            "asr_index": asr_index,
            "fast_payload": fast_payload,
            "emotion_tag": emotion_tag,
            "body_action": body_action,
            "audio_tone": audio_tone,
            "research_binding": research_binding,
            "enhanced_runtime_active": enhanced_runtime_active,
        }
    finally:
        db.close()


def _run_realtime_speech_analysis(prepared: Dict[str, Any], precomputed_combined: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        meeting_id = int(prepared["meeting_id"])
        transcript_id = int(prepared["transcript_id"])
        username = prepared["username"]
        text = prepared["text"]
        timestamp = prepared["timestamp"]
        asr_sentence_id = prepared.get("asr_sentence_id")
        asr_index = prepared.get("asr_index")
        enhanced_runtime_active = bool(prepared.get("enhanced_runtime_active"))
        research_binding = prepared.get("research_binding")
        emotion_tag = prepared.get("emotion_tag", "neutral")
        body_action = prepared.get("body_action", "static")
        audio_tone = prepared.get("audio_tone", "")

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        trans = db.query(Transcript).filter(Transcript.id == transcript_id).first()
        if not meeting or not trans:
            return []

        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id,
            Transcript.id != transcript_id
        ).order_by(Transcript.id.desc()).limit(3).all()
        ctx = "\n".join([f"{t.user.username}:{t.content}" for t in recents if getattr(t, "user", None)])

        if precomputed_combined and isinstance(precomputed_combined, dict):
            print("[AI] 使用流式返回的同一份联合分析结果")
            combined = precomputed_combined
        else:
            print("[AI] 开始实时句级联合分析(评分+进度)...")
            combined = llm.analyze_speech_and_progress(
                speech_content=text,
                topic=meeting.topic,
                recent_context=ctx,
                current_goals=meeting.knowledge_points,
                student_name=username
            )

        quality_score = int(combined.get("score", 50) or 50)
        quality_feedback = combined.get("feedback", "") or "已评估"
        relevance = int(combined.get("relevance", 50) or 50)
        hint = combined.get("hint", "") or ""
        updated_goals = combined.get("updated_goals") or (meeting.knowledge_points or [])
        dimensions = combined.get("dimensions") or {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50}
        quality_distribution = {"relevance": 0.25, "depth": 0.25, "creativity": 0.25, "expression": 0.25}
        quality_research = {}

        events: List[Dict[str, Any]] = []

        if updated_goals:
            old_done = {g["id"] for g in (meeting.knowledge_points or []) if g.get("status") == "done"}
            new_done = {g["id"] for g in updated_goals if g.get("status") == "done"}
            newly_completed = new_done - old_done
            meeting.knowledge_points = updated_goals

            if newly_completed:
                completed_descs = [g["desc"] for g in updated_goals if g["id"] in newly_completed]
                all_done = all(g.get("status") == "done" for g in updated_goals)
                events.append({
                    "type": "goal_completed",
                    "completed_goals": completed_descs,
                    "all_done": all_done,
                    "goals": updated_goals
                })

        if enhanced_runtime_active:
            pdl_result = research_runtime.refine_speech_assessment(
                text=text,
                topic=meeting.topic,
                dimensions=dimensions,
                quality_score=quality_score,
                quality_feedback=quality_feedback,
                relevance=relevance,
                emotion_tag=emotion_tag,
                body_action=body_action,
                audio_tone=audio_tone,
            )
            if pdl_result and isinstance(pdl_result, dict):
                quality_score = pdl_result.get("score", quality_score)
                quality_feedback = pdl_result.get("quality_feedback", quality_feedback)
                dimensions = pdl_result.get("dimensions", dimensions)
                quality_distribution = pdl_result.get("soft_distribution", quality_distribution)
                quality_research = pdl_result.get("research", quality_research)

        trans.relevance_score = relevance
        trans.quality_score = quality_score
        trans.quality_feedback = quality_feedback
        db.commit()

        if hint:
            db.add(AIInsight(
                meeting_id=meeting_id,
                target_user=username,
                content=hint,
                type="hint"
            ))
            db.commit()

        analysis_payload = {
            "type": "speech_analysis_update",
            "transcript_id": transcript_id,
            "username": username,
            "text": text,
            "timestamp": timestamp,
            "relevance": relevance,
            "quality_score": quality_score,
            "quality_feedback": quality_feedback,
            "quality_dimensions": dimensions,
            "goals": meeting.knowledge_points,
            "hint": hint,
            "asr_sentence_id": asr_sentence_id,
            "asr_index": asr_index
        }
        if enhanced_runtime_active:
            analysis_payload["research_binding"] = research_runtime.get_transcript_review(trans.id) or research_binding
            analysis_payload["quality_distribution"] = quality_distribution
            analysis_payload["quality_research"] = quality_research
        events.append(analysis_payload)

        transcript_count = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).count()

        if transcript_count > 0 and transcript_count % 10 == 0:
            print(f"[BOOK] 触发材料推荐: {transcript_count}条发言")
            try:
                recent_5 = db.query(Transcript).filter(
                    Transcript.meeting_id == meeting_id
                ).order_by(Transcript.id.desc()).limit(5).all()

                if len(recent_5) >= 3:
                    discussion_ctx = [{
                        "username": t.user.username,
                        "content": t.content
                    } for t in reversed(recent_5) if getattr(t, "user", None)]

                    materials_result = llm.recommend_materials(discussion_ctx, meeting.topic)

                    if materials_result.get("materials"):
                        events.append({
                            "type": "material_recommendation",
                            "materials": materials_result["materials"],
                            "trigger_reason": materials_result.get("trigger_reason", "")
                        })
            except Exception as e:
                print(f"[ERROR] 材料推荐失败: {e}")

        kg_counter[meeting_id] = kg_counter.get(meeting_id, 0) + 1
        if kg_counter[meeting_id] % 10 == 0:
            print("[WEB] 更新知识图谱...")
            updated_graph = update_knowledge_graph(meeting_id, db)
            if updated_graph:
                viz_data = kg_service.generate_graph_visualization_data(updated_graph)
                events.append({
                    "type": "knowledge_graph_update",
                    "data": viz_data
                })

        return events
    except Exception as e:
        print(f"[ERROR] 实时评分失败: {e}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        db.close()


def _stream_realtime_speech_analysis_events(prepared: Dict[str, Any]):
    """Stream the real LLM feedback from the same detailed JSON analysis request."""
    db = SessionLocal()
    combined = None
    try:
        meeting_id = int(prepared["meeting_id"])
        transcript_id = int(prepared["transcript_id"])
        username = prepared["username"]
        text = prepared["text"]
        timestamp = prepared["timestamp"]
        asr_sentence_id = prepared.get("asr_sentence_id")
        asr_index = prepared.get("asr_index")

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            yield {"__combined": None}
            return

        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id,
            Transcript.id != transcript_id
        ).order_by(Transcript.id.desc()).limit(3).all()
        ctx = "\n".join([f"{t.user.username}:{t.content}" for t in recents if getattr(t, "user", None)])

        yield {
            "type": "speech_feedback_stream_start",
            "transcript_id": transcript_id,
            "username": username,
            "text": text,
            "timestamp": timestamp,
            "quality_feedback": "",
            "asr_sentence_id": asr_sentence_id,
            "asr_index": asr_index,
        }

        for item in llm.stream_speech_analysis_and_progress(
            speech_content=text,
            topic=meeting.topic,
            recent_context=ctx,
            current_goals=meeting.knowledge_points,
            student_name=username,
        ) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "feedback_delta":
                delta = item.get("delta") or ""
                if delta:
                    yield {
                        "type": "speech_feedback_delta",
                        "transcript_id": transcript_id,
                        "username": username,
                        "text": text,
                        "timestamp": timestamp,
                        "delta": delta,
                        "asr_sentence_id": asr_sentence_id,
                        "asr_index": asr_index,
                    }
            elif item.get("type") == "result":
                combined = item.get("result")
    except Exception as e:
        print(f"[AI] 流式真实评语失败: {e}")
    finally:
        db.close()
        yield {"__combined": combined}
