"""课堂发言（Transcript）只读查询。

HTTP 路由与 Agent Tool 共用这一层，避免同一查询出现两份实现。
本类是**只读**的：不写入、不提交事务。
"""

from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import Transcript


class TranscriptQueryService:
    def __init__(self, db: Session):
        self.db = db

    def _base_query(self, meeting_id: int):
        return (
            self.db.query(Transcript)
            .options(joinedload(Transcript.user))
            .filter(Transcript.meeting_id == meeting_id)
        )

    def list_for_meeting(
        self,
        meeting_id: int,
        limit: Optional[int] = None,
        ascending: bool = True,
    ) -> List[Transcript]:
        """按课堂取发言，默认时间升序；`limit` 为 None 时取全部。"""
        query = self._base_query(meeting_id).order_by(
            Transcript.created_at.asc() if ascending else Transcript.created_at.desc()
        )
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def recent_for_meeting(self, meeting_id: int, limit: int = 5) -> List[Transcript]:
        """最近的 N 条发言（时间倒序）。"""
        return self.list_for_meeting(meeting_id, limit=limit, ascending=False)

    def count_for_meeting(self, meeting_id: int) -> int:
        return self._base_query(meeting_id).count()

    def counts_by_user(self, meeting_id: int) -> Dict[int, int]:
        """按用户聚合发言条数，返回 {user_id: count}。"""
        rows = (
            self.db.query(Transcript.user_id, func.count(Transcript.id))
            .filter(Transcript.meeting_id == meeting_id)
            .group_by(Transcript.user_id)
            .all()
        )
        return {
            int(user_id): int(count)
            for user_id, count in rows
            if user_id is not None
        }
