"""Hint 发送记录、教师确认与学生响应。"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ActiveClassroomSession, HintLog, Meeting, Transcript, User
from app.realtime.registry import manager
from app.services.hint_candidate_service import (
    SEND_RATE_LIMIT,
    count_sent_recent,
)
from app.services.session_service import SessionContext, require_session

router = APIRouter()


class HintResponseRequest(BaseModel):
    response: Literal["acknowledged", "need_help", "dismissed"]


def _iso(value):
    return value.isoformat() if value else None


def _teacher_row(db: Session, ctx: SessionContext, hint_id: int) -> HintLog:
    row = db.query(HintLog).filter(HintLog.id == hint_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="提示不存在")
    meeting = db.query(Meeting).filter(Meeting.id == row.meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="课堂不存在")
    if ctx.user.role != "teacher" or int(meeting.teacher_id) != int(ctx.user.id):
        raise HTTPException(status_code=403, detail="只有本课堂教师可以操作提示")
    return row


def _payload(row: HintLog) -> dict:
    return {
        "type": "topic_suggestion",
        "target": "personal" if row.target_type == "student" else "all",
        "hint_id": row.id,
        "suggestion": row.text,
        "reason": "low_participation" if row.target_type == "student" else "group_silence",
        "trigger_reason": row.trigger_reason,
        "evidence": row.evidence or {},
    }


@router.post("/api/hint-logs/{hint_id}/send")
async def send_hint(
    hint_id: int,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    row = _teacher_row(db, ctx, hint_id)
    if row.status != "candidate":
        raise HTTPException(status_code=409, detail="该提示已处理")
    if count_sent_recent(db, int(row.meeting_id)) >= SEND_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="10 分钟内提示条数已达上限")

    if row.target_type == "student":
        try:
            target_id = int(row.target_user_id or "")
        except ValueError:
            raise HTTPException(status_code=409, detail="目标学生无效") from None
        user = db.query(User).filter(User.id == target_id).first()
        if user is None:
            raise HTTPException(status_code=409, detail="目标学生已不存在")
        await manager.send_to_user(row.meeting_id, user.username, _payload(row))
    else:
        await manager.broadcast_to_meeting(row.meeting_id, _payload(row))

    row.status = "sent"  # type: ignore[assignment]
    row.sent_at = datetime.now()  # type: ignore[assignment]
    row.created_by = int(ctx.user.id)  # type: ignore[assignment]
    db.commit()
    return {"status": "success", "hint_id": row.id, "sent_at": _iso(row.sent_at)}


@router.post("/api/hint-logs/{hint_id}/ignore")
def ignore_hint(
    hint_id: int,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    row = _teacher_row(db, ctx, hint_id)
    if row.status != "candidate":
        raise HTTPException(status_code=409, detail="该提示已处理")
    row.status = "ignored"  # type: ignore[assignment]
    row.created_by = int(ctx.user.id)  # type: ignore[assignment]
    db.commit()
    return {"status": "success", "hint_id": row.id, "hint_status": "ignored"}


@router.post("/api/hint-logs/{hint_id}/response")
def respond_hint(
    hint_id: int,
    payload: HintResponseRequest,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    row = db.query(HintLog).filter(HintLog.id == hint_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="提示不存在")
    if row.status != "sent":
        raise HTTPException(status_code=409, detail="提示尚未发送")
    if ctx.user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以回应提示")

    if row.target_type == "student":
        if str(ctx.user.id) != str(row.target_user_id):
            raise HTTPException(status_code=403, detail="只能回应发给自己的提示")
    else:
        is_participant = (
            db.query(ActiveClassroomSession.id)
            .filter(
                ActiveClassroomSession.meeting_id == row.meeting_id,
                ActiveClassroomSession.user_id == ctx.user.id,
            )
            .first()
            is not None
            or db.query(Transcript.id)
            .filter(
                Transcript.meeting_id == row.meeting_id,
                Transcript.user_id == ctx.user.id,
            )
            .first()
            is not None
        )
        if not is_participant:
            raise HTTPException(status_code=403, detail="你尚未加入该课堂")

    row.response = payload.response  # type: ignore[assignment]
    db.commit()
    return {"status": "success", "hint_id": hint_id, "response": payload.response}


@router.get("/api/hint-logs/{meeting_id}")
def list_hint_logs(
    meeting_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="课堂不存在")
    if ctx.user.role != "teacher" or int(meeting.teacher_id) != int(ctx.user.id):
        raise HTTPException(status_code=403, detail="只有本课堂教师可以查看提示记录")

    rows = (
        db.query(HintLog)
        .filter(HintLog.meeting_id == meeting_id)
        .order_by(HintLog.id.desc())
        .limit(limit)
        .all()
    )
    user_ids = {
        int(row.target_user_id)
        for row in rows
        if row.target_user_id and str(row.target_user_id).isdigit()
    }
    names = (
        {str(user.id): user.username for user in db.query(User).filter(User.id.in_(user_ids))}
        if user_ids
        else {}
    )
    return {
        "status": "success",
        "meeting_id": meeting_id,
        "logs": [
            {
                "id": row.id,
                "evidence_id": f"H#{row.id}",
                "dedupe_key": row.dedupe_key,
                "hint_type": row.hint_type,
                "target_type": row.target_type,
                "target_user_id": row.target_user_id,
                "target_name": names.get(str(row.target_user_id)),
                "trigger_reason": row.trigger_reason,
                "evidence": row.evidence or {},
                "evidence_ids": row.evidence_ids or [],
                "text": row.text,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "status": row.status,
                "created_by": row.created_by,
                "sent_at": _iso(row.sent_at),
                "created_at": _iso(row.created_at),
                "response": row.response,
            }
            for row in rows
        ],
    }
