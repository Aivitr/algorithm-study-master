"""分析运行观测：记录耗时、token 与错误。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AnalysisRun


def record_run(
    db: Session,
    *,
    meeting_id: int,
    kind: str,
    source: str,
    status: str,
    model: str = "",
    version: str = "",
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost: float | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> int | None:
    """写一条观测记录；失败只打印，不影响主流程。"""
    row = AnalysisRun(
        meeting_id=meeting_id,
        kind=kind,
        source=source,
        model=model or None,
        version=version or None,
        status=status,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost=cost,
        result=result or {},
        error=(error or "")[:2000] or None,
    )
    db.add(row)
    try:
        db.commit()
        return int(row.id)
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] 分析观测写入失败: meeting_id={meeting_id}: {exc}")
        return None
