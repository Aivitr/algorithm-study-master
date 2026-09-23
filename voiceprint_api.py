"""
声纹注册和管理 API
添加到 server.py 中
"""

# ============ 添加到 server.py 的导入部分 ============
from flask import app

from voiceprint_service import voiceprint_service
from voiceprint_realtime_transcriber import VoiceprintRealtimeTranscriberV2


# ============ 添加到 server.py 的路由部分 ============

@app.post("/api/voiceprint/register")
async def register_voiceprint(
    username: str = Form(...),
    audio_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    注册用户声纹

    用户需要录制 3-5 秒清晰的语音样本
    建议让用户朗读一段固定文本，如："我是XXX，正在注册声纹"
    """
    try:
        # 验证用户是否存在
        user = resolve_user_by_identifier(db, username)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 保存上传的音频文件
        audio_dir = os.path.join(ROOT_DIR, "storage", "voiceprint_samples")
        os.makedirs(audio_dir, exist_ok=True)

        audio_filename = f"{username}_{int(time.time())}.wav"
        audio_path = os.path.join(audio_dir, audio_filename)

        with open(audio_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)

        # 注册声纹
        success = voiceprint_service.register_user(username, audio_path)

        if success:
            return {
                "success": True,
                "message": "声纹注册成功",
                "username": username
            }
        else:
            return {
                "success": False,
                "message": "声纹注册失败，请确保音频清晰且时长足够"
            }

    except Exception as e:
        print(f"[ERROR] 声纹注册失败: {e}")
        return {"success": False, "message": f"注册失败: {str(e)}"}


@app.get("/api/voiceprint/status/{username}")
async def get_voiceprint_status(username: str, db: Session = Depends(get_db)):
    """查询用户声纹注册状态"""
    user = resolve_user_by_identifier(db, username)
    if not user:
        return {"success": False, "message": "用户不存在"}

    is_registered = voiceprint_service.is_user_registered(username)

    return {
        "success": True,
        "username": username,
        "is_registered": is_registered,
        "voiceprint_enabled": True  # 系统是否启用声纹功能
    }


@app.delete("/api/voiceprint/unregister/{username}")
async def unregister_voiceprint(username: str, db: Session = Depends(get_db)):
    """删除用户声纹"""
    user = resolve_user_by_identifier(db, username)
    if not user:
        return {"success": False, "message": "用户不存在"}

    success = voiceprint_service.unregister_user(username)

    if success:
        return {"success": True, "message": "声纹已删除"}
    else:
        return {"success": False, "message": "该用户未注册声纹"}


@app.post("/api/voiceprint/verify")
async def verify_voiceprint(
    username: str = Form(...),
    audio_file: UploadFile = File(...),
    threshold: float = Form(0.25)
):
    """
    验证音频是否为指定用户

    用于测试声纹识别效果
    """
    try:
        # 保存临时音频
        temp_dir = os.path.join(ROOT_DIR, "storage", "temp")
        os.makedirs(temp_dir, exist_ok=True)

        temp_path = os.path.join(temp_dir, f"verify_{int(time.time())}.wav")
        with open(temp_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)

        # 验证声纹
        result = voiceprint_service.verify_speaker(username, temp_path, threshold)

        # 删除临时文件
        try:
            os.remove(temp_path)
        except:
            pass

        return {
            "success": True,
            "username": username,
            "is_match": result.get("is_match"),
            "confidence": result.get("confidence"),
            "distance": result.get("distance"),
            "threshold": threshold
        }

    except Exception as e:
        print(f"[ERROR] 声纹验证失败: {e}")
        return {"success": False, "message": f"验证失败: {str(e)}"}


@app.post("/api/voiceprint/identify")
async def identify_speaker(
    audio_file: UploadFile = File(...),
    top_k: int = Form(3)
):
    """
    识别音频中的说话人

    从所有注册用户中找出最匹配的用户
    """
    try:
        # 保存临时音频
        temp_dir = os.path.join(ROOT_DIR, "storage", "temp")
        os.makedirs(temp_dir, exist_ok=True)

        temp_path = os.path.join(temp_dir, f"identify_{int(time.time())}.wav")
        with open(temp_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)

        # 识别说话人
        results = voiceprint_service.identify_speaker(temp_path, top_k)

        # 删除临时文件
        try:
            os.remove(temp_path)
        except:
            pass

        return {
            "success": True,
            "candidates": results
        }

    except Exception as e:
        print(f"[ERROR] 说话人识别失败: {e}")
        return {"success": False, "message": f"识别失败: {str(e)}"}


# ============ 修改 ASRSessionManager 使用声纹验证 ============

class ASRSessionManager:
    """修改后的 ASR 会话管理器，支持声纹验证"""

    def __init__(self):
        self.sessions = {}
        self.meeting_connections = {}

    async def start_session(self, username, meeting_id, client_ws, enable_voiceprint=True):
        """
        启动 ASR 会话，支持声纹验证

        Args:
            enable_voiceprint: 是否启用声纹验证（默认启用）
        """
        key = (meeting_id, username)

        if meeting_id not in self.meeting_connections:
            self.meeting_connections[meeting_id] = {}
        self.meeting_connections[meeting_id][username] = client_ws

        loop = asyncio.get_running_loop()

        def on_partial(text):
            asyncio.run_coroutine_threadsafe(
                self._broadcast_to_meeting(meeting_id, {
                    "type": "asr_partial",
                    "username": username,
                    "text": text
                }),
                loop
            )

        def on_final(text):
            asyncio.run_coroutine_threadsafe(
                self._handle_final_result(meeting_id, username, text),
                loop
            )

        def on_error(msg):
            print(f"[ASR ERROR] {username}@meeting{meeting_id}: {msg}")

        # 检查是否启用声纹验证
        if enable_voiceprint and voiceprint_service.is_user_registered(username):
            # 使用带声纹验证的转写器
            transcriber = VoiceprintRealtimeTranscriberV2(
                username=username,
                on_partial=on_partial,
                on_final=on_final,
                on_error=on_error,
                voiceprint_threshold=0.25,  # 可配置
                enable_voiceprint=True
            )
            print(f"[ASR] 启用声纹验证: {username}@meeting{meeting_id}")
        else:
            # 使用标准转写器
            from ai_core import RealtimeTranscriber
            transcriber = RealtimeTranscriber(
                on_partial=on_partial,
                on_final=on_final,
                on_error=on_error
            )
            if enable_voiceprint:
                print(f"[ASR] 用户 {username} 未注册声纹，使用标准模式")

        success = transcriber.start()
        if success:
            self.sessions[key] = transcriber
            print(f"[ASR] 实时会话已启动: {username}@meeting{meeting_id}")
        else:
            print(f"[ASR ERROR] 会话启动失败: {username}@meeting{meeting_id}")

        return success

    # ... 其他方法保持不变 ...
