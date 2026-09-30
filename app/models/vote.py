"""观点投票。

阶段 3.1：本文件的类定义从仓库根的 `database.py` **逐字搬移**而来，只换了 import 头。
字段、默认值、注释（含字面量 `[EMOJI]` 占位符）一律未动——搬移与校验过程见
`tools/split_models_3_1.py`，可随时用 `--verify` 重跑。
"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String

from app.models.base import Base


# [EMOJI]: [EMOJI]
class ViewpointVote(Base):
    __tablename__ = "viewpoint_votes"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    vote_session_id = Column(String(50), index=True)  # [EMOJI]ID
    viewpoints = Column(JSON, nullable=False)  # [EMOJI]
    votes = Column(JSON, default=dict)  # {viewpoint_id: [user_ids]}
    status = Column(String(20), default="active")  # active/closed
    winner_viewpoint_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime, nullable=True)
