"""课堂三维投入计算与落库适配。

把 transcripts / emotion_logs / 质量分转换成 GCA 的统一输入，调用
`analyze_engagement`，再把结果按固定 5 分钟窗口写入 `engagement_curves`。
只读写本仓库的数据，不修改 gca_engine 的任何实现。
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any, cast

from sqlalchemy.orm import Session

from app.core.emotions import normalize_emotion_label
from app.models import EmotionLog, EngagementCurve, Meeting, Transcript
from app.services.gca_service import analyze_meeting_metrics
from app.services.observability_service import record_run
from gca_engine.adapters.classroom import transcripts_to_utterances
from gca_engine.engagement import (
    ENGAGEMENT_PROTOCOL_VERSION,
    EmotionRecord,
    EngagementResult,
    SpeechQualityRecord,
    analyze_engagement,
)
from gca_engine.schemas import GroupAnalysisResult, Utterance


def _relative_seconds(value: datetime | None, origin: datetime) -> float | None:
    if value is None:
        return None
    return max(0.0, (value - origin).total_seconds())


def _meeting_origin(meeting: Meeting, transcripts: list[Transcript]) -> datetime:
    if meeting.started_at is not None:
        return cast(datetime, meeting.started_at)
    times = [item.created_at or item.timestamp for item in transcripts]
    times = [value for value in times if value is not None]
    return min(times) if times else (meeting.created_at or datetime.now())


def _student_transcripts(meeting_id: int, db: Session) -> list[Transcript]:
    rows = (
        db.query(Transcript)
        .filter(Transcript.meeting_id == meeting_id)
        .order_by(Transcript.id)
        .all()
    )
    return [row for row in rows if getattr(row.user, "role", None) != "teacher"]


def _transcript_records(transcripts: list[Transcript], origin: datetime) -> list[dict[str, Any]]:
    records = []
    for item in transcripts:
        occurred_at = item.created_at or item.timestamp
        seconds = _relative_seconds(cast("datetime | None", occurred_at), origin)
        if seconds is None:
            continue
        records.append(
            {
                "id": item.id,
                "user_id": item.user_id,
                "content": item.content or "",
                "timestamp": seconds,
            }
        )
    return records


def build_utterances(meeting_id: int, db: Session) -> tuple[Meeting | None, list[Utterance]]:
    """取课堂的学生发言（教师已排除），按 meeting.started_at 换算相对秒数。"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        return None, []
    transcripts = _student_transcripts(meeting_id, db)
    origin = _meeting_origin(meeting, transcripts)
    return meeting, transcripts_to_utterances(
        _transcript_records(transcripts, origin), str(meeting_id)
    )


def _build_inputs(
    meeting: Meeting, transcripts: list[Transcript], db: Session
) -> tuple[list[Utterance], list[SpeechQualityRecord], list[EmotionRecord]]:
    origin = _meeting_origin(meeting, transcripts)
    utterances = transcripts_to_utterances(
        _transcript_records(transcripts, origin), str(meeting.id)
    )

    quality = [
        SpeechQualityRecord(
            utterance_id=str(item.id),
            quality_score=cast("int | None", item.quality_score),
            relevance_score=cast("int | None", item.relevance_score),
            feedback=cast("str | None", item.quality_feedback),
        )
        for item in transcripts
    ]

    emotions = []
    for row in db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting.id).all():
        seconds = _relative_seconds(cast("datetime | None", row.created_at), origin)
        if seconds is None:
            seconds = float(row.video_start_time or 0.0)
        emotions.append(
            EmotionRecord(
                meeting_id=str(meeting.id),
                user_id=str(row.user_id),
                emotion_type=normalize_emotion_label(cast(str, row.emotion_type or "")),
                timestamp=max(0.0, seconds),
                intensity=cast("float | None", row.intensity),
                source="video",
                record_id=str(row.id),
            )
        )

    return utterances, quality, emotions


def _gca_result(meeting_id: int, db: Session) -> GroupAnalysisResult:
    payload: dict[str, Any] = analyze_meeting_metrics(meeting_id, db)
    status = payload.get("status")
    status = getattr(status, "value", status)
    return GroupAnalysisResult(
        meeting_id=str(meeting_id),
        status=str(status or ""),
        student_metrics=payload.get("student_metrics") or {},
        group_metrics=payload.get("group_metrics") or {},
        timeline=payload.get("timeline"),
        metadata=payload.get("metadata") or {},
        warnings=payload.get("warnings") or [],
        error=payload.get("error"),
    )


def build_engagement(meeting_id: int, db: Session) -> EngagementResult | None:
    """计算一节课的三维投入；课堂不存在时返回 None。"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        return None

    transcripts = _student_transcripts(meeting_id, db)
    utterances, quality, emotions = _build_inputs(meeting, transcripts, db)
    origin = _meeting_origin(meeting, transcripts)
    end = meeting.ended_at or datetime.now()
    duration = max(0.0, (end - origin).total_seconds())

    return analyze_engagement(
        str(meeting_id),
        utterances,
        emotion_records=emotions,
        quality_records=quality,
        gca_result=_gca_result(meeting_id, db),
        duration_seconds=duration,
    )


def _curve_rows(
    meeting_id: int, result: EngagementResult, duration: float
) -> list[EngagementCurve]:
    rows: list[EngagementCurve] = []
    for dimension, dim_result in result.dimensions.items():
        windows = (dim_result.timeline or {}).get("fixed_5min") or []
        if not windows:
            windows = [
                {
                    "start_second": 0,
                    "end_second": duration,
                    "group_metrics": dim_result.group_metrics,
                    "student_metrics": dim_result.student_metrics,
                }
            ]

        for window in windows:
            start = float(window.get("start_second") or 0.0)
            end = float(window.get("end_second") or duration)
            group_metrics = window.get("group_metrics") or {}
            if group_metrics:
                rows.append(
                    EngagementCurve(
                        meeting_id=meeting_id,
                        user_id=None,
                        dimension=dimension,
                        window_start_second=start,
                        window_end_second=end,
                        metrics=group_metrics,
                        status=dim_result.status,
                        protocol_version=ENGAGEMENT_PROTOCOL_VERSION,
                    )
                )
            for raw_user_id, metrics in (window.get("student_metrics") or {}).items():
                try:
                    user_id = int(raw_user_id)
                except (TypeError, ValueError):
                    continue
                rows.append(
                    EngagementCurve(
                        meeting_id=meeting_id,
                        user_id=user_id,
                        dimension=dimension,
                        window_start_second=start,
                        window_end_second=end,
                        metrics=metrics,
                        status=dim_result.status,
                        protocol_version=ENGAGEMENT_PROTOCOL_VERSION,
                    )
                )
    return rows


def rebuild_engagement_curves(meeting_id: int, db: Session) -> dict[str, Any]:
    """重算并覆盖一节课的投入曲线；重复调用结果一致。"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        return {"status": "not_found", "meeting_id": meeting_id}

    result = build_engagement(meeting_id, db)
    if result is None:
        return {"status": "not_found", "meeting_id": meeting_id}

    transcripts = _student_transcripts(meeting_id, db)
    origin = _meeting_origin(meeting, transcripts)
    end = meeting.ended_at or datetime.now()
    duration = max(0.0, (end - origin).total_seconds())
    started = perf_counter()
    rows = _curve_rows(meeting_id, result, duration)

    try:
        db.query(EngagementCurve).filter(EngagementCurve.meeting_id == meeting_id).delete(
            synchronize_session=False
        )
        db.add_all(rows)
        db.commit()
    except Exception as exc:
        db.rollback()
        record_run(
            db,
            meeting_id=meeting_id,
            kind="engagement",
            source="gca",
            status="error",
            model="gca",
            version=ENGAGEMENT_PROTOCOL_VERSION,
            latency_ms=int((perf_counter() - started) * 1000),
            error=str(exc),
        )
        raise

    dimension_status = {name: dim.status for name, dim in result.dimensions.items()}
    record_run(
        db,
        meeting_id=meeting_id,
        kind="engagement",
        source="gca",
        status=result.status,
        model="gca",
        version=ENGAGEMENT_PROTOCOL_VERSION,
        latency_ms=int((perf_counter() - started) * 1000),
        result={"rows": len(rows), "dimension_status": dimension_status},
    )

    return {
        "status": "success",
        "meeting_id": meeting_id,
        "analysis_status": result.status,
        "dimension_status": dimension_status,
        "rows": len(rows),
        "protocol_version": ENGAGEMENT_PROTOCOL_VERSION,
        "warnings": result.warnings,
    }
