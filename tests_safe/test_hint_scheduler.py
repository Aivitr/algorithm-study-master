"""服务端 Hint 评估循环：只处理进行中的课堂，单课堂失败不影响其他课堂。"""

from __future__ import annotations

from app.core import database
from app.models import Meeting


def test_evaluate_running_meetings_skips_ended(monkeypatch, seeded_ids):
    from app.services import hint_scheduler

    calls = []
    monkeypatch.setattr(
        hint_scheduler,
        "generate_pending_hints",
        lambda db, meeting_id: calls.append(meeting_id) or [],
    )

    hint_scheduler.evaluate_running_meetings()

    assert seeded_ids["meeting_id_active"] in calls
    assert seeded_ids["meeting_id"] not in calls

    db = database.SessionLocal()
    try:
        running = {
            int(row_id)
            for (row_id,) in db.query(Meeting.id).filter(Meeting.status == "running").all()
        }
    finally:
        db.close()
    assert set(calls) <= running


def test_evaluate_running_meetings_isolates_failures(monkeypatch, seeded_ids):
    from app.services import hint_scheduler

    calls = []

    def fake_generate(db, meeting_id):
        calls.append(meeting_id)
        if meeting_id == seeded_ids["meeting_id_active"]:
            raise RuntimeError("boom")
        return []

    monkeypatch.setattr(hint_scheduler, "generate_pending_hints", fake_generate)

    assert hint_scheduler.evaluate_running_meetings() == 0
    assert seeded_ids["meeting_id_active"] in calls
