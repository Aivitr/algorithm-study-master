"""分析运行观测查询。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AnalysisRun, Meeting
from app.services.session_service import SessionContext, require_session

router = APIRouter()


@router.get("/api/analysis-runs/{meeting_id}")
def list_analysis_runs(
    meeting_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="课堂不存在")
    if ctx.user.role != "teacher" or int(meeting.teacher_id) != int(ctx.user.id):
        raise HTTPException(status_code=403, detail="只有本课堂教师可以查看运行记录")

    rows = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.meeting_id == meeting_id)
        .order_by(AnalysisRun.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "status": "success",
        "meeting_id": meeting_id,
        "runs": [
            {
                "id": row.id,
                "kind": row.kind,
                "source": row.source,
                "model": row.model,
                "version": row.version,
                "status": row.status,
                "latency_ms": row.latency_ms,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "cost": row.cost,
                "result": row.result or {},
                "error": row.error,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }
