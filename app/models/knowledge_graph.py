"""知识图谱：图、节点、边。"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy import Text

from app.models.base import Base


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
    concept_label = Column(String(200), nullable=False)
    concept_type = Column(String(50))  # [EMOJI]/[EMOJI]/[EMOJI]/[EMOJI]
    frequency = Column(Integer, default=1)
    speakers = Column(JSON)  # [EMOJI]
    meta_info = Column(JSON)  # [EMOJI]([EMOJI])

class GraphEdge(Base):
    __tablename__ = "graph_edges"
    id = Column(Integer, primary_key=True, index=True)
    graph_id = Column(Integer, ForeignKey("knowledge_graphs.id"), index=True)
    source_node_id = Column(Integer, ForeignKey("graph_nodes.id"))
    target_node_id = Column(Integer, ForeignKey("graph_nodes.id"))
    relation_type = Column(String(50))  # [EMOJI]/[EMOJI]/[EMOJI]/[EMOJI]/[EMOJI]
    weight = Column(Float, default=0.5)  # [EMOJI]0-1
    evidence = Column(Text)  # [EMOJI]
