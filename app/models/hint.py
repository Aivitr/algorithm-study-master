"""Hint 发送记录。"""

from datetime import datetime

from sqlalchemy import JSON, NVARCHAR, Column, DateTime, ForeignKey, Index, Integer

from app.models.base import Base


class HintLog(Base):
    __tablename__ = "hint_logs"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    dedupe_key = Column(NVARCHAR(200), nullable=False)
    hint_type = Column(NVARCHAR(30), nullable=False)
    target_type = Column(NVARCHAR(20), nullable=False)
    target_user_id = Column(NVARCHAR(50))
    trigger_reason = Column(NVARCHAR(2000))
    evidence = Column(JSON, default=dict)
    evidence_ids = Column(JSON, default=list)
    text = Column(NVARCHAR(2000))
    model = Column(NVARCHAR(50))
    prompt_version = Column(NVARCHAR(30))
    status = Column(NVARCHAR(20), nullable=False, default="sent")
    created_by = Column(Integer, ForeignKey("users.id"))
    sent_at = Column(DateTime)
    response = Column(NVARCHAR(2000))
    created_at = Column(DateTime, default=datetime.now)


Index("idx_hint_logs_meeting_created", HintLog.meeting_id, HintLog.created_at)
