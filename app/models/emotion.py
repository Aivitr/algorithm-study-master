"""情绪记录与心理健康评估。"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy.orm import relationship

from app.models.base import Base


class EmotionLog(Base):
    __tablename__ = "emotion_logs"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    # === [EMOJI] 100 ===
    emotion_type = Column(String(100))
    intensity = Column(Float)
    snapshot_path = Column(String(500))  # [EMOJI]URL[EMOJI]OSS[EMOJI]
    video_url = Column(String(500))      # [EMOJI]URL[EMOJI]OSS[EMOJI]
    video_start_time = Column(Float, default=0)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User")

# [EMOJI]: [EMOJI]
class MentalHealthAssessment(Base):
    __tablename__ = "mental_health_assessments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    risk_level = Column(String(20))  # high/medium/normal
    assessment_data = Column(JSON)  # [EMOJI]
    intervention_time = Column(DateTime, nullable=True)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)

Index('idx_emotion_meeting_user', EmotionLog.meeting_id, EmotionLog.user_id)
