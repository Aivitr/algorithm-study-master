"""会议统计口径的共享辅助（阶段 5 从 server.py 迁出）。

本模块只有两个**纯查询**函数，作用是给"一节课"算两个维度的聚合，避免各路由
各写一遍 SQL：

    _build_meeting_window_map(db, meeting_ids)     这节课的起止时刻
    _build_meeting_activity_map(db, meeting_ids, *) 这节课的发言数 / 发言人数

为什么需要一个独立的家
----------------------
它们原本是 server.py 的模块级私有辅助，但**同时被两个业务域使用**——
学生统计域（`/api/student-home-stats`）与教师域（`/api/teacher-classes`、
`/api/teacher-stats`）。阶段 5 把路由按业务域拆出去之后，任何一方都不能再
`from server import ...`（在 `python server.py` 下那会让 server.py 二次执行，
见 `app/routers/__init__.py`）。跟着其中一组走，另一组就会缺依赖；所以给它
一个中立的家，两组都从这里取。

`server.py` 目前仍以 `from app.services.meeting_metrics import ...` **再导出**
这两个名字，因此在 server.py 内的既有调用点（`/api/teacher-classes`、
`/api/teacher-stats`）一行都不用改；等教师域也搬完，再让它们直接导入本模块。

名字里的下划线
--------------
`_` 前缀是它们在 server.py 里"模块私有"的历史痕迹，这里**刻意保留**：本次是
纯搬迁，改名字只增加比对噪音。要改成公开名，应作为独立一次提交，且改完由
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
