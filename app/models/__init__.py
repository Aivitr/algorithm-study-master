"""ORM 模型包。

**导入本包即完成全部模型的注册**——`Base.metadata` 因此总是完整的。

需要整份 metadata 的地方必须显式 `import app.models`——`server.py` 与测试里的
`create_all()` 都属此类。
"""

from app.models.base import Base
from app.models.classroom import Meeting, MemberConnection
from app.models.emotion import EmotionLog, MentalHealthAssessment
from app.models.insight import AIInsight
from app.models.knowledge_graph import GraphEdge, GraphNode, KnowledgeGraph
from app.models.learning import Exercise, LearningReport, ReportTemplate, StudentAnswer
from app.models.session import ActiveClassroomSession, UserSession
from app.models.transcript import Transcript
from app.models.user import User
from app.models.vote import ViewpointVote

__all__ = [
    "Base",
    "AIInsight",
    "ActiveClassroomSession",
    "EmotionLog",
    "Exercise",
    "GraphEdge",
    "GraphNode",
    "KnowledgeGraph",
    "LearningReport",
    "Meeting",
    "MemberConnection",
    "MentalHealthAssessment",
    "ReportTemplate",
    "StudentAnswer",
    "Transcript",
    "User",
    "UserSession",
    "ViewpointVote",
]
