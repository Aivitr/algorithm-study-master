import os
import config  # 先加载 .env，确保 os.getenv 能读到 DATABASE_URL
from sqlalchemy import create_engine, Column, Integer, Unicode, UnicodeText, Float, DateTime, ForeignKey, JSON, Index, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.pool import NullPool
from sqlalchemy.dialects.mssql import NVARCHAR
from datetime import datetime

# 数据库配置 - 阿里云 RDS SQL Server
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./storage/app.db")


def _connect_args(url: str) -> dict:
    """按方言构造 connect_args。

    login_timeout 是 pymssql 的专有参数。原先无论方言一律传给它，导致任何
    SQLite 连接在建立时就抛 TypeError: 'login_timeout' is an invalid keyword
    argument for Connection()，于是上面那句"留空回退 SQLite"实际上根本不可用。
    这里按方言分开，SQLite 只传它认识的 timeout。
    """
    if url.startswith("sqlite"):
        return {"timeout": 10}
    if url.startswith("mssql"):
        return {"timeout": 10, "login_timeout": 10}
    return {}


engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    poolclass=NullPool,  # 无连接池
    connect_args=_connect_args(SQLALCHEMY_DATABASE_URL),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ⚠️ 文本列一律用 Unicode / UnicodeText，不要改回 String / Text。
# 在 MSSQL 上 String/Text 会落成 varchar，而 varchar 的编码由库排序规则决定
# （Chinese_PRC_CI_AS 即 GBK 代码页）。pymssql/FreeTDS 对 varchar 不做代码页转换：
#   charset=utf8  → 写入正确，读出来按 Latin-1 解 → 中文乱码
#   charset=cp936 → 读取正常，写入被二次编码 → 中文**不可逆损坏**
# 而 Unicode/UnicodeText 在 MSSQL 上生成 NVARCHAR，在 SQLite 上生成 TEXT，
# 两边都能正确存取中文。这是唯一同时适用于本项目两种方言的写法。

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Unicode(50), unique=True, index=True, nullable=False)  # [EMOJI]/[EMOJI]
    username = Column(Unicode(50), nullable=False)  # [EMOJI]
    password = Column(Unicode(256), nullable=False)  # [EMOJI]([EMOJI],[EMOJI]hash)
    role = Column(Unicode(20), nullable=False, default="student")  # teacher/student
    face_encoding = Column(JSON, nullable=True)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)

class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True, index=True)
    class_code = Column(Unicode(50), unique=True, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"))
    topic = Column(UnicodeText, nullable=False)
    reference_materials = Column(JSON, nullable=True)  # [EMOJI]
    teaching_design = Column(JSON, nullable=True)  # AI[EMOJI]
    knowledge_points = Column(JSON, default=list)  # [EMOJI]
    template_path = Column(Unicode(500), nullable=True)  # [EMOJI]
    status = Column(Unicode(20), default="active")  # active/paused/ended
    created_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime, nullable=True)

class Transcript(Base):
    __tablename__ = "transcripts"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(NVARCHAR(4000))  # NVARCHAR 正确存储中文/Unicode，避免乱码
    audio_file_path = Column(Unicode(500))
    relevance_score = Column(Integer, default=0)
    quality_score = Column(Integer, default=0)  # [EMOJI](0-100)
    quality_feedback = Column(NVARCHAR(1000), nullable=True)  # NVARCHAR 支持中文反馈
    # === [EMOJI] 100 ===
    emotion_tag = Column(NVARCHAR(100), nullable=True)
    body_action = Column(NVARCHAR(100), nullable=True)
    audio_tone = Column(NVARCHAR(100), nullable=True)
    binding_source = Column(NVARCHAR(100), nullable=True)
    binding_confidence = Column(Float, nullable=True)
    identity_review_status = Column(NVARCHAR(50), nullable=True)
    identity_review_note = Column(NVARCHAR(1000), nullable=True)
    cross_modal_consistency = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.now)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User")

class EmotionLog(Base):
    __tablename__ = "emotion_logs"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    # === [EMOJI] 100 ===
    emotion_type = Column(Unicode(100))
    intensity = Column(Float)
    snapshot_path = Column(Unicode(500))  # [EMOJI]URL[EMOJI]OSS[EMOJI]
    video_url = Column(Unicode(500))      # [EMOJI]URL[EMOJI]OSS[EMOJI]
    video_start_time = Column(Float, default=0)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User")

class AIInsight(Base):
    __tablename__ = "ai_insights"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    target_user = Column(Unicode(50))
    content = Column(UnicodeText)
    type = Column(Unicode(20))
    created_at = Column(DateTime, default=datetime.now)

# [EMOJI]: [EMOJI]
class KnowledgeGraph(Base):
    __tablename__ = "knowledge_graphs"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    graph_data = Column(JSON, nullable=False)  # [EMOJI](nodes+edges)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class GraphNode(Base):
    __tablename__ = "graph_nodes"
    id = Column(Integer, primary_key=True, index=True)
    graph_id = Column(Integer, ForeignKey("knowledge_graphs.id"), index=True)
    concept_label = Column(Unicode(200), nullable=False)
    concept_type = Column(Unicode(50))  # [EMOJI]/[EMOJI]/[EMOJI]/[EMOJI]
    frequency = Column(Integer, default=1)
    speakers = Column(JSON)  # [EMOJI]
    meta_info = Column(JSON)  # [EMOJI]([EMOJI])

class GraphEdge(Base):
    __tablename__ = "graph_edges"
    id = Column(Integer, primary_key=True, index=True)
    graph_id = Column(Integer, ForeignKey("knowledge_graphs.id"), index=True)
    source_node_id = Column(Integer, ForeignKey("graph_nodes.id"))
    target_node_id = Column(Integer, ForeignKey("graph_nodes.id"))
    relation_type = Column(Unicode(50))  # [EMOJI]/[EMOJI]/[EMOJI]/[EMOJI]/[EMOJI]
    weight = Column(Float, default=0.5)  # [EMOJI]0-1
    evidence = Column(UnicodeText)  # [EMOJI]

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
    answer_content = Column(UnicodeText)
    is_correct = Column(Integer, nullable=True)  # 1[EMOJI]/0[EMOJI]/null[EMOJI]
    submitted_at = Column(DateTime, default=datetime.now)

# [EMOJI]: [EMOJI]
class MentalHealthAssessment(Base):
    __tablename__ = "mental_health_assessments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    risk_level = Column(Unicode(20))  # high/medium/normal
    assessment_data = Column(JSON)  # [EMOJI]
    intervention_time = Column(DateTime, nullable=True)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)

# [EMOJI]: [EMOJI]
class ViewpointVote(Base):
    __tablename__ = "viewpoint_votes"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    vote_session_id = Column(Unicode(50), index=True)  # [EMOJI]ID
    viewpoints = Column(JSON, nullable=False)  # [EMOJI]
    votes = Column(JSON, default=dict)  # {viewpoint_id: [user_ids]}
    status = Column(Unicode(20), default="active")  # active/closed
    winner_viewpoint_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime, nullable=True)

# [EMOJI]: [EMOJI]([EMOJI])
class MemberConnection(Base):
    __tablename__ = "member_connections"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    username = Column(Unicode(50))
    is_online = Column(Integer, default=1)  # 1[EMOJI]/0[EMOJI]
    video_enabled = Column(Integer, default=1)
    audio_enabled = Column(Integer, default=1)
    last_heartbeat = Column(DateTime, default=datetime.now)
    joined_at = Column(DateTime, default=datetime.now)

# [EMOJI]: [EMOJI]
class ReportTemplate(Base):
    __tablename__ = "report_templates"
    id = Column(Integer, primary_key=True, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), index=True)
    filename = Column(Unicode(200), nullable=False)  # [EMOJI]
    filepath = Column(Unicode(500), nullable=False)  # [EMOJI]
    is_default = Column(Integer, default=0)  # [EMOJI]
    created_at = Column(DateTime, default=datetime.now)

# [EMOJI]
Index('idx_transcript_meeting_user', Transcript.meeting_id, Transcript.user_id)
Index('idx_emotion_meeting_user', EmotionLog.meeting_id, EmotionLog.user_id)
Index('idx_exercise_report', Exercise.report_id)

# [EMOJI]
# try: Base.metadata.create_all(bind=engine)
# except: pass


def _ensure_transcripts_columns():
    """Patch legacy transcript tables with research enhancement fields."""
    # 下面的 DDL 是 MSSQL 专有写法（NVARCHAR / ALTER TABLE ... ADD）。
    # 非 MSSQL 方言下直接跳过——新库由 create_all 建表时这些列本就齐全。
    if engine.dialect.name != "mssql":
        return
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
