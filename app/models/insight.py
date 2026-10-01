"""AI 生成的课堂洞察。"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text

from app.models.base import Base


class AIInsight(Base):
    __tablename__ = "ai_insights"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    target_user = Column(String(50))
    content = Column(Text)
    type = Column(String(20))
    created_at = Column(DateTime, default=datetime.now)
