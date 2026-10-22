"""ClassStatsService：统计口径与共享聚合（先钉行为，再重构路由）。"""

from app.core import database
from app.services.class_stats_service import ClassStatsService


def _session():
    return database.SessionLocal()


def test_class_score_formula_is_pinned():
    svc = ClassStatsService()
    assert svc.class_score(0, 0) == 0
    # base=min(60, 10/2*12=60) + volume=min(30, 8) + breadth=min(10, 2) = 70
    assert svc.class_score(10, 2) == 70
    # 无发言、5 名成员：base=0 + volume=0 + breadth=5
    assert svc.class_score(0, 5) == 5
    # 封顶 100
    assert svc.class_score(1000, 100) == 100


def test_score_level_thresholds():
    svc = ClassStatsService()
    assert svc.score_level(80) == ("优秀", "green")
    assert svc.score_level(60) == ("良好", "yellow")
    assert svc.score_level(59) == ("待提高", "red")


def test_active_status_tag_thresholds():
    svc = ClassStatsService()
    assert svc.active_status_tag(4, 100.0) == "冷清"
    assert svc.active_status_tag(5, 2.0) == "活跃"
    assert svc.active_status_tag(5, 1.9) == "一般"


def test_window_duration_minutes():
    from datetime import datetime, timedelta

    svc = ClassStatsService()
    start = datetime(2026, 1, 1, 9, 0, 0)
    assert svc.window_duration_minutes(start, start + timedelta(minutes=7)) == 7
    assert svc.window_duration_minutes(start, start) == 0
    assert svc.window_duration_minutes(None, start) == 0


def test_activity_and_window_maps(seeded_ids):
    db = _session()
    try:
        svc = ClassStatsService(db)
        assert svc.activity_map([seeded_ids["meeting_id"]]) == {
            seeded_ids["meeting_id"]: {"speech_count": 3, "member_count": 2}
        }
        window = svc.window_map([seeded_ids["meeting_id"]])[seeded_ids["meeting_id"]]
        assert window["first_at"] < window["last_at"]
    finally:
        db.close()


def test_emotion_counts(seeded_ids):
    db = _session()
    try:
        counts = ClassStatsService(db).emotion_counts(seeded_ids["meeting_id"])
    finally:
        db.close()

    assert counts == {"专注": 1}


def test_participant_and_user_speech_counts(seeded_ids):
    db = _session()
    try:
        svc = ClassStatsService(db)
        assert svc.participant_count(seeded_ids["meeting_id"]) == 2
        assert (
            svc.user_speech_count(
                seeded_ids["meeting_id"], seeded_ids["student_id"]
            )
            == 2
        )
    finally:
        db.close()
