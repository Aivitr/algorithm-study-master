"""课堂 Agent 两条 HTTP 接口的无网络契约测试。"""

import app.routers.agents as agent_routes
from app.agents.group_analysis_agent import GroupAnalysisOutput


def _output() -> GroupAnalysisOutput:
    return GroupAnalysisOutput(
        summary="测试摘要",
        structure="测试结构",
        metrics_reading=[],
        findings=[],
        interventions=[],
        data_gaps=[],
        unsupported_claims=[],
    )


def test_group_analysis_tools_endpoint(client):
    response = client.get("/api/agents/group-analysis/tools")

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert [tool["name"] for tool in tools] == [
        "get_classroom_transcripts",
        "get_classroom_statistics",
        "get_classroom_knowledge",
    ]
    assert all(tool["allowed_states"] == ["ended", "running"] for tool in tools)


def test_group_analysis_question_endpoint(client, monkeypatch):
    async def fake_run(db, meeting_id, question, max_turns):
        assert meeting_id == 1
        assert question == "分析参与是否均衡"
        assert max_turns == 6
        return _output()

    monkeypatch.setattr(agent_routes, "run_group_analysis", fake_run)
    response = client.post(
        "/api/agents/group-analysis",
        json={"meeting_id": 1, "question": "分析参与是否均衡", "max_turns": 6},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "analysis": _output().model_dump()}
