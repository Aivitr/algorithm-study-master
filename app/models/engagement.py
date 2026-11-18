"""三维学习投入曲线（按课堂窗口）。"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Index, Integer, String

from app.models.base import Base


class EngagementCurve(Base):
    __tablename__ = "engagement_curves"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    # 空表示小组级曲线
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    dimension = Column(String(20), nullable=False)  # emotional/behavioral/cognitive
    window_start_second = Column(Float, nullable=False)
    window_end_second = Column(Float, nullable=False)
    metrics = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False)  # ok/insufficient/unavailable
    protocol_version = Column(String(20), nullable=False, default="1.0")
    created_at = Column(DateTime, default=datetime.now)


Index(
    "idx_engagement_meeting_window",
    EngagementCurve.meeting_id,
    EngagementCurve.dimension,
    EngagementCurve.window_start_second,
)
Index(
    "idx_engagement_meeting_user",
    EngagementCurve.meeting_id,
    EngagementCurve.user_id,
)
