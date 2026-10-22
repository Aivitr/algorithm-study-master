"""知识点覆盖与知识图谱的只读查询。

给 HTTP 路由与 Agent Tool 共用：
  - visualize()              现有图谱的可视化数据（缺失时返回 empty 形状）
  - goal_coverage()          学习目标的覆盖情况（按 status == "done" 划分）
  - build_from_transcripts()  图谱缺失时用现有 kg_service 现场构建
                              —— 只返回结果，**不落库、不提交事务**

本类是**只读**的。
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import KnowledgeGraph, Meeting
from app.services.knowledge_graph_service import kg_service
from app.services.transcript_query_service import TranscriptQueryService


class KnowledgeTraceService:
    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def get_graph_data(self, meeting_id: int) -> Optional[Dict[str, Any]]:
        row = (
            self.db.query(KnowledgeGraph)
            .filter(KnowledgeGraph.meeting_id == meeting_id)
            .first()
        )
        return row.graph_data if row else None

    def visualize(self, meeting_id: int) -> Dict[str, Any]:
        """与 `GET /api/knowledge-graph/{meeting_id}` 的返回结构保持一致。"""
        graph = self.get_graph_data(meeting_id)
        if not graph:
            return {"status": "empty", "data": {"nodes": [], "edges": []}}
        return {
            "status": "success",
            "data": kg_service.generate_graph_visualization_data(graph),
        }

    @staticmethod
    def goal_coverage(goals: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """按 `status == "done"` 划分已覆盖 / 未覆盖的学习目标。"""
        goals = goals or []
        covered = [g for g in goals if isinstance(g, dict) and g.get("status") == "done"]
        uncovered = [
            g for g in goals if not (isinstance(g, dict) and g.get("status") == "done")
        ]
        return {
            "total": len(goals),
            "covered_count": len(covered),
            "uncovered_count": len(uncovered),
            "covered": covered,
            "uncovered": uncovered,
        }

    def goal_coverage_for_meeting(self, meeting_id: int) -> Optional[Dict[str, Any]]:
        meeting = self.db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return None
        return self.goal_coverage(meeting.knowledge_points)

    def build_from_transcripts(
        self, meeting_id: int, limit: int = 10
    ) -> Optional[Dict[str, Any]]:
        """图谱缺失时现场构建：复用 kg_service，不写入数据库。

        返回 None 表示课堂不存在或没有可用的发言。
        """
        meeting = self.db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return None

        transcripts = TranscriptQueryService(self.db).recent_for_meeting(
            meeting_id, limit=limit
        )
        if not transcripts:
            return None

        conversations = [
            {"username": t.user.username, "content": t.content}
            for t in reversed(transcripts)
        ]
        return kg_service.extract_concepts_from_conversation(
            topic=meeting.topic,
            conversations=conversations,
            existing_graph=self.get_graph_data(meeting_id),
        )
