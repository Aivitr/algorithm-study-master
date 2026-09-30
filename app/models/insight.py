"""AI 生成的课堂洞察。

阶段 3.1：本文件的类定义从仓库根的 `database.py` **逐字搬移**而来，只换了 import 头。
字段、默认值、注释（含字面量 `[EMOJI]` 占位符）一律未动——搬移与校验过程见
`tools/split_models_3_1.py`，可随时用 `--verify` 重跑。
"""

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
