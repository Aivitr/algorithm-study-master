"""课堂级 Agent 工具使用的只读查询 Service。"""

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models import EmotionLog, KnowledgeGraph, Meeting, Transcript, User
from app.services.knowledge_graph_service import kg_service


def _milliseconds(value: Any) -> int | None:
    return int(value.timestamp() * 1000) if value else None


def _goal_label(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("desc") or item.get("title") or item.get("name") or "").strip()
    return str(item or "").strip()


class ClassroomAgentService:
    def get_transcripts(
        self,
        db: Session,
        meeting_id: int,
        limit: int = 200,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        rows = (
            db.query(Transcript)
            .options(joinedload(Transcript.user))
            .join(Transcript.user)
            .filter(Transcript.meeting_id == meeting_id, User.role != "teacher")
            .order_by(Transcript.created_at.asc(), Transcript.id.asc())
            .limit(limit)
            .all()
        )
        items = [
            {
                "evidence_id": f"T#{row.id}",
                "transcript_id": row.id,
                "speaker": row.user.username if row.user else "",
                "text": row.content or "",
                "timestamp": _milliseconds(row.created_at or row.timestamp),
                "relevance_score": row.relevance_score,
                "quality_score": row.quality_score,
                "emotion": row.emotion_tag,
                "body_action": row.body_action,
                "audio_tone": row.audio_tone,
                "cross_modal_consistency": row.cross_modal_consistency,
            }
            for row in rows
        ]
        return {"ok": True, "meeting_id": meeting_id, "count": len(items), "items": items}

    def get_statistics(self, db: Session, meeting_id: int) -> dict[str, Any]:
        transcripts = self.get_transcripts(db, meeting_id, limit=1000)["items"]
        emotions = (
            db.query(EmotionLog)
            .filter(EmotionLog.meeting_id == meeting_id)
            .order_by(EmotionLog.created_at.asc())
            .all()
        )
        speech_counts = Counter(item["speaker"] for item in transcripts)
        qualities = [
            item["quality_score"]
            for item in transcripts
            if item["quality_score"] is not None
        ]
        interactions = Counter(
            (left["speaker"], right["speaker"])
            for left, right in zip(transcripts, transcripts[1:])
            if left["speaker"] and right["speaker"] and left["speaker"] != right["speaker"]
        )
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "transcript_count": len(transcripts),
            "participant_count": len(speech_counts),
            "speech_counts": dict(speech_counts.most_common()),
            "interaction_count": sum(interactions.values()),
            "interactions": [
                {"from": source, "to": target, "count": count}
                for (source, target), count in interactions.most_common(50)
            ],
            "average_quality": round(sum(qualities) / len(qualities), 2) if qualities else None,
            "quality_sample_size": len(qualities),
            "emotion_count": len(emotions),
            "emotion_distribution": dict(Counter(e.emotion_type or "unknown" for e in emotions)),
            "truncated": len(transcripts) == 1000,
        }

    def get_knowledge(self, db: Session, meeting_id: int) -> dict[str, Any]:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting is None:
            return {"ok": False, "reason": "课堂不存在"}

        goals = meeting.knowledge_points if isinstance(meeting.knowledge_points, list) else []
        goal_labels = [label for item in goals if (label := _goal_label(item))]
        graph = (
            db.query(KnowledgeGraph)
            .filter(KnowledgeGraph.meeting_id == meeting_id)
            .order_by(KnowledgeGraph.id.desc())
            .first()
        )
        visualization = (
            kg_service.generate_graph_visualization_data(graph.graph_data)
            if graph and isinstance(graph.graph_data, dict)
            else {"nodes": [], "links": [], "categories": []}
        )
        node_labels = [
            str(node.get("name") or "").strip()
            for node in visualization.get("nodes", [])
            if str(node.get("name") or "").strip()
        ]
        covered = [
            goal
            for goal in goal_labels
            if any(goal in label or label in goal for label in node_labels)
        ]
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "goals": goals,
            "covered_goals": covered,
            "untouched_goals": [goal for goal in goal_labels if goal not in covered],
            "coverage_ratio": round(len(covered) / len(goal_labels), 3) if goal_labels else None,
            "graph": visualization,
            "data_gaps": [] if graph else ["课堂尚无知识图谱"],
        }


classroom_agent_service = ClassroomAgentService()
