"""实时用户流的生成器。

`process_user_stream_generator(username, video_data, meeting_id)` 是实时链路的主
循环：它一边收浏览器推来的音视频分片，一边跑声纹/情绪/画面判定、写转写记录、
更新知识图谱，并按事件把结果 yield 给 WebSocket 消费方。

它内部有大量跨分支共享的局部变量与控制流（提前 return 的清理路径、按帧累积的
缓冲），不要切开。

## 关于这堆 import

模块级全局必须显式、完整地导入，少一个要到执行到那条分支才 NameError。函数
**自己**在开头写了 `import time`、并在四处写了 `import traceback`：那些是函数体
内的局部绑定，原样保留，不需要（也不应该）提到模块级来。

`tests_safe/test_module_free_names.py` 用 symtable 判据守住这一点，本模块的头
必须让它保持空集。
"""

import os
import re
import subprocess
import threading
from datetime import datetime

import cv2

from app.core.database import SessionLocal
from app.core.emotions import normalize_emotion_label
from app.core.oss import USE_OSS, get_oss_manager
from app.core.paths import PROJECT_ROOT
from app.models import AIInsight, EmotionLog, Meeting, Transcript
from app.realtime.emotion_helpers import (
    _detect_visual_state_from_video,
    analyze_audio_tone,
    is_speaking,
    map_silent_emotion,
    map_speaking_emotion,
)
from app.realtime.knowledge_graph import update_knowledge_graph
from app.realtime.registry import manager
from app.realtime.speech import _persist_speech_emotion_artifacts
from app.realtime.state import (
    ASR_SELF_VOICE_GATE_ENABLED,
    REALTIME_ASR_VOICEPRINT_DISABLED,
    REALTIME_TEXT_SCORING_ENABLED,
    _remember_recent_media_state,
    _stage_recent_media_state_assets,
    kg_counter,
    recent_speech_cache,
    recent_speech_cache_lock,
)
from app.services.ai_core import engine
from app.services.knowledge_graph_service import kg_service
from app.services.llm_service import llm
from app.services.research_runtime import research_runtime
from app.services.user_lookup import resolve_user_by_identifier

# 直接由 PROJECT_ROOT 重算，不复制字面量路径，免得锚点随文件位置漂移
# （见 tests_safe/test_paths_anchor.py）。
ROOT_DIR = str(PROJECT_ROOT)

def process_user_stream_generator(username, video_data, meeting_id):
    import time
    db = SessionLocal()
    v_path = None
    a_path = None

    try:
        timestamp = int(time.time() * 1000)
        v_name = f"{meeting_id}_{username}_{timestamp}.webm"
        v_path = os.path.join(ROOT_DIR, "storage", "video_chunks", v_name)
        with open(v_path, "wb") as f:
            f.write(video_data)

        # 防御：过小/不完整的 webm 切片会导致 ffmpeg 报 EBML/EOF 错误，直接跳过
        try:
            if os.path.getsize(v_path) < 1024:  # 1KB 以下基本无有效媒体数据
                print(f"[WARN] 视频切片过小，跳过: {v_name}")
                return
        except Exception:
            pass

        a_name = f"{meeting_id}_{username}_{timestamp}.wav"
        a_path = os.path.join(ROOT_DIR, "storage", "audio_chunks", a_name)
        # 用 subprocess 检查 ffmpeg 是否成功
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", v_path, "-ac", "1", "-ar", "16000", "-f", "wav", "-loglevel", "error", a_path],
                capture_output=True,
                text=True
            )
            if proc.returncode != 0 or (not os.path.exists(a_path)) or os.path.getsize(a_path) == 0:
                err = (proc.stderr or proc.stdout or "").strip()
                print(f"[WARN] ffmpeg 转码失败，跳过该切片: {v_name} | {err[:200]}")
                return
        except Exception as e:
            print(f"[WARN] ffmpeg 执行异常，跳过该切片: {v_name} | {e}")
            return

        user = resolve_user_by_identifier(db, username)
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not user or not meeting:
            print(f"[WARN] 用户或课堂不存在: username={username}, meeting_id={meeting_id}")
            return

        ret, frame, vis_emotion, emotion_confidence, body_action = _detect_visual_state_from_video(v_path)

        vad_check = is_speaking(a_path)

        if vad_check:
            print(f"[MIC] [{username}] 检测到说话")

            _, tone = analyze_audio_tone(a_path)
            vis_emotion = map_speaking_emotion(vis_emotion, tone)

            yield {
                "type": "speaking_status",
                "username": username,
                "status": "recognizing",
                "tags": {"emotion": vis_emotion, "action": body_action}
            }

            # 语音识别。实时 ASR 会晚一点返回 final 文本，所以先把本轮音频/视频证据暂存起来，
            # 后续创建 Transcript 时再用于音色相似度、声纹聚类和身份绑定复核。
            if REALTIME_TEXT_SCORING_ENABLED:
                has_active_realtime_asr = False
                try:
                    has_active_realtime_asr = bool(
                        globals().get("asr_manager")
                        and getattr(globals().get("asr_manager"), "sessions", {}).get((meeting_id, username))
                    )
                except Exception:
                    has_active_realtime_asr = False

                artifacts = _persist_speech_emotion_artifacts(
                    db,
                    user=user,
                    meeting_id=meeting_id,
                    username=username,
                    timestamp=timestamp,
                    v_name=v_name,
                    v_path=v_path,
                    frame=frame,
                    ret=ret,
                    vis_emotion=vis_emotion,
                    body_action=body_action,
                )
                staged_recent_assets = _stage_recent_media_state_assets(
                    meeting_id,
                    username,
                    timestamp,
                    audio_path=a_path,
                    video_path=v_path,
                    snapshot_path=artifacts.get("snapshot_path", ""),
                )
                _remember_recent_media_state(
                    meeting_id,
                    username,
                    vis_emotion,
                    body_action,
                    tone,
                    audio_path=staged_recent_assets.get("audio_path", a_path),
                    video_path=staged_recent_assets.get("video_path", v_path),
                    snapshot_path=staged_recent_assets.get("snapshot_path", artifacts.get("snapshot_path", "")),
                    video_url=artifacts.get("video_url", ""),
                    snapshot_url=artifacts.get("snapshot_url", ""),
                )
                if ASR_SELF_VOICE_GATE_ENABLED and not REALTIME_ASR_VOICEPRINT_DISABLED:
                    return
                if has_active_realtime_asr:
                    return
                print(f"[FALLBACK] ASR会话不可用，回退到切片转写: meeting={meeting_id}, user={username}")
            else:
                _remember_recent_media_state(
                    meeting_id,
                    username,
                    vis_emotion,
                    body_action,
                    tone,
                    audio_path=a_path,
                    video_path=v_path,
                )

            text = None
            try:
                start_time = time.time()
                text = engine.transcribe_audio(a_path)
                elapsed = time.time() - start_time

                if text:
                    print(f"[OK] 识别成功 {elapsed:.2f}秒")
                else:
                    print(f"[WARN] 识别为空 {elapsed:.2f}秒")
            except Exception as e:
                print(f"[ERROR] [{username}] 识别失败: {e}")
                import traceback
                traceback.print_exc()
                text = None

            if text:
                normalized_text = re.sub(r'\s+', '', str(text or '').strip())
                recent_key = (int(meeting_id), normalized_text)
                now_ts = time.time()
                with recent_speech_cache_lock:
                    cached = recent_speech_cache.get(recent_key)
                    if cached and (now_ts - cached.get("ts", 0)) < 3.0:
                        cached_user = cached.get("username", "")
                        if cached_user != username:
                            print(f"[DEDUP] 同时窗内重复转写，保留首个端: meeting={meeting_id}, first={cached_user}, skip={username}")
                        else:
                            print(f"[DEDUP] 跳过同端重复转写: meeting={meeting_id}, user={username}")
                        return
                    recent_speech_cache[recent_key] = {"username": username, "ts": now_ts}

                print(f"[NOTE] 发言内容: {text} ([FAST] 快速返回...)")
                manager.record_speech(meeting_id, username)
                enhanced_runtime_active = research_runtime.research_algorithms_active
                research_binding = None

                # 第一次快速返回
                fast_payload = {
                    "type": "new_speech_fast",
                    "username": username,
                    "text": text,
                    "tags": {"emotion": vis_emotion, "action": body_action},
                    "timestamp": timestamp,
                    "goals": meeting.knowledge_points,
                    "quality_score": 50,
                    "quality_feedback": "评估中..."
                }
                if enhanced_runtime_active:
                    research_binding = research_runtime.build_initial_transcript_state(
                        username=username,
                        text=text,
                        emotion_tag=vis_emotion,
                        body_action=body_action,
                        audio_tone=tone,
                    )
                    fast_payload["audio_tone"] = tone
                    fast_payload["research_binding"] = research_binding
                yield fast_payload

                # 异步OSS上传
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

                            print(f"[FAST] 上传视频到OSS...")
                            oss_video_url = oss_mgr.upload_video(_v_path, _user_id, _meeting_id)

                            oss_snapshot_url = None
                            if _has_snapshot and _snapshot_path and os.path.exists(_snapshot_path):
                                print(f"[FAST] 上传快照到OSS...")
                                oss_snapshot_url = oss_mgr.upload_snapshot(_snapshot_path, _user_id, _meeting_id)

                                try:
                                    os.remove(_snapshot_path)
                                    print(f"已删除本地快照: {_snapshot_path}")
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
                                    print(f"[OK] OSS链接已更新")
                                else:
                                    print(f"[WARN] 未找到待更新的EmotionLog记录")
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

                # 保存情绪日志
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

                # 保存转录（先用占位评分）
                trans = Transcript(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    content=text,
                    audio_file_path=f"storage/audio_chunks/{a_name}",
                    emotion_tag=vis_emotion,
                    body_action=body_action,
                    audio_tone=tone if enhanced_runtime_active else None,
                    binding_source=research_binding.get("binding_source") if research_binding else None,
                    binding_confidence=research_binding.get("binding_confidence") if research_binding else None,
                    identity_review_status=research_binding.get("identity_review_status") if research_binding else None,
                    identity_review_note=research_binding.get("identity_review_note") if research_binding else None,
                    cross_modal_consistency=research_binding.get("cross_modal_consistency") if research_binding else None,
                    timestamp=datetime.now(),
                    quality_score=50,
                    quality_feedback="评估中..."
                )
                db.add(trans)
                db.commit()
                if enhanced_runtime_active:
                    db.refresh(trans)

                    staged_assets = research_runtime.stage_runtime_assets(
                        meeting_id=meeting_id,
                        transcript_id=trans.id,
                        audio_path=a_path,
                        video_path=v_path,
                        snapshot_path=snapshot_path,
                    )

                    research_runtime.enqueue_transcript_enhancement(
                        transcript_id=trans.id,
                        meeting_id=meeting_id,
                        user_id=user.id,
                        student_id=getattr(user, "student_id", ""),
                        username=username,
                        text=text,
                        topic=meeting.topic,
                        emotion_tag=vis_emotion,
                        body_action=body_action,
                        audio_tone=tone,
                        audio_path=staged_assets.get("audio_path", ""),
                        video_path=staged_assets.get("video_path", ""),
                        snapshot_path=staged_assets.get("snapshot_path", ""),
                    )

                # 联合AI分析
                relevance = 0
                hint = ""
                updated_goals = None
                quality_score = 50
                quality_feedback = ""
                dimensions = {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50}
                quality_distribution = {"relevance": 0.25, "depth": 0.25, "creativity": 0.25, "expression": 0.25}
                quality_research = {}

                # 低信息量短句不触发LLM，直接给默认评价
                if len((text or "").strip()) >= 8:
                    try:
                        recents = db.query(Transcript).filter(
                            Transcript.meeting_id == meeting_id
                        ).order_by(Transcript.id.desc()).limit(3).all()
                        ctx = "\n".join([f"{t.user.username}:{t.content}" for t in recents])

                        print("[AI] 开始联合分析(评分+进度)...")

                        combined = llm.analyze_speech_and_progress(
                            speech_content=text,
                            topic=meeting.topic,
                            recent_context=ctx,
                            current_goals=meeting.knowledge_points,
                            student_name=username
                        )

                        if combined and isinstance(combined, dict):
                            quality_score = combined.get("score", 50)
                            quality_feedback = combined.get("feedback", "") or "已评估"
                            relevance = combined.get("relevance", 0)
                            hint = combined.get("hint", "") or ""
                            updated_goals = combined.get("updated_goals")
                            dimensions = combined.get("dimensions", dimensions)
                            print(f"[OK] 联合分析完成: score={quality_score}, relevance={relevance}")
                        else:
                            print(f"[WARN] 联合分析返回格式异常: {combined}")
                            quality_feedback = "已评估"

                    except Exception as e:
                        print(f"[ERROR] 联合AI分析失败: {e}")
                        import traceback
                        traceback.print_exc()
                        quality_feedback = "评估超时"
                else:
                    # 短句直接给默认反馈
                    quality_score = 35
                    quality_feedback = "语句较短，建议展开详细论述"

                # 更新数据库
                if updated_goals:
                    # 检测新完成的目标
                    old_done = {g["id"] for g in (meeting.knowledge_points or []) if g.get("status") == "done"}
                    new_done = {g["id"] for g in updated_goals if g.get("status") == "done"}
                    newly_completed = new_done - old_done
                    meeting.knowledge_points = updated_goals

                    # 如果有新完成的目标，发送目标完成通知
                    if newly_completed:
                        completed_descs = [g["desc"] for g in updated_goals if g["id"] in newly_completed]
                        all_done = all(g.get("status") == "done" for g in updated_goals)
                        yield {
                            "type": "goal_completed",
                            "completed_goals": completed_descs,
                            "all_done": all_done,
                            "goals": updated_goals
                        }
                if enhanced_runtime_active:
                    pdl_result = research_runtime.refine_speech_assessment(
                        text=text,
                        topic=meeting.topic,
                        dimensions=dimensions,
                        quality_score=quality_score,
                        quality_feedback=quality_feedback,
                        relevance=relevance,
                        emotion_tag=vis_emotion,
                        body_action=body_action,
                        audio_tone=tone,
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

                # 第二次返回：带AI分析结果
                payload = {
                    "type": "speech_analysis_update",
                    "transcript_id": trans.id,
                    "username": username,
                    "text": text,
                    "timestamp": timestamp,
                    "relevance": relevance,
                    "quality_score": quality_score,
                    "quality_feedback": quality_feedback,
                    "quality_dimensions": dimensions,
                    "goals": meeting.knowledge_points,
                    "hint": hint
                }
                if enhanced_runtime_active:
                    payload["research_binding"] = research_runtime.get_transcript_review(trans.id) or research_binding
                    payload["quality_distribution"] = quality_distribution
                    payload["quality_research"] = quality_research
                yield payload

                # 材料推荐（每10条发言）
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
                            } for t in reversed(recent_5)]

                            materials_result = llm.recommend_materials(discussion_ctx, meeting.topic)

                            if materials_result.get("materials"):
                                print(f"[BOOK] 推荐了 {len(materials_result['materials'])} 个材料")
                                yield {
                                    "type": "material_recommendation",
                                    "materials": materials_result["materials"],
                                    "trigger_reason": materials_result.get("trigger_reason", "")
                                }
                    except Exception as e:
                        print(f"[ERROR] 材料推荐失败: {e}")

                # 知识图谱更新（每10条发言）
                if meeting_id not in kg_counter:
                    kg_counter[meeting_id] = 0
                kg_counter[meeting_id] += 1

                if kg_counter[meeting_id] % 10 == 0:
                    print(f"[WEB] 更新知识图谱...")
                    updated_graph = update_knowledge_graph(meeting_id, db)
                    if updated_graph:
                        viz_data = kg_service.generate_graph_visualization_data(updated_graph)
                        yield {
                            "type": "knowledge_graph_update",
                            "data": viz_data
                        }

        else:
            silent_emotion = map_silent_emotion(vis_emotion)
            if silent_emotion != 'calm' or body_action == 'high_activity':
                snapshot_url = None

                try:
                    if ret:
                        s_name = f"{meeting_id}_{username}_{timestamp}.jpg"
                        local_snapshot_path = os.path.join(ROOT_DIR, "storage", "snapshots", s_name)
                        cv2.imwrite(local_snapshot_path, frame)

                        if USE_OSS:
                            oss_mgr = get_oss_manager()
                            print(f"[FAST] 上传快照到OSS...")
                            snapshot_url = oss_mgr.upload_snapshot(local_snapshot_path, user.id, meeting_id)

                            try:
                                os.remove(local_snapshot_path)
                            except Exception:
                                pass
                        else:
                            snapshot_url = f"storage/snapshots/{s_name}"
                except Exception as e:
                    print(f"[ERROR] 快照处理失败: {e}")
                    if ret:
                        s_name = f"{meeting_id}_{username}_{timestamp}.jpg"
                        local_snapshot_path = os.path.join(ROOT_DIR, "storage", "snapshots", s_name)
                        cv2.imwrite(local_snapshot_path, frame)
                        snapshot_url = f"storage/snapshots/{s_name}"

                emo_str = f"{silent_emotion}|{body_action}"
                if len(emo_str) > 90:
                    emo_str = emo_str[:90]

                db.add(EmotionLog(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    emotion_type=emo_str,
                    intensity=0.8,
                    snapshot_path=snapshot_url
                ))
                db.commit()

                yield {
                    "type": "new_emotion",
                    "username": username,
                    "emotion": silent_emotion,
                    "action": body_action,
                    "snapshot": snapshot_url
                }

    except Exception as e:
        print(f"Error process: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理过期去重缓存，避免同一句话跨时段误伤后续发言
        try:
            now_ts = time.time()
            with recent_speech_cache_lock:
                expired = [k for k, v in recent_speech_cache.items() if (now_ts - v.get("ts", 0)) > 15]
                for k in expired:
                    recent_speech_cache.pop(k, None)
        except Exception:
            pass
        try:
            if v_path and os.path.exists(v_path):
                os.remove(v_path)
            if a_path and os.path.exists(a_path):
                os.remove(a_path)
        except Exception:
            pass
        db.close()
