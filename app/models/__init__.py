"""ORM 模型包。

**导入本包即完成全部模型的注册**——`Base.metadata` 因此总是完整的。

需要整份 metadata 的地方必须显式 `import app.models`——`server.py` 与测试里的
`create_all()` 都属此类。
"""

from app.models.base import Base

from app.models.user import User
from app.models.classroom import Meeting
from app.models.classroom import MemberConnection
from app.models.transcript import Transcript
from app.models.emotion import EmotionLog
from app.models.emotion import MentalHealthAssessment
from app.models.insight import AIInsight
from app.models.knowledge_graph import KnowledgeGraph
from app.models.knowledge_graph import GraphNode
from app.models.knowledge_graph import GraphEdge
from app.models.learning import LearningReport
from app.models.learning import Exercise
from app.models.learning import StudentAnswer
from app.models.learning import ReportTemplate
from app.models.vote import ViewpointVote

__all__ = [
    "Base",
    "AIInsight",
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
    "ViewpointVote",
]
