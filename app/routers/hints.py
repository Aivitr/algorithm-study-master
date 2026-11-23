"""Hint 发送记录与响应。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ActiveClassroomSession, HintLog, Meeting, Transcript
from app.services.session_service import SessionContext, require_session

router = APIRouter()


class HintResponseRequest(BaseModel):
    response: Literal["acknowledged", "need_help", "dismissed"]


def _iso(value):
    return value.isoformat() if value else None


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
