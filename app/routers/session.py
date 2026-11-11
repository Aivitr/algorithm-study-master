"""服务端登录会话、课堂占用锁与登出接口。"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.session_service import (
    ClassroomError,
    SessionContext,
    claim_classroom,
    release_classroom,
    require_session,
    revoke_session,
)

router = APIRouter()


class ClassroomRequest(BaseModel):
    meeting_id: int = Field(gt=0)


@router.get("/api/session/validate")
def validate_session(ctx: SessionContext = Depends(require_session)) -> dict[str, Any]:
    return {
        "status": "success",
        "user": {
            "id": ctx.user.id,
            "student_id": ctx.user.student_id,
            "username": ctx.user.username,
            "role": ctx.user.role,
        },
        "session": {
            "id": ctx.session.id,
            "device_id": ctx.session.device_id,
            "expires_at": ctx.session.expires_at.isoformat() if ctx.session.expires_at else None,
        },
    }


@router.post("/api/classroom/enter")
def enter_classroom(
    payload: ClassroomRequest,
    ctx: SessionContext = Depends(require_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        active = claim_classroom(db, ctx, payload.meeting_id)
    except ClassroomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "status": "success",
        "meeting_id": active.meeting_id,
        "session_id": active.session_id,
        "device_id": active.device_id,
        "claimed_at": active.claimed_at.isoformat() if active.claimed_at else None,
    }


@router.post("/api/classroom/leave")
def leave_classroom(
    payload: ClassroomRequest,
    ctx: SessionContext = Depends(require_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    deleted = release_classroom(db, ctx.session.id, payload.meeting_id)
    return {"status": "success", "released": deleted}


@router.post("/api/logout")
def logout(
    ctx: SessionContext = Depends(require_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    revoke_session(db, ctx.session)
    return {"status": "success", "message": "已退出登录"}
