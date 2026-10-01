"""课堂进行中的教师操作域。

本组 5 条，都是"一堂课进行中教师端要触发的动作"：

    GET  /api/agora-token          取 RTC 令牌/配置
    POST /api/end-class            结束课堂
    POST /api/suggest-topic        学生"不知道说什么"时推话题建议（调 LLM）
    POST /api/quick-decompose      一键分解：跳过聚类投票直接生成子任务
    POST /api/cluster-viewpoints   聚类学生观点

本组带走 Agora 那一小块配件：常量 `DEFAULT_AGORA_APP_ID` 与
`_normalize_agora_auth_mode` / `_get_agora_rtc_config` 两个私有辅助，它们只服务
`/api/agora-token` 一条路由。

`manager` 取自 `app.realtime.registry`（与 `server.manager` 是同一个对象）；
`NO_CACHE_HEADERS` 取自 `app.core.http`（令牌类响应必须每次现取）。

`/api/agora-token` 的响应随 `.env` 里的 `AGORA_*` 变化，**不在**行为基线的
覆盖范围内——见 `docs/route-inventory.md`。
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import NO_CACHE_HEADERS
from app.models import Meeting, Transcript, User, ViewpointVote
from app.realtime.registry import manager
from app.services.llm_service import llm
from app.services.research_runtime import research_runtime

router = APIRouter()

@router.get("/api/agora-token")
async def get_agora_token(channel: str, uid: str = "0", _: Optional[str] = None, response: Response = None):
    """返回前端加入声网频道所需的 RTC 配置与 Token（如启用）。"""
    if response is not None:
        for key, value in NO_CACHE_HEADERS.items():
            response.headers[key] = value

    agora_config = _get_agora_rtc_config()
    response = {
        "appId": agora_config["app_id"],
        "authMode": agora_config["auth_mode"],
        "useToken": agora_config["use_token"],
        "token": None,
    }

    if agora_config.get("error"):
        response["error"] = agora_config["error"]
        return response

    if not agora_config["use_token"]:
        return response

    try:
        from agora_token_builder import RtcTokenBuilder
        import time as _time

        expire_seconds = 86400  # 24小时
        current_ts = int(_time.time())
        privilege_expired_ts = current_ts + expire_seconds
        # 使用 buildTokenWithAccount 支持字符串UID
        token = RtcTokenBuilder.buildTokenWithAccount(
            agora_config["app_id"], agora_config["app_certificate"],
            channel, uid, 1, privilege_expired_ts
        )
        response["token"] = token
        response["expireAt"] = privilege_expired_ts
        return response
    except ModuleNotFoundError as e:
        print(f"[ERROR] Agora token 依赖缺失: {e}")
        response["error"] = "服务器缺少 agora_token_builder 依赖，请安装后重试"
        return response
    except Exception as e:
        print(f"[ERROR] 生成Agora Token失败: {e}")
        response["error"] = f"生成Agora Token失败: {str(e)}"
        return response


@router.post("/api/end-class")
async def end_class(
    meeting_id: int = Form(...),
    username: str = Form(...),
    db: Session = Depends(get_db)
):
    """教师结束课堂"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        # 验证是教师
        user = db.query(User).filter(User.student_id == username).first()
        if not user or user.role != "teacher":
            return {"status": "error", "message": "只有教师可以结束课堂"}

        # 更新课堂状态
        meeting.status = "ended"
        db.commit()

        # 广播课堂结束通知到所有在线成员
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "class_ended",
            "message": "教师已结束本次课堂",
            "teacher": user.username
        })

        # 断开所有成员的WebSocket连接
        if meeting_id in manager.meeting_connections:
            for member_ws in list(manager.meeting_connections[meeting_id].values()):
                try:
                    await member_ws.close()
                except:
                    pass
            manager.meeting_connections.pop(meeting_id, None)

        print(f"[OK] 课堂 {meeting_id} 已被教师 {username} 结束")
        return {"status": "success", "message": "课堂已结束"}
    except Exception as e:
        print(f"[ERROR] end-class: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/suggest-topic")
async def suggest_topic(meeting_id: int = Form(...), db: Session = Depends(get_db)):
    """当学生说'不知道该说什么'时，AI自动总结当前情况并推送话题建议"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "会议不存在"}

        # 获取最近的发言记录
        recent = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.created_at.desc()).limit(15).all()

        transcripts_text = "\n".join([f"{t.user.username}: {t.content}" for t in recent if t.content]) if recent else "暂无发言"

        # 获取当前目标
        goals = meeting.knowledge_points or []
        goals_text = "\n".join([f"- {g.get('desc', '')} ({g.get('status', 'pending')})" for g in goals[:8]]) if goals else "暂无目标"

        prompt = f"""你是课堂讨论助手。学生们在讨论中遇到了瓶颈，不知道接下来该讨论什么。

课程主题：{meeting.topic}
当前教学目标：
{goals_text}

最近课堂发言：
{transcripts_text}

请根据以上信息：
1. 简要总结目前的讨论进展（1句话）
2. 提出2-3个具体的、有启发性的讨论话题或问题，帮助学生继续深入讨论

要求：话题要具体、有针对性，能激发思考。总字数不超过150字。直接输出内容，不要加标题。"""

        result = llm.client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        suggestion = result.choices[0].message.content.strip()
        return {"status": "success", "suggestion": suggestion}
    except Exception as e:
        print(f"[ERROR] suggest-topic: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/quick-decompose")
async def quick_decompose(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """一键分解：跳过聚类投票，直接分析发言并生成子任务"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        transcripts = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id).all()

        if len(transcripts) < 1:
            return {"status": "error", "message": "暂无发言记录"}

        all_transcripts = [{
            "username": t.user.username,
            "content": t.content
        } for t in transcripts]

        # 一次 LLM 调用完成分析+分解
        result = llm.quick_decompose(
            all_transcripts, meeting.topic, meeting.knowledge_points or []
        )

        # 更新目标列表
        new_goals = list(meeting.knowledge_points or [])
        for sg in result.get("sub_goals", []):
            new_goals.append({
                "id": len(new_goals) + 1,
                "desc": f"[深入探讨] {sg['desc']}",
                "status": "pending",
                "parent_viewpoint": result.get("main_viewpoint", "")
            })
        meeting.knowledge_points = new_goals
        db.commit()

        # 广播更新到所有客户端
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "goals_updated",
            "updated_goals": meeting.knowledge_points,
            "main_viewpoint": result.get("main_viewpoint", ""),
            "sub_goals": result.get("sub_goals", []),
            "guidance": result.get("guidance", "")
        })

        return {
            "status": "success",
            "main_viewpoint": result.get("main_viewpoint", ""),
            "sub_goals": result.get("sub_goals", []),
            "guidance": result.get("guidance", ""),
            "updated_goals": meeting.knowledge_points
        }
    except Exception as e:
        print(f"[ERROR] quick-decompose: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@router.post("/api/cluster-viewpoints")
async def cluster_viewpoints(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """聚类学生观点"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        # 获取所有发言
        transcripts = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id).all()

        if len(transcripts) < 3:
            return {"status": "error", "message": "发言太少，无法聚类"}

        # 构建对话数据
        all_transcripts = [{
            "username": t.user.username,
            "content": t.content
        } for t in transcripts]

        # 调用LLM聚类观点
        result = llm.cluster_viewpoints(all_transcripts, meeting.topic)
        if research_runtime.research_algorithms_active:
            result = research_runtime.refine_viewpoint_clusters(all_transcripts, meeting.topic, result)

        # 创建投票记录
        import uuid
        vote_session_id = str(uuid.uuid4())[:8]
        vote_record = ViewpointVote(
            meeting_id=meeting_id,
            vote_session_id=vote_session_id,
            viewpoints=result.get("viewpoints", []),
            votes={str(vp["id"]): [] for vp in result.get("viewpoints", [])},
            status="active"
        )
        db.add(vote_record)
        db.commit()
        db.refresh(vote_record)

        # 广播投票开始
        vote_payload = {
            "type": "vote_start",
            "vote_id": vote_record.id,
            "vote_session_id": vote_session_id,
            "viewpoints": result.get("viewpoints", []),
            "summary": result.get("summary", ""),
            "suggested_next": result.get("suggested_next", ""),
            "votes": vote_record.votes,
            "online_members": manager.get_online_members(meeting_id)
        }
        if research_runtime.research_algorithms_active:
            vote_payload["research"] = result.get("research", {})
        await manager.broadcast_to_meeting(meeting_id, vote_payload)

        response_payload = {
            "status": "success",
            "vote_id": vote_record.id,
            "viewpoints": result.get("viewpoints", []),
            "summary": result.get("summary", ""),
            "suggested_next": result.get("suggested_next", "")
        }
        if research_runtime.research_algorithms_active:
            response_payload["research"] = result.get("research", {})
        return response_payload
    except Exception as e:
        print(f"[ERROR] 观点聚类失败: {e}")
        return {"status": "error", "message": str(e)}


# ===== 声网 Agora Token 生成 =====
DEFAULT_AGORA_APP_ID = "d3144900be6843d8a8c14271f1da8cdb"


def _normalize_agora_auth_mode(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if raw in ("appid", "app_id", "static", "null", "none", "no_token"):
        return "appid"
    if raw in ("token", "dynamic", "certificate", "app_certificate"):
        return "token"
    return "auto"


def _get_agora_rtc_config():
    app_id = (os.getenv("AGORA_APP_ID") or DEFAULT_AGORA_APP_ID).strip()
    app_certificate = (os.getenv("AGORA_APP_CERTIFICATE") or "").strip()
    configured_mode = _normalize_agora_auth_mode(os.getenv("AGORA_AUTH_MODE"))
    auth_mode = configured_mode if configured_mode != "auto" else ("token" if app_certificate else "appid")

    config = {
        "app_id": app_id,
        "app_certificate": app_certificate,
        "auth_mode": auth_mode,
        "use_token": auth_mode == "token",
    }

    if not app_id:
        config["error"] = "Agora App ID 未配置"
    elif auth_mode == "token" and not app_certificate:
        config["error"] = "Agora 当前配置为动态 Token 模式，但服务端未配置 AGORA_APP_CERTIFICATE"

    return config
