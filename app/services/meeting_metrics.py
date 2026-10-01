"""会议统计口径的共享辅助。

本模块只有两个**纯查询**函数，作用是给"一节课"算两个维度的聚合，避免各路由
各写一遍 SQL：

    _build_meeting_window_map(db, meeting_ids)     这节课的起止时刻
    _build_meeting_activity_map(db, meeting_ids, *) 这节课的发言数 / 发言人数

这两个函数同时服务学生统计域（`/api/student-home-stats`）与教师域
（`/api/teacher-classes`、`/api/teacher-stats`），因此放在中立模块，两组都从
这里取（不能 `from server import ...`，见 `app/routers/__init__.py`）。

`_` 前缀是刻意保留的模块私有名；要改成公开名应作为独立一次提交，并靠
`tests_safe/test_module_free_names.py` 兜底（漏改调用点会立刻红）。
"""

from typing import Any, Dict, List

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models import Transcript, User


def _build_meeting_window_map(db: Session, meeting_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not meeting_ids:
        return {}

    rows = db.query(
        Transcript.meeting_id.label("meeting_id"),
        sa_func.min(Transcript.created_at).label("first_at"),
        sa_func.max(Transcript.created_at).label("last_at"),
    ).filter(
        Transcript.meeting_id.in_(meeting_ids)
    ).group_by(
        Transcript.meeting_id
    ).all()

    return {
        int(row.meeting_id): {
            "first_at": row.first_at,
            "last_at": row.last_at,
        }
        for row in rows
    }


def _build_meeting_activity_map(db: Session, meeting_ids: List[int], *, exclude_teacher: bool = True) -> Dict[int, Dict[str, int]]:
    if not meeting_ids:
        return {}

    query = db.query(
        Transcript.meeting_id.label("meeting_id"),
        sa_func.count(Transcript.id).label("speech_count"),
        sa_func.count(sa_func.distinct(Transcript.user_id)).label("member_count"),
    )
    if exclude_teacher:
        query = query.join(User, User.id == Transcript.user_id).filter(User.role != "teacher")

    rows = query.filter(
        Transcript.meeting_id.in_(meeting_ids)
    ).group_by(
        Transcript.meeting_id
    ).all()

    return {
        int(row.meeting_id): {
            "speech_count": int(row.speech_count or 0),
            "member_count": int(row.member_count or 0),
        }
        for row in rows
    }
