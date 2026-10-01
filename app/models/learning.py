"""学习报告、练习题、学生作答、报告模板。"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.dialects.mssql import NVARCHAR

from app.models.base import Base


# [EMOJI]: [EMOJI]
class LearningReport(Base):
    __tablename__ = "learning_reports"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    report_data = Column(JSON, nullable=False)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)

# [EMOJI]: [EMOJI]
class Exercise(Base):
    __tablename__ = "exercises"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("learning_reports.id"), index=True)
    # 使用 NVARCHAR 存储中文/Unicode，避免导出/展示时出现乱码
    question = Column(NVARCHAR(4000), nullable=False)
    question_type = Column(NVARCHAR(50), nullable=True)  # 题型（选择题/填空题/简答题...）
    options = Column(JSON, nullable=True)  # [EMOJI]
    answer = Column(NVARCHAR(2000), nullable=True)  # 正确答案
    knowledge_tag = Column(NVARCHAR(200), nullable=True)  # 对应知识点
    difficulty = Column(Float)  # [EMOJI]0-1
    estimated_time = Column(Integer)  # [EMOJI]([EMOJI])

# [EMOJI]: [EMOJI]
class StudentAnswer(Base):
    __tablename__ = "student_answers"
    id = Column(Integer, primary_key=True, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    answer_content = Column(Text)
    is_correct = Column(Integer, nullable=True)  # 1[EMOJI]/0[EMOJI]/null[EMOJI]
    submitted_at = Column(DateTime, default=datetime.now)

# [EMOJI]: [EMOJI]
class ReportTemplate(Base):
    __tablename__ = "report_templates"
    id = Column(Integer, primary_key=True, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), index=True)
    filename = Column(String(200), nullable=False)  # [EMOJI]
    filepath = Column(String(500), nullable=False)  # [EMOJI]
    is_default = Column(Integer, default=0)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)

Index('idx_exercise_report', Exercise.report_id)
