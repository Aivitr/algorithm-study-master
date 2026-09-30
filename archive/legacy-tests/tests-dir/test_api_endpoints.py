from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


def test_ai_tutor():
    res = client.post("/api/ai-tutor", json={"question": "1+1=?"})
    assert res.status_code == 200


def test_suggest_topic():
    res = client.post("/api/suggest-topic", json={"context": "AI学习"})
    assert res.status_code == 200


def test_quiz_error_analysis():
    res = client.post("/api/quiz-error-analysis", json={"answer": "wrong"})
    assert res.status_code == 200