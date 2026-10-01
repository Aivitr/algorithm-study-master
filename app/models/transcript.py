"""课堂转写文本（含研究增强的跨模态绑定字段）。"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.dialects.mssql import NVARCHAR
from sqlalchemy.orm import relationship

from app.models.base import Base


class Transcript(Base):
    __tablename__ = "transcripts"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(NVARCHAR(4000))  # NVARCHAR 正确存储中文/Unicode，避免乱码
    audio_file_path = Column(String(500))
    relevance_score = Column(Integer, default=0)
    quality_score = Column(Integer, default=0)  # [EMOJI](0-100)
    quality_feedback = Column(NVARCHAR(1000), nullable=True)  # NVARCHAR 支持中文反馈
    # === [EMOJI] 100 ===
    emotion_tag = Column(NVARCHAR(100), nullable=True)
    body_action = Column(NVARCHAR(100), nullable=True)
    audio_tone = Column(NVARCHAR(100), nullable=True)
    binding_source = Column(NVARCHAR(100), nullable=True)
    binding_confidence = Column(Float, nullable=True)
    identity_review_status = Column(NVARCHAR(50), nullable=True)
    identity_review_note = Column(NVARCHAR(1000), nullable=True)
    cross_modal_consistency = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.now)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User")

Index('idx_transcript_meeting_user', Transcript.meeting_id, Transcript.user_id)
