"""课堂级 Agent 工具使用的只读查询 Service。

数据来源统一走已有的只读 Service：
- 发言 / 统计：TranscriptQueryService、ClassStatsService
- 知识图谱 / 目标覆盖：KnowledgeTraceService
- GCA 六指标：gca_service
"""

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models import Meeting
from app.services.class_stats_service import ClassStatsService
from app.services.gca_service import analyze_meeting_metrics
from app.services.knowledge_trace_service import KnowledgeTraceService
from app.services.transcript_query_service import TranscriptQueryService


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
        rows = [
            row
            for row in TranscriptQueryService(db).list_for_meeting(
                meeting_id, limit=limit
            )
            if getattr(row.user, "role", None) != "teacher"
        ]
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
        emotion_distribution = ClassStatsService(db).emotion_counts(meeting_id)
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
            "emotion_count": sum(emotion_distribution.values()),
            "emotion_distribution": emotion_distribution,
            "truncated": len(transcripts) == 1000,
        }

    def get_knowledge(self, db: Session, meeting_id: int) -> dict[str, Any]:
        coverage = KnowledgeTraceService(db).goal_coverage_for_meeting(meeting_id)
        if coverage is None:
            return {"ok": False, "reason": "课堂不存在"}

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        visualization = KnowledgeTraceService(db).visualize(meeting_id)
        graph = (
            visualization["data"]
            if visualization["status"] == "success"
            else {"nodes": [], "links": [], "categories": []}
        )
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "goals": meeting.knowledge_points if meeting else [],
            "covered_goals": [_goal_label(item) for item in coverage["covered"]],
            "untouched_goals": [_goal_label(item) for item in coverage["uncovered"]],
            "coverage_ratio": (
                round(coverage["covered_count"] / coverage["total"], 3)
                if coverage["total"]
                else None
            ),
            "graph": graph,
            "data_gaps": [] if graph.get("nodes") else ["课堂尚无知识图谱"],
        }

    def get_metrics(self, db: Session, meeting_id: int) -> dict[str, Any]:
        result = analyze_meeting_metrics(meeting_id, db)
        ok = result["status"] in {"success", "single_speaker"}
        payload = {
            "ok": ok,
            "meeting_id": meeting_id,
            "layer": "quality",
            "status": result["status"],
            "student_metrics": result["student_metrics"],
            "group_metrics": result["group_metrics"],
            "timeline": result["timeline"],
            "warnings": result["warnings"],
        }
        if not ok:
            payload["reason"] = result.get("error") or result["status"]
        return payload


classroom_agent_service = ClassroomAgentService()
