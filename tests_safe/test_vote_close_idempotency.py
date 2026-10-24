"""投票关闭幂等性回归测试。

全部使用本地 SQLite 合成数据，并将 LLM 与 WebSocket 广播替换成内存桩，
不会访问真实课堂、真实数据库或外部模型。
"""

from uuid import uuid4

import pytest


@pytest.fixture
def active_vote(local_app, seeded_ids):
    from app.core.database import SessionLocal
    from app.models import Meeting, ViewpointVote

    db = SessionLocal()
    suffix = uuid4().hex[:10]
    meeting = Meeting(
        class_code=f"VOTE-{suffix}",
        teacher_id=seeded_ids["teacher_id"],
        topic="投票幂等性测试课堂",
        status="active",
        knowledge_points=[
            {"id": 1, "desc": "原始目标", "status": "pending"},
        ],
    )
    db.add(meeting)
    db.flush()

    vote = ViewpointVote(
        meeting_id=meeting.id,
        vote_session_id=f"vote-{suffix}",
        viewpoints=[
            {"id": 1, "title": "观点一", "desc": "观点一的内容"},
            {"id": 2, "title": "观点二", "desc": "观点二的内容"},
        ],
        votes={"1": ["学生甲", "学生乙"], "2": ["学生丙"]},
        status="active",
    )
    db.add(vote)
    db.commit()
    db.refresh(meeting)
    db.refresh(vote)

    ids = {"meeting_id": meeting.id, "vote_id": vote.id}
    db.close()

    try:
        yield ids
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(ViewpointVote).filter(ViewpointVote.id == ids["vote_id"]).delete()
            cleanup.query(Meeting).filter(Meeting.id == ids["meeting_id"]).delete()
            cleanup.commit()
        finally:
            cleanup.close()


@pytest.fixture
def isolated_vote_effects(monkeypatch):
    import app.routers.votes as votes_router

    llm_calls = []
    broadcasts = []

    def fake_generate_sub_goals(selected_viewpoint, topic, current_goals):
        llm_calls.append((selected_viewpoint, topic, current_goals))
        return {
            "sub_goals": [
                {"desc": "验证子目标A"},
                {"desc": "验证子目标B"},
            ],
            "guidance": "测试引导语",
        }

    async def fake_broadcast(meeting_id, payload):
        broadcasts.append((meeting_id, payload))

    monkeypatch.setattr(votes_router.llm, "generate_sub_goals", fake_generate_sub_goals)
    monkeypatch.setattr(votes_router.manager, "broadcast_to_meeting", fake_broadcast)

    return {"llm_calls": llm_calls, "broadcasts": broadcasts}


def _post_close(client, ids):
    return client.post(
        "/api/close-vote",
        data={"vote_id": ids["vote_id"], "meeting_id": ids["meeting_id"]},
    )


def test_repeated_close_only_appends_goals_once(
    client, active_vote, isolated_vote_effects
):
    from app.core.database import SessionLocal
    from app.models import Meeting, ViewpointVote

    first = _post_close(client, active_vote)
    assert first.status_code == 200
    assert first.json()["status"] == "success"

    db = SessionLocal()
    try:
        first_closed_at = (
            db.query(ViewpointVote)
            .filter(ViewpointVote.id == active_vote["vote_id"])
            .one()
            .closed_at
        )
    finally:
        db.close()

    second = _post_close(client, active_vote)
    assert second.status_code == 200
    assert second.json()["status"] == "success"
    assert second.json()["already_closed"] is True

    db = SessionLocal()
    try:
        vote = (
            db.query(ViewpointVote)
            .filter(ViewpointVote.id == active_vote["vote_id"])
            .one()
        )
        meeting = (
            db.query(Meeting)
            .filter(Meeting.id == active_vote["meeting_id"])
            .one()
        )
        assert vote.status == "closed"
        assert vote.closed_at == first_closed_at
        assert [goal["desc"] for goal in meeting.knowledge_points] == [
            "原始目标",
            "[深入探讨] 验证子目标A",
            "[深入探讨] 验证子目标B",
        ]
    finally:
        db.close()

    assert len(isolated_vote_effects["llm_calls"]) == 1
    assert [payload["type"] for _, payload in isolated_vote_effects["broadcasts"]] == [
        "vote_result",
        "goals_updated",
    ]


def test_atomic_close_claim_can_only_succeed_once(active_vote):
    from app.core.database import SessionLocal
    from app.routers.votes import _claim_vote_close

    first_db = SessionLocal()
    second_db = SessionLocal()
    try:
        assert _claim_vote_close(
            first_db,
            active_vote["vote_id"],
            active_vote["meeting_id"],
            1,
        ) is True
        assert _claim_vote_close(
            second_db,
            active_vote["vote_id"],
            active_vote["meeting_id"],
            1,
        ) is False
    finally:
        first_db.close()
        second_db.close()


def test_confirm_after_manual_close_does_not_repeat_side_effects(
    client, active_vote, isolated_vote_effects
):
    from app.core.database import SessionLocal
    from app.models import Meeting

    closed = _post_close(client, active_vote)
    assert closed.json()["status"] == "success"

    confirmed = client.post(
        "/api/confirm-vote",
        data={
            "vote_id": active_vote["vote_id"],
            "meeting_id": active_vote["meeting_id"],
            "username": "学生甲",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "success"
    assert confirmed.json()["already_closed"] is True

    db = SessionLocal()
    try:
        meeting = (
            db.query(Meeting)
            .filter(Meeting.id == active_vote["meeting_id"])
            .one()
        )
        assert len(meeting.knowledge_points) == 3
    finally:
        db.close()

    assert len(isolated_vote_effects["llm_calls"]) == 1
    assert [payload["type"] for _, payload in isolated_vote_effects["broadcasts"]] == [
        "vote_result",
        "goals_updated",
    ]
