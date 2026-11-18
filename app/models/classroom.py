"""课堂会话与其成员在场状态。"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.meeting_state import CREATED
from app.models.base import Base


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'running', 'ended')",
            name="CK_meetings_status",
        ),
    )
    id = Column(Integer, primary_key=True, index=True)
    class_code = Column(String(50), unique=True, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"))
    topic = Column(Text, nullable=False)
    reference_materials = Column(JSON, nullable=True)  # [EMOJI]
    teaching_design = Column(JSON, nullable=True)  # AI[EMOJI]
    knowledge_points = Column(JSON, default=list)  # [EMOJI]
    template_path = Column(String(500), nullable=True)  # [EMOJI]
    status = Column(String(20), default=CREATED, nullable=False)  # created/running/ended
    created_at = Column(DateTime, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)


# [EMOJI]: [EMOJI]([EMOJI])
class MemberConnection(Base):
    __tablename__ = "member_connections"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    username = Column(String(50))
    is_online = Column(Integer, default=1)  # 1[EMOJI]/0[EMOJI]
    video_enabled = Column(Integer, default=1)
    audio_enabled = Column(Integer, default=1)
    last_heartbeat = Column(DateTime, default=datetime.now)
    joined_at = Column(DateTime, default=datetime.now)
