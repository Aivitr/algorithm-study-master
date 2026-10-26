"""待开始（created）的课堂不参与评分、风险统计与平均分。"""

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


def test_created_class_is_not_scored(client, seeded_ids, created_meeting):
    body = client.get(f"/api/teacher-classes/{seeded_ids['teacher_id']}").json()
    row = {item["meeting_id"]: item for item in body["classes"]}[created_meeting]

    assert row["status"] == "created"
    assert row["score"] is None
    assert row["score_level"] == "待开始"
    assert row["score_color"] == "blue"


def test_created_class_is_excluded_from_risk_and_average(
    client, seeded_ids, created_meeting
):
    stats = client.get(f"/api/teacher-stats/{seeded_ids['teacher_id']}").json()["stats"]
    classes = client.get(f"/api/teacher-classes/{seeded_ids['teacher_id']}").json()["classes"]

    scored = [item for item in classes if item["status"] != "created"]
    expected_risk = sum(1 for item in scored if item["score"] < 60)
    expected_avg = int(sum(item["score"] for item in scored) / len(scored))

    # 待开始的课堂计入总数，但不进风险数与平均分
    assert stats["totalClasses"] == len(classes)
    assert stats["riskGroups"] == expected_risk
    assert stats["avgScore"] == expected_avg
