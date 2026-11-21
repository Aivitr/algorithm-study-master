"""Role-scoped teacher and student GCA dashboard APIs."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ActiveClassroomSession, Meeting, Transcript
from app.services.gca_service import build_gca_dashboard, build_gca_student_view
from app.services.session_service import SessionContext, require_session

router = APIRouter()


@router.get("/api/gca-dashboard/{meeting_id}")
def get_gca_dashboard(
    meeting_id: int,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="课堂不存在")
    if ctx.user.role != "teacher" or int(meeting.teacher_id) != int(ctx.user.id):
        raise HTTPException(status_code=403, detail="只有本课堂教师可以查看协作分析")
    return build_gca_dashboard(meeting_id, db)


@router.get("/api/gca-student-view/{meeting_id}")
def get_gca_student_view(
    meeting_id: int,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="课堂不存在")
    if ctx.user.role != "student":
        raise HTTPException(status_code=403, detail="该接口仅供学生查看自己的协作数据")

    is_active = (
        db.query(ActiveClassroomSession.id)
        .filter(
            ActiveClassroomSession.meeting_id == meeting_id,
            ActiveClassroomSession.user_id == ctx.user.id,
        )
        .first()
        is not None
    )
    has_spoken = (
        db.query(Transcript.id)
        .filter(
            Transcript.meeting_id == meeting_id,
            Transcript.user_id == ctx.user.id,
        )
        .first()
        is not None
    )
    if not is_active and not has_spoken:
        raise HTTPException(status_code=403, detail="你尚未加入该课堂")
    return build_gca_student_view(meeting_id, ctx.user, db)
