"""KnowledgeTraceService：图谱读取与学习目标覆盖（只读）。"""

from app.core import database
from app.services import knowledge_graph_service
from app.services.knowledge_trace_service import KnowledgeTraceService


def _session():
    return database.SessionLocal()


def test_visualize_existing_graph(seeded_ids):
    db = _session()
    try:
        result = KnowledgeTraceService(db).visualize(seeded_ids["meeting_id"])
    finally:
        db.close()

    assert result["status"] == "success"
    assert set(result["data"]) == {"nodes", "links", "categories"}
    assert [n["name"] for n in result["data"]["nodes"]] == ["光合作用"]


def test_visualize_missing_graph_returns_empty(seeded_ids):
    db = _session()
    try:
        result = KnowledgeTraceService(db).visualize(seeded_ids["meeting_id_active"])
    finally:
        db.close()

    assert result == {"status": "empty", "data": {"nodes": [], "edges": []}}


def test_goal_coverage_splits_by_done_status():
    svc = KnowledgeTraceService(None)
    goals = [
        {"id": 1, "desc": "理解光照", "status": "done"},
        {"id": 2, "desc": "理解产物", "status": "pending"},
        {"id": 3, "desc": "理解叶绿体", "status": "done"},
    ]

    coverage = svc.goal_coverage(goals)

    assert coverage["total"] == 3
    assert coverage["covered_count"] == 2
    assert coverage["uncovered_count"] == 1
    assert [g["id"] for g in coverage["covered"]] == [1, 3]
    assert [g["id"] for g in coverage["uncovered"]] == [2]


def test_goal_coverage_handles_empty():
    coverage = KnowledgeTraceService(None).goal_coverage(None)
    assert coverage == {
        "total": 0,
        "covered_count": 0,
        "uncovered_count": 0,
        "covered": [],
        "uncovered": [],
    }


def test_build_from_transcripts_reuses_kg_service_without_writing(seeded_ids, monkeypatch):
    calls = {}

    def fake_extract(topic, conversations, existing_graph=None):
        calls["topic"] = topic
        calls["conversations"] = conversations
        calls["existing_graph"] = existing_graph
        return {"nodes": [{"id": "concept_1", "label": "测试概念"}], "edges": []}

    monkeypatch.setattr(
        knowledge_graph_service.kg_service,
        "extract_concepts_from_conversation",
        fake_extract,
    )

    db = _session()
    try:
        graph = KnowledgeTraceService(db).build_from_transcripts(seeded_ids["meeting_id"], limit=10)
    finally:
        db.close()

    assert graph["nodes"][0]["label"] == "测试概念"
    assert calls["topic"] == "测试课堂：光合作用"
    # 对话按时间正序送入（Service 内部对 recent(倒序) 做了反转）
    assert [c["content"] for c in calls["conversations"]] == [
        "我认为光合作用需要光照和叶绿体",
        "还有二氧化碳和水",
        "产物是葡萄糖和氧气",
    ]
    assert calls["existing_graph"]["nodes"][0]["label"] == "光合作用"


def test_extract_prompt_has_no_placeholder_and_normalizes_output(monkeypatch):
    import json
    import types

    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        content = json.dumps(
            {
                "nodes": [
                    {"id": "c1", "label": "光合作用", "type": "概念"},
                    {"id": "c2", "label": "叶绿体"},
                ],
                "edges": [
                    {
                        "source": "c1",
                        "target": "c2",
                        "relation": "发生在",
                        "weight": 0.9,
                    },
                    {"source": "c1", "target": "missing", "relation": "悬空"},
                ],
            },
            ensure_ascii=False,
        )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
        )

    monkeypatch.setattr(
        knowledge_graph_service.kg_service.llm.client.chat.completions,
        "create",
        fake_create,
    )

    result = knowledge_graph_service.kg_service.extract_concepts_from_conversation(
        "测试主题", [{"username": "A", "content": "只有一句对话"}]
    )

    prompt = captured["messages"][1]["content"]
    assert "[EMOJI]" not in prompt
    assert "概念" in prompt and "1-15" in prompt
    assert [n["label"] for n in result["nodes"]] == ["光合作用", "叶绿体"]
    assert result["nodes"][1]["type"] == "概念"
    assert result["edges"] == [
        {
            "source": "c1",
            "target": "c2",
            "relation": "发生在",
            "weight": 0.9,
            "evidence": "",
        }
    ]


def test_visualization_uses_chinese_categories_and_drops_dirty_nodes():
    data = knowledge_graph_service.kg_service.generate_graph_visualization_data(
        {
            "nodes": [
                {"id": "c1", "label": "光合作用", "type": "概念"},
                {"id": "c2", "label": "[EMOJI]", "type": "[EMOJI]"},
            ],
            "edges": [{"source": "c1", "target": "c2", "relation": "包含"}],
        }
    )

    assert [c["name"] for c in data["categories"]] == ["概念", "人物", "方法", "关系"]
    assert [n["name"] for n in data["nodes"]] == ["光合作用"]
    assert data["links"] == []
