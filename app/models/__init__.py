"""ORM 模型包（阶段 3.1 从仓库根的 `database.py` 拆出）。

**导入本包即完成全部模型的注册**——`Base.metadata` 因此总是完整的。
这一点是必需的：`declarative_base()` 只创建一个 `Base`，而模型类分散在多个
模块里，只有全部导入过，`metadata.tables` 才包含全部表。

阶段 3.2 起这条性质**不再由 `app.core.database` 顺带保证**（那个文件已不再
导入本包）。需要整份 metadata 的地方必须显式 `import app.models`——
`server.py`、测试的 `create_all()` 都属此类。少写这一句不会报错，
`create_all()` 只会安静地建出一个没有任何表的空 schema。
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
