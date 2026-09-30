import os

from app.core import config  # 先加载 .env，确保 os.getenv 能读到 DATABASE_URL
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# 数据库配置 - 阿里云 RDS SQL Server
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./storage/app.db")

# connect_args 中的 login_timeout 是 pymssql 专有参数。此前无条件传入，
# 导致 DATABASE_URL 指向 sqlite 时 sqlite3.connect() 抛
# TypeError: 'login_timeout' is an invalid keyword argument。
# 现按方言选择——生产（mssql+pymssql）传入的实参与此前完全一致。
_IS_MSSQL = SQLALCHEMY_DATABASE_URL.startswith("mssql")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    poolclass=NullPool,  # 无连接池
    connect_args={'timeout': 10, 'login_timeout': 10} if _IS_MSSQL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 阶段 3.1：模型已搬到 `app/models/`。这里原样转出，使 `from database import User` 这类
# 既有写法继续有效——本步据此可以声称「调用方零改动」。这层转发是**临时的**，
# 阶段 3.2 搬迁本文件时会连同这些调用方一起收拢，届时删除。
from app.models import (
    User,
    Meeting,
    MemberConnection,
    Transcript,
    EmotionLog,
    MentalHealthAssessment,
    AIInsight,
    KnowledgeGraph,
    GraphNode,
    GraphEdge,
    LearningReport,
    Exercise,
    StudentAnswer,
    ReportTemplate,
    ViewpointVote,
)
from app.models.base import Base  # noqa: F401  （Base 的公开位置未变）

def _ensure_transcripts_columns():
    """Patch legacy transcript tables with research enhancement fields."""
    try:
        inspector = inspect(engine)
        if "transcripts" not in inspector.get_table_names():
            return

        columns = {col.get("name") for col in inspector.get_columns("transcripts")}
        ddl_list = []

        if "binding_source" not in columns:
            ddl_list.append("ALTER TABLE transcripts ADD binding_source NVARCHAR(100) NULL")
        if "binding_confidence" not in columns:
            ddl_list.append("ALTER TABLE transcripts ADD binding_confidence FLOAT NULL")
        if "identity_review_status" not in columns:
            ddl_list.append("ALTER TABLE transcripts ADD identity_review_status NVARCHAR(50) NULL")
        if "identity_review_note" not in columns:
            ddl_list.append("ALTER TABLE transcripts ADD identity_review_note NVARCHAR(1000) NULL")
        if "cross_modal_consistency" not in columns:
            ddl_list.append("ALTER TABLE transcripts ADD cross_modal_consistency FLOAT NULL")

        if ddl_list:
            with engine.begin() as conn:
                for ddl in ddl_list:
                    conn.execute(text(ddl))
            print(f"[DB_MIGRATION] transcripts patched with {len(ddl_list)} research columns")
    except Exception as e:
        print(f"[DB_MIGRATION] transcripts patch skipped: {e}")


_ensure_transcripts_columns()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
