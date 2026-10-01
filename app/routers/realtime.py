"""实时链路的路由。

本组 8 条，即实时域的全部入口——三条 WebSocket 加五条 POST：

    /ws-signal/{username}/{meeting_id}   WebRTC 信令通道（转发 offer/answer/ice/hangup）
    /ws-asr/{username}/{meeting_id}      PCM 音频上行 + 识别结果广播
    /ws/{username}/{meeting_id}          课堂通用通道（成员进出、状态）
    /api/ai-tutor                        AI 助教（一次性问答）
    /api/browser-asr-final               浏览器侧识别结果的收尾
    /api/check-silence                   检查是否长时间无人发言
    /api/check-quiet-members             找出沉默成员
    /api/ai-tutor-stream                 AI 助教（流式 SSE）

它们与其余路由的区别是**不碰数据库查询**，只做转发与判定；但会用到实时链路那
几块进程内共享状态（ASR 自我语音门禁的阈值、连接管理器、ASR 会话单例）。

## 三条 WebSocket 的装配

`APIRouter` 支持 `.websocket()`，`include_router` 会把它们一并加进路由表，
地址与签名不变。**注册顺序**：本组在装配段最后 include，因此排在其它路由之后；
本仓库没有 `/{...}` 形式的 catch-all 路由，且三条 ws 路径与既有路径的段数都不同，
匹配结果不变。

`asr_manager` / `manager` / `signal_manager` 从它们的真实出处
（`app.realtime.asr_manager` / `app.realtime.registry`）取——是同一批对象，不是副本。
不能 `from server import`，见 `app/routers/__init__.py`。
"""

import asyncio

from fastapi import APIRouter, Depends, Form, WebSocket
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Meeting, Transcript
from app.realtime.asr_manager import asr_manager
from app.realtime.registry import manager, signal_manager
from app.realtime.speech import _create_realtime_transcript_entry
from app.realtime.state import (
    ASR_SELF_VOICE_GATE_CHECK_INTERVAL_MS,
    ASR_SELF_VOICE_GATE_ENABLED,
    ASR_SELF_VOICE_GATE_MIN_MS,
    ASR_SELF_VOICE_GATE_RMS_THRESHOLD,
    ASR_SELF_VOICE_GATE_SILENCE_MS,
    ASR_SELF_VOICE_GATE_WINDOW_MS,
    REALTIME_ASR_VOICEPRINT_DISABLED,
)
from app.realtime.stream import process_user_stream_generator
from app.services.llm_service import llm

router = APIRouter()

@router.websocket("/ws-signal/{username}/{meeting_id}")
async def websocket_signal_endpoint(websocket: WebSocket, username: str, meeting_id: int):
    """
    WebRTC 信令通道：转发 webrtc_offer / webrtc_answer / webrtc_ice / webrtc_hangup。
    from 字段强制为连接身份，防止伪造。
    """
    await signal_manager.register(websocket, meeting_id, username)
    print(f"[SIGNAL] WebSocket: {username} -> meeting{meeting_id}")
    try:
        while True:
            data = await websocket.receive_json()
            t = data.get("type")
            if t not in ("webrtc_offer", "webrtc_answer", "webrtc_ice", "webrtc_hangup"):
                continue
            target = data.get("to")
            if not target or target == username:
                continue
            data["from"] = username
            ok = await signal_manager.forward_to(meeting_id, target, data)
            if not ok:
                print(f"[SIGNAL] 转发失败: {username} -> {target}")
    except Exception as e:
        print(f"[SIGNAL] 断开: {username} - {type(e).__name__}: {e}")
    finally:
        signal_manager.unregister(meeting_id, username)


@router.websocket("/ws-asr/{username}/{meeting_id}")
async def websocket_asr_endpoint(websocket: WebSocket, username: str, meeting_id: int):
    """
    实时语音识别 WebSocket 端点。
    接收前端发来的 PCM 音频数据（二进制），转发给阿里云 NLS，
    将中间/最终识别结果广播给课堂所有成员。
    延迟启动：收到第一个音频包后才创建阿里云 NLS 会话。
    """
    await websocket.accept()
    print(f"[ASR] WebSocket连接: {username} -> meeting{meeting_id}")

    # 记录连接但不立即启动阿里云会话
    if meeting_id not in asr_manager.meeting_connections:
        asr_manager.meeting_connections[meeting_id] = {}
    asr_manager.meeting_connections[meeting_id][username] = websocket

    session_started = False
    try:
        while True:
            data = await websocket.receive_bytes()
            if len(data) > 0:
                key = (int(meeting_id), username)
                asr_manager._append_pcm_buffer(meeting_id, username, data)

                # 阿里云会话收到音频后立即启动；实时转文字不使用声纹门控。
                if not session_started:
                    print(f"[ASR] 启动阿里云实时会话，声纹门控已关闭: {username}")
                    success = await asr_manager.start_session(username, meeting_id, websocket)
                    if not success:
                        print(f"[ASR] 阿里云会话启动失败，继续接收但不转发")
                        try:
                            await websocket.send_json({
                                "type": "asr_error",
                                "message": "阿里云实时转写会话启动失败，请检查服务器网络或 ASR 配置"
                            })
                        except Exception:
                            pass
                        session_started = True
                        continue
                    session_started = True
                    try:
                        status_message = "Aliyun realtime ASR started"
                        await websocket.send_json({
                            "type": "asr_status",
                            "message": status_message
                        })
                    except Exception:
                        pass

                # Keep Aliyun ASR hot from the first PCM frame. The self-voice gate
                # only controls whether callbacks may broadcast/persist text.
                asr_manager.feed_audio(username, meeting_id, data)

                if ASR_SELF_VOICE_GATE_ENABLED and not REALTIME_ASR_VOICEPRINT_DISABLED:
                    state = asr_manager.self_voice_gate_state.setdefault(key, {
                        "last_check_ms": 0,
                        "last_voice_ms": 0,
                        "allow_output": False,
                        "checking": False,
                        "check_token": 0,
                    })
                    total_ms = asr_manager.pcm_total_ms.get(key, 0)
                    rms = asr_manager._pcm_rms(data)
                    if rms >= ASR_SELF_VOICE_GATE_RMS_THRESHOLD:
                        state["last_voice_ms"] = total_ms

                    gate_open = bool(state.get("allow_output"))
                    if (
                        gate_open
                        and not state.get("sentence_locked")
                        and not state.get("active_sentence_id")
                        and state.get("last_voice_ms")
                        and (total_ms - state["last_voice_ms"]) >= ASR_SELF_VOICE_GATE_SILENCE_MS
                    ):
                        print(f"[ASR] {username}@meeting{meeting_id} silence, close legacy self voice gate")
                        state["allow_output"] = False
                        state["sentence_locked"] = False
                        continue

                    if not bool(state.get("allow_output")):
                        available_ms = min(total_ms, ASR_SELF_VOICE_GATE_WINDOW_MS)
                        if available_ms < ASR_SELF_VOICE_GATE_MIN_MS:
                            continue
                        if (total_ms - int(state.get("last_check_ms") or 0)) < ASR_SELF_VOICE_GATE_CHECK_INTERVAL_MS:
                            continue
                        if state.get("checking"):
                            continue
                        state["last_check_ms"] = total_ms
                        gate_pcm = asr_manager._get_recent_pcm(key, ASR_SELF_VOICE_GATE_WINDOW_MS)
                        state["checking"] = True
                        state["check_token"] = int(state.get("check_token") or 0) + 1
                        asyncio.create_task(
                            asr_manager._run_self_voice_gate_check(
                                int(meeting_id),
                                username,
                                key,
                                gate_pcm,
                                state["check_token"],
                            )
                        )

    except Exception as e:
        print(f"[ASR] WebSocket断开: {username} - {type(e).__name__}")
    finally:
        await asr_manager.stop_session(username, meeting_id, websocket)


@router.websocket("/ws/{username}/{meeting_id}")
async def websocket_endpoint(websocket: WebSocket, username: str, meeting_id: int):
    await manager.connect(websocket, meeting_id, username)
    print(f"[OK] WebSocket连接成功: {username} -> 课堂{meeting_id}")

    # 广播成员加入
    online_members = manager.get_online_members(meeting_id)
    await manager.broadcast_to_meeting(meeting_id, {
        "type": "member_update",
        "action": "join",
        "username": username,
        "online_members": online_members
    })

    try:
        while True:
            # 接收消息（支持 bytes 和 text 类型）
            message = await websocket.receive()

            # 处理心跳消息
            if "text" in message:
                text_data = message["text"]
                if text_data == "ping":
                    await websocket.send_text("pong")
                    continue

            # 处理音视频数据
            if "bytes" in message:
                data = message["bytes"]
                print(f"[DATA] 收到数据: {len(data)} 字节")

                if len(data) > 0:
                    # 处理音视频流
                    print(f"[PROCESS] 处理中...")
                    import asyncio
                    import queue

                    result_queue = queue.Queue()

                    def run_generator():
                        """在线程池中运行同步generator，逐个放入队列"""
                        try:
                            for result in process_user_stream_generator(username, data, int(meeting_id)):
                                result_queue.put(result)
                        except Exception as e:
                            print(f"[ERROR] generator异常: {e}")
                        finally:
                            result_queue.put(None)  # 结束标记

                    # 在线程池中启动generator
                    loop = asyncio.get_event_loop()
                    future = loop.run_in_executor(None, run_generator)

                    # 异步轮询队列，每个结果立即广播
                    result_count = 0
                    while True:
                        try:
                            result = result_queue.get_nowait()
                        except queue.Empty:
                            await asyncio.sleep(0.05)
                            continue
                        if result is None:
                            break
                        result_count += 1
                        print(f"[SEND] 发送第{result_count}条结果: {result.get('type', 'unknown')}")
                        await manager.broadcast_to_meeting(meeting_id, result)

                    await future  # 确保线程完成
                    print(f"[OK] 处理完成{result_count}条结果")
    except Exception as e:
        print(f"[WARN] WebSocket断开连接: {username} - {type(e).__name__}")
        manager.disconnect(websocket, meeting_id, username)
        # 广播成员离开
        online_members = manager.get_online_members(meeting_id)
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "member_update",
            "action": "leave",
            "username": username,
            "online_members": online_members
        })


@router.post("/api/ai-tutor")
async def ai_tutor(question: str = Form(...)):
    """
    AI导师接口
    学生提问，返回AI解答
    """
    try:
        if not question or not question.strip():
            return {"status": "error", "answer": "问题不能为空"}

        question = question.strip()
        print(f"收到 AI导师提问: {question}")

        # 复用 llm_service 内部的 client / 缓存
        answer = llm.ai_tutor(question)

        if not answer:
            answer = "抱歉，我暂时无法回答这个问题。"

        print(f"[OK] AI导师回答: {answer[:100]}...")
        return {"status": "success", "answer": answer}

    except Exception as e:
        print(f"[ERROR] AI导师失败: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "answer": f"抱歉，AI导师暂时无法回答: {str(e)}"}

@router.post("/api/browser-asr-final")
async def browser_asr_final(
    meeting_id: int = Form(...),
    username: str = Form(...),
    text: str = Form(...),
):
    """浏览器原生语音识别兜底：将最终句子回写到课堂流和报告链路"""
    clean_text = str(text or "").strip()
    if not clean_text:
        return {"status": "ignored", "message": "empty text"}

    prepared = await asyncio.to_thread(
        _create_realtime_transcript_entry,
        username,
        int(meeting_id),
        clean_text,
    )
    if not prepared:
        return {"status": "ignored", "message": "duplicate or invalid"}

    await manager.broadcast_to_meeting(int(meeting_id), prepared["fast_payload"])
    asyncio.create_task(asr_manager._dispatch_realtime_analysis(prepared))
    return {
        "status": "success",
        "transcript_id": prepared["transcript_id"],
        "text": clean_text,
    }


@router.post("/api/check-silence")
async def check_silence(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """检查课堂是否沉默超过2分钟，如果是则生成话题建议"""
    try:
        if not manager.is_group_silent(meeting_id, silence_seconds=120):
            return {"status": "ok", "silent": False}

        if manager.silence_notified.get(meeting_id):
            return {"status": "ok", "silent": True, "already_notified": True}

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        # 获取最近讨论上下文
        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id.desc()).limit(5).all()
        ctx = "\n".join([f"{t.user.username}: {t.content}" for t in reversed(recents)])

        suggestion = llm.generate_topic_suggestion(
            meeting.topic, ctx, meeting.knowledge_points, target_type="group"
        )

        # 广播给所有在线成员
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "topic_suggestion",
            "target": "all",
            "suggestion": suggestion,
            "reason": "group_silence"
        })
        manager.silence_notified[meeting_id] = True

        return {"status": "success", "silent": True, "suggestion": suggestion}
    except Exception as e:
        print(f"[ERROR] check-silence: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/check-quiet-members")
async def check_quiet_members(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """检查发言少的成员并推送个性化话题建议"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        quiet_members = manager.get_quiet_members(meeting_id, threshold=2)
        if not quiet_members:
            return {"status": "ok", "quiet_members": []}

        # 获取讨论上下文
        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id.desc()).limit(5).all()
        ctx = "\n".join([f"{t.user.username}: {t.content}" for t in reversed(recents)])

        suggestion = llm.generate_topic_suggestion(
            meeting.topic, ctx, meeting.knowledge_points, target_type="quiet"
        )

        # 只推送给沉默的成员
        for member in quiet_members:
            await manager.send_to_user(meeting_id, member, {
                "type": "topic_suggestion",
                "target": "personal",
                "suggestion": suggestion,
                "reason": "low_participation"
            })

        return {"status": "success", "quiet_members": quiet_members, "suggestion": suggestion}
    except Exception as e:
        print(f"[ERROR] check-quiet-members: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/api/ai-tutor-stream")
async def ai_tutor_stream(question: str = Form(...), history: str = Form(default="[]")):
    """
    AI导师流式接口 - SSE
    """
    import json as _json

    def generate():
        try:
            q = question.strip()
            if not q:
                yield f"data: 问题不能为空\n\n"
                yield "data: [DONE]\n\n"
                return

            # 解析历史对话
            try:
                hist = _json.loads(history) if history else []
            except Exception:
                hist = []

            print(f"[STREAM] AI导师提问: {q}")
            for token in llm.ai_tutor_stream(q, hist):
                # SSE 格式：每行 data: xxx，用双换行分隔
                yield f"data: {_json.dumps(token, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            print(f"[OK] AI导师流式回答完成")
        except Exception as e:
            print(f"[ERROR] AI导师流式失败: {e}")
            yield f"data: {_json.dumps('抱歉，系统出错，请重试。', ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
