"""用户账号（教师 / 学生）。

阶段 3.1：本文件的类定义从仓库根的 `database.py` **逐字搬移**而来，只换了 import 头。
字段、默认值、注释（含字面量 `[EMOJI]` 占位符）一律未动——搬移与校验过程见
`tools/split_models_3_1.py`，可随时用 `--verify` 重跑。
"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(50), unique=True, index=True, nullable=False)  # [EMOJI]/[EMOJI]
    username = Column(String(50), nullable=False)  # [EMOJI]
    password = Column(String(256), nullable=False)  # [EMOJI]([EMOJI],[EMOJI]hash)
    role = Column(String(20), nullable=False, default="student")  # teacher/student
    face_encoding = Column(JSON, nullable=True)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)
