"""教师查看 Hint 发送记录。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import HintLog, Meeting
from app.services.session_service import SessionContext, require_session

router = APIRouter()


def _iso(value):
    return value.isoformat() if value else None


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
