"""三维学习投入读取。

写入由后续整合层负责；这里只提供按课堂、维度、学生过滤的只读查询。
学生只能看自己的曲线，小组级曲线只对教师返回。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Meeting
from app.models.engagement import EngagementCurve
from app.services.session_service import SessionContext, require_session

router = APIRouter()

DIMENSIONS = ("emotional", "behavioral", "cognitive")


@router.get("/api/engagement/{meeting_id}")
async def get_engagement(
    meeting_id: int,
    dimension: str | None = None,
    user_id: int | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="课堂不存在")

    if dimension is not None and dimension not in DIMENSIONS:
        raise HTTPException(status_code=422, detail="dimension 必须是三个维度之一")

    is_teacher = ctx.user.role == "teacher"
    if is_teacher:
        if int(meeting.teacher_id) != int(ctx.user.id):
            raise HTTPException(status_code=403, detail="只能查看自己课堂的投入数据")
    else:
        if user_id is not None and int(user_id) != int(ctx.user.id):
            raise HTTPException(status_code=403, detail="只能查看自己的投入数据")
        user_id = int(ctx.user.id)

    query = db.query(EngagementCurve).filter(EngagementCurve.meeting_id == meeting_id)
    if dimension is not None:
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
        "meeting_id": meeting_id,
        "status": "success",
        "curves": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "dimension": row.dimension,
                "window_start_second": row.window_start_second,
                "window_end_second": row.window_end_second,
                "metrics": row.metrics or {},
                "status": row.status,
                "protocol_version": row.protocol_version,
            }
            for row in rows
        ],
    }
