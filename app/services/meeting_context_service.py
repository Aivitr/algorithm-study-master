"""课堂上下文（只读）。

`GET /api/meeting/{meeting_id}` 与 Agent 的课堂上下文工具共用这一份实现：
基本信息 + 当前状态 + 三个时间戳 + 学习目标 + 教学设计。

`started_at` 由状态机任务引入；在字段尚未加到模型之前，用 `getattr` 兼容，
对外统一返回 `None`，调用方无需感知。
"""

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import Meeting


class MeetingContextService:
    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def get_meeting(self, meeting_id: int) -> Optional[Meeting]:
        return self.db.query(Meeting).filter(Meeting.id == meeting_id).first()

    @staticmethod
    def _iso(value) -> Optional[str]:
        return value.isoformat() if value else None

    def to_dict(self, meeting: Meeting) -> Dict[str, Any]:
        return {
            "status": "success",
            "meeting_id": meeting.id,
            "topic": meeting.topic,
            "class_status": meeting.status,
            "meeting_status": meeting.status,  # alias: 前端 app.js 读的是这个名字
            "created_at": self._iso(meeting.created_at),
            "started_at": self._iso(getattr(meeting, "started_at", None)),
            "ended_at": self._iso(meeting.ended_at),
            "goals": meeting.knowledge_points or [],
            "teaching_design": meeting.teaching_design,
        }

    def build_response(self, meeting_id: int) -> Dict[str, Any]:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}
        return self.to_dict(meeting)
