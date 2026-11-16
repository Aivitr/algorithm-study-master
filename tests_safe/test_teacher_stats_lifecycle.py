"""待开始（created）与无发言样本的课堂不参与评分、风险统计与平均分。"""

from uuid import uuid4

import pytest


@pytest.fixture
def created_meeting(seeded_ids):
    from app.core.database import SessionLocal
    from app.models import Meeting

    db = SessionLocal()
    meeting = Meeting(
        class_code=f"CREATED-{uuid4().hex[:8]}",
        teacher_id=seeded_ids["teacher_id"],
        topic="待开始课堂",
        knowledge_points=[],
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    meeting_id = meeting.id
    db.close()

    try:
        yield meeting_id
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(Meeting).filter(Meeting.id == meeting_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


@pytest.fixture
def empty_running_meeting(seeded_ids):
    from app.core.database import SessionLocal
    from app.models import Meeting

    db = SessionLocal()
    meeting = Meeting(
        class_code=f"EMPTY-{uuid4().hex[:8]}",
        teacher_id=seeded_ids["teacher_id"],
        topic="空课堂",
        knowledge_points=[],
        status="running",
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    meeting_id = meeting.id
    db.close()

    try:
        yield meeting_id
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(Meeting).filter(Meeting.id == meeting_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_created_class_is_not_scored(client, seeded_ids, created_meeting):
    body = client.get(f"/api/teacher-classes/{seeded_ids['teacher_id']}").json()
    row = {item["meeting_id"]: item for item in body["classes"]}[created_meeting]

    assert row["status"] == "created"
    assert row["score"] is None
    assert row["score_level"] == "待开始"
    assert row["score_color"] == "blue"


def test_created_class_is_excluded_from_risk_and_average(client, seeded_ids, created_meeting):
    stats = client.get(f"/api/teacher-stats/{seeded_ids['teacher_id']}").json()["stats"]
    classes = client.get(f"/api/teacher-classes/{seeded_ids['teacher_id']}").json()["classes"]

    scored = [item for item in classes if item["score"] is not None]
    expected_risk = sum(1 for item in scored if item["score"] < 60)
    expected_avg = int(sum(item["score"] for item in scored) / len(scored)) if scored else None

    # 待开始的课堂计入总数，但不进风险数与平均分
    assert stats["totalClasses"] == len(classes)
    assert stats["riskGroups"] == expected_risk
    assert stats["avgScore"] == expected_avg


def test_empty_running_class_is_not_scored_or_counted_as_risk(
    client, seeded_ids, empty_running_meeting
):
    stats = client.get(f"/api/teacher-stats/{seeded_ids['teacher_id']}").json()["stats"]
    classes = client.get(f"/api/teacher-classes/{seeded_ids['teacher_id']}").json()["classes"]
    row = {item["meeting_id"]: item for item in classes}[empty_running_meeting]

    assert row["score"] is None
    assert row["score_level"] == "暂无数据"

    scored = [item for item in classes if item["score"] is not None]
    expected_risk = sum(1 for item in scored if item["score"] < 60)
    expected_avg = int(sum(item["score"] for item in scored) / len(scored)) if scored else None

    # 没有发言样本的课不拉低平均分，也不产生风险计数
    assert stats["riskGroups"] == expected_risk
    assert stats["avgScore"] == expected_avg


def test_empty_running_class_appears_last_in_active_groups(
    client, seeded_ids, empty_running_meeting
):
    groups = client.get(f"/api/active-groups/{seeded_ids['teacher_id']}").json()["groups"]
    row = {item["meeting_id"]: item for item in groups}[empty_running_meeting]

    assert row["score"] is None
    assert row["status_tag"] == "暂无数据"
    # 无数据的课堂排在最后，且不会让排序因 None 报错
    assert groups[-1]["meeting_id"] == empty_running_meeting
