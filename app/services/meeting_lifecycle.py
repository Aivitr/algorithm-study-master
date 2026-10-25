"""课堂生命周期的数据库状态转换。

状态转换使用带旧状态条件的 UPDATE，使并发的重复开始/结束请求中只有一个请求
能够取得执行权；调用方仅在返回 True 时执行广播、关闭连接等副作用。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.meeting_state import CREATED, ENDED, RUNNING
from app.models import Meeting


def claim_start(db: Session, meeting_id: int, started_at: datetime) -> bool:
    updated_rows = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.status == CREATED)
        .update(
            {Meeting.status: RUNNING, Meeting.started_at: started_at},
            synchronize_session=False,
        )
    )
    db.commit()
    return updated_rows == 1


def claim_end(db: Session, meeting_id: int, ended_at: datetime) -> bool:
    updated_rows = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.status == RUNNING)
        .update(
            {Meeting.status: ENDED, Meeting.ended_at: ended_at},
            synchronize_session=False,
        )
    )
    db.commit()
    return updated_rows == 1
