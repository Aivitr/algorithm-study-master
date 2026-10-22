"""TranscriptQueryService：只读查询行为 + 路由响应形状。

合成数据（tests_safe/fixtures.py）约定：
  - meeting 1：3 条发言，按时间升序为 李同学 / 王同学 / 李同学
  - meeting 2：6 条发言，两人各 3 条
本文件先把「路由返回什么」钉死，再验证 Service 行为与之一致——
重构期间任何字段变化都应当让这里变红。
"""

from app.core import database
from app.services.transcript_query_service import TranscriptQueryService


def _session():
    return database.SessionLocal()


def test_list_for_meeting_is_chronological(seeded_ids):
    db = _session()
    try:
        rows = TranscriptQueryService(db).list_for_meeting(seeded_ids["meeting_id"])
    finally:
        db.close()

    assert [r.content for r in rows] == [
        "我认为光合作用需要光照和叶绿体",
        "还有二氧化碳和水",
        "产物是葡萄糖和氧气",
    ]


def test_list_for_meeting_honours_limit(seeded_ids):
    db = _session()
    try:
        rows = TranscriptQueryService(db).list_for_meeting(
            seeded_ids["meeting_id"], limit=2
        )
    finally:
        db.close()

    assert [r.content for r in rows] == [
        "我认为光合作用需要光照和叶绿体",
        "还有二氧化碳和水",
    ]


def test_recent_for_meeting_is_newest_first(seeded_ids):
    db = _session()
    try:
        rows = TranscriptQueryService(db).recent_for_meeting(
            seeded_ids["meeting_id"], limit=2
        )
    finally:
        db.close()

    assert [r.content for r in rows] == [
        "产物是葡萄糖和氧气",
        "还有二氧化碳和水",
    ]


def test_counts_by_user(seeded_ids):
    db = _session()
    try:
        counts = TranscriptQueryService(db).counts_by_user(
            seeded_ids["meeting_id_active"]
        )
    finally:
        db.close()

    assert counts == {seeded_ids["student_id"]: 3, seeded_ids["student_id_b"]: 3}


def test_route_response_shape_is_pinned(client):
    """GET /api/transcripts/{meeting_id} 的字段集合必须保持不变。"""
    resp = client.get("/api/transcripts/1")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body) == {"status", "transcripts"}
    assert body["status"] == "success"

    items = body["transcripts"]
    assert len(items) == 3
    assert set(items[0]) == {
        "id",
        "username",
        "text",
        "timestamp",
        "quality_score",
        "quality_feedback",
        "emotion",
        "action",
    }
    assert items[0]["username"] == "李同学"
    assert items[0]["text"] == "我认为光合作用需要光照和叶绿体"
    assert items[0]["quality_score"] == 85
    assert items[0]["emotion"] == "专注"
    assert items[0]["action"] == "举手"


def test_route_limit_is_pinned(client):
    body = client.get("/api/transcripts/1", params={"limit": 1}).json()
    assert len(body["transcripts"]) == 1
