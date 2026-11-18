"""知识图谱生成接口：仅在有转写时构建，并持久化结果。"""

from app.core.database import SessionLocal
from app.models import KnowledgeGraph


def _delete_graph(meeting_id: int) -> None:
    db = SessionLocal()
    try:
        db.query(KnowledgeGraph).filter(KnowledgeGraph.meeting_id == meeting_id).delete()
        db.commit()
    finally:
        db.close()


def test_generate_knowledge_graph_requires_login(client, seeded_ids):
    response = client.post(
        f"/api/knowledge-graph/{seeded_ids['meeting_id_active']}/generate",
        headers={"Authorization": ""},
    )
    assert response.status_code == 401


def test_generate_knowledge_graph_rejects_student(client, seeded_ids, student_headers, monkeypatch):
    import app.services.knowledge_trace_service as trace

    def fail_if_called(*args, **kwargs):
        raise AssertionError("学生越权时不应调用 LLM")

    monkeypatch.setattr(trace.kg_service, "extract_concepts_from_conversation", fail_if_called)

    response = client.post(
        f"/api/knowledge-graph/{seeded_ids['meeting_id_active']}/generate",
        headers=student_headers,
    )
    body = response.json()

    assert body["status"] == "error"
    assert "只有本课堂教师" in body["message"]


def test_generate_knowledge_graph_builds_and_persists(
    client, seeded_ids, teacher_headers, monkeypatch
):
    import app.services.knowledge_trace_service as trace

    meeting_id = seeded_ids["meeting_id_active"]
    calls = []

    def fake_extract(topic, conversations, existing_graph=None):
        calls.append((topic, conversations))
        return {
            "nodes": [
                {
                    "id": "concept_1",
                    "label": "细胞呼吸",
                    "type": "概念",
                    "description": "细胞分解有机物释放能量",
                }
            ],
            "edges": [],
        }

    monkeypatch.setattr(trace.kg_service, "extract_concepts_from_conversation", fake_extract)
    _delete_graph(meeting_id)

    try:
        response = client.post(
            f"/api/knowledge-graph/{meeting_id}/generate",
            headers=teacher_headers,
        )
        body = response.json()

        assert body["status"] == "success"
        assert body["data"]["nodes"][0]["name"] == "细胞呼吸"
        assert calls and calls[0][0] == "测试课堂：细胞呼吸"

        db = SessionLocal()
        try:
            row = db.query(KnowledgeGraph).filter(KnowledgeGraph.meeting_id == meeting_id).one()
            assert row.graph_data["nodes"][0]["label"] == "细胞呼吸"
        finally:
            db.close()
    finally:
        _delete_graph(meeting_id)
