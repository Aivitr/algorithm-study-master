"""Personal overview authentication and output contract."""
def test_overview_requires_login(client, seeded_ids):
    assert client.get(f"/api/student-classroom-overview/{seeded_ids['meeting_id']}").status_code == 401


def test_overview_rejects_teacher(client, seeded_ids, teacher_headers):
    assert client.get(f"/api/student-classroom-overview/{seeded_ids['meeting_id']}", headers=teacher_headers).status_code == 403


def test_overview_returns_only_self(client, seeded_ids, student_headers):
    response = client.get(f"/api/student-classroom-overview/{seeded_ids['meeting_id']}", headers=student_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'status', 'student', 'meeting', 'summary', 'distribution', 'speeches', 'emotions'}
    assert body['summary']['speech_count'] == len(body['speeches'])
    assert sum(item['count'] for item in body['distribution']) == len(body['speeches'])
    from app.core.database import SessionLocal
    from app.models import Transcript, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.student_id == body['student']['student_id']).one()
        expected = {row.id for row in db.query(Transcript).filter(Transcript.meeting_id == seeded_ids['meeting_id'], Transcript.user_id == user.id).all()}
        assert {row['id'] for row in body['speeches']} == expected
    finally:
        db.close()
