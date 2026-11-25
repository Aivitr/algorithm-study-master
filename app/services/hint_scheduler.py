"""服务端 Hint 评估循环。

每 30 秒为所有进行中的课堂评估一次，生成待教师确认的提示。
替代原先由教师浏览器定时轮询触发的检查；本循环只写候选，不发送。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Meeting
from app.services.hint_candidate_service import generate_pending_hints

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 30

_task: asyncio.Task | None = None


def evaluate_running_meetings() -> int:
    """同步执行一轮评估，返回新建提示数。供定时循环与测试调用。"""
    db = SessionLocal()
    try:
        rows: list[Any] = list(db.scalars(select(Meeting.id).where(Meeting.status == "running")))
        meeting_ids = [int(value) for value in rows]
    finally:
        db.close()

    created = 0
    for meeting_id in meeting_ids:
        session = SessionLocal()
        try:
            created += len(generate_pending_hints(session, meeting_id))
        except Exception as exc:  # 单个课堂失败不影响其他课堂
            logger.warning("hint evaluation failed for meeting %s: %s", meeting_id, exc)
            session.rollback()
        finally:
            session.close()
    return created


async def _loop() -> None:
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(evaluate_running_meetings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("hint scheduler tick failed")


def start() -> None:
    global _task
    if os.getenv("HINT_SCHEDULER_ENABLED", "1") != "1":
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
