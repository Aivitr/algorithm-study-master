"""报告读取权限：本人或本课堂教师。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import LearningReport, Meeting
from app.services.session_service import SessionContext


def can_view_report(db: Session, ctx: SessionContext, report: LearningReport) -> bool:
    if int(report.user_id) == int(ctx.user.id):
        return True
    if ctx.user.role != "teacher":
        return False
    meeting = db.query(Meeting).filter(Meeting.id == report.meeting_id).first()
    return bool(meeting and int(meeting.teacher_id) == int(ctx.user.id))
