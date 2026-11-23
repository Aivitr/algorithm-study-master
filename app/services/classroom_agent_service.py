"""课堂级 Agent 工具使用的只读查询 Service。

数据来源统一走已有的只读 Service：
- 发言 / 统计：TranscriptQueryService、ClassStatsService
- 知识图谱 / 目标覆盖：KnowledgeTraceService
- GCA 六指标：gca_service
"""

import json
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AIInsight, EmotionLog, EngagementCurve, HintLog, Meeting
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
            for row in TranscriptQueryService(db).list_for_meeting(meeting_id, limit=limit)
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
                "quality_evidence_id": f"Q#{row.id}",
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
            item["quality_score"] for item in transcripts if item["quality_score"] is not None
        ]
        interactions = Counter(
            (left["speaker"], right["speaker"])
            for left, right in zip(transcripts, transcripts[1:])
            if left["speaker"] and right["speaker"] and left["speaker"] != right["speaker"]
        )
        emotion_distribution = ClassStatsService(db).emotion_counts(meeting_id)
        emotion_rows: list[Any] = list(
            db.scalars(
                select(EmotionLog.id)
                .where(EmotionLog.meeting_id == meeting_id)
                .order_by(EmotionLog.id.desc())
                .limit(100)
            )
        )
        emotion_ids = [f"E#{value}" for value in emotion_rows]
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
            "emotion_evidence_ids": emotion_ids,
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

    def get_engagement(
        self,
        db: Session,
        meeting_id: int,
        dimension: str | None = None,
        user_id: int | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 500))
        query = db.query(EngagementCurve).filter(EngagementCurve.meeting_id == meeting_id)
        if dimension:
            query = query.filter(EngagementCurve.dimension == dimension)
        if user_id is not None:
            query = query.filter(EngagementCurve.user_id == user_id)
        rows = (
            query.order_by(
                EngagementCurve.window_start_second,
                EngagementCurve.dimension,
                EngagementCurve.user_id,
            )
            .limit(limit)
            .all()
        )
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "count": len(rows),
            "rows": [
                {
                    "dimension": row.dimension,
                    "user_id": row.user_id,
                    "window_start_second": row.window_start_second,
                    "window_end_second": row.window_end_second,
                    "metrics": row.metrics or {},
                    "status": row.status,
                    "protocol_version": row.protocol_version,
                }
                for row in rows
            ],
        }

    def get_hint_history(
        self,
        db: Session,
        meeting_id: int,
        limit: int = 50,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        rows = (
            db.query(HintLog)
            .filter(HintLog.meeting_id == meeting_id)
            .order_by(HintLog.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "count": len(rows),
            "items": [
                {
                    "evidence_id": f"H#{row.id}",
                    "hint_id": row.id,
                    "hint_type": row.hint_type,
                    "target_type": row.target_type,
                    "target_user_id": row.target_user_id,
                    "trigger_reason": row.trigger_reason,
                    "evidence": row.evidence or {},
                    "text": row.text,
                    "status": row.status,
                    "sent_at": _milliseconds(row.sent_at),
                    "created_at": _milliseconds(row.created_at),
                }
                for row in rows
            ],
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
            "metadata": result.get("metadata") or {},
        }
        if not ok:
            payload["reason"] = result.get("error") or result["status"]
        return payload

    def record_action(
        self,
        db: Session,
        meeting_id: int,
        *,
        status: str,
        target: str,
        action: str,
        script: str,
        expected: str,
        risk: str,
        evidence: list[str],
        operator_id: int | None = None,
    ) -> dict[str, Any]:
        """记录教师对干预动作的确认/忽略；只写审计，不向学生下发。"""
        type_name = {
            "confirmed": "agent_action_confirm",
            "ignored": "agent_action_ignore",
        }.get(status)
        if type_name is None:
            return {"ok": False, "reason": "不支持的动作状态"}
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting is None:
            return {"ok": False, "reason": "课堂不存在"}
        if not action.strip():
            return {"ok": False, "reason": "动作内容不能为空"}
        payload = {
            "meeting_id": meeting_id,
            "status": status,
            "target": target.strip(),
            "action": action.strip(),
            "script": script.strip(),
            "expected": expected.strip(),
            "risk": risk.strip(),
            "evidence": evidence,
            "confirmation_source": "teacher",
            "operator_id": operator_id,
        }
        insight = AIInsight(
            meeting_id=meeting_id,
            target_user=target.strip() or "小组",
            content=json.dumps(payload, ensure_ascii=False),
            type=type_name,
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)
        return {
            "ok": True,
            "audit_id": insight.id,
            "confirmation_id": insight.id,
            "status": status,
        }

    def confirm_action(
        self,
        db: Session,
        meeting_id: int,
        *,
        target: str,
        action: str,
        script: str,
        expected: str,
        risk: str,
        evidence: list[str],
        confirmed_by: int | None = None,
    ) -> dict[str, Any]:
        return self.record_action(
            db,
            meeting_id,
            status="confirmed",
            target=target,
            action=action,
            script=script,
            expected=expected,
            risk=risk,
            evidence=evidence,
            operator_id=confirmed_by,
        )

    def ignore_action(
        self,
        db: Session,
        meeting_id: int,
        *,
        target: str,
        action: str,
        script: str,
        expected: str,
        risk: str,
        evidence: list[str],
        ignored_by: int | None = None,
    ) -> dict[str, Any]:
        return self.record_action(
            db,
            meeting_id,
            status="ignored",
            target=target,
            action=action,
            script=script,
            expected=expected,
            risk=risk,
            evidence=evidence,
            operator_id=ignored_by,
        )

    def list_action_audits(self, db: Session, meeting_id: int, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        rows = (
            db.query(AIInsight)
            .filter(
                AIInsight.meeting_id == meeting_id,
                AIInsight.type.in_(("agent_action_confirm", "agent_action_ignore")),
            )
            .order_by(AIInsight.id.desc())
            .limit(limit)
            .all()
        )
        items = []
        for row in rows:
            try:
                payload = json.loads(row.content or "{}")
            except (TypeError, ValueError):
                payload = {}
            items.append(
                {
                    "audit_id": row.id,
                    "status": payload.get(
                        "status",
                        "confirmed" if row.type == "agent_action_confirm" else "ignored",
                    ),
                    "target": payload.get("target") or row.target_user,
                    "action": payload.get("action", ""),
                    "script": payload.get("script", ""),
                    "evidence": payload.get("evidence", []),
                    "operator_id": payload.get("operator_id"),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return {"ok": True, "meeting_id": meeting_id, "count": len(items), "items": items}


classroom_agent_service = ClassroomAgentService()
