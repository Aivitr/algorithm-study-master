"""课堂生命周期状态及通用校验。

状态只允许单向流转：created -> running -> ended。
本模块不依赖 FastAPI 或数据库，供 ORM、Service、Router 共同复用。
"""

from enum import Enum
from typing import Iterable, Optional


class MeetingStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    ENDED = "ended"


CREATED = MeetingStatus.CREATED.value
RUNNING = MeetingStatus.RUNNING.value
ENDED = MeetingStatus.ENDED.value
ALL_MEETING_STATUSES = frozenset({CREATED, RUNNING, ENDED})


_STATUS_LABELS = {
    CREATED: "课堂尚未开始",
    RUNNING: "课堂正在进行",
    ENDED: "课堂已经结束",
}


def meeting_status_error(status: Optional[str], allowed: Iterable[str]) -> Optional[str]:
    """状态不在 allowed 中时返回可直接展示的错误信息，否则返回 None。"""
    allowed_set = set(allowed)
    if status in allowed_set:
        return None
    return _STATUS_LABELS.get(status, f"课堂状态异常：{status or 'unknown'}")
