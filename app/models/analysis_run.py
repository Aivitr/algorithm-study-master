"""分析运行观测记录（耗时、token、错误）。"""

from datetime import datetime

from sqlalchemy import JSON, NVARCHAR, Column, DateTime, Float, ForeignKey, Index, Integer

from app.models.base import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    kind = Column(NVARCHAR(30), nullable=False)  # hint_llm / engagement / ...
    source = Column(NVARCHAR(30), nullable=False, default="")
    model = Column(NVARCHAR(50))
    version = Column(NVARCHAR(30))
    status = Column(NVARCHAR(30), nullable=False)
    latency_ms = Column(Integer)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    cost = Column(Float)
    result = Column(JSON, default=dict)
    error = Column(NVARCHAR(2000))
    created_at = Column(DateTime, default=datetime.now)


Index("idx_analysis_runs_meeting_created", AnalysisRun.meeting_id, AnalysisRun.created_at)
