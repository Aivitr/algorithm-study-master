"""用户账号（教师 / 学生）。"""

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
