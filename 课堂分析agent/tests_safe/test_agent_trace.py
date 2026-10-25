"""本地 Agent trace 的无网络测试。"""

import asyncio
import json
from types import SimpleNamespace

from app.agents.trace import LocalTraceHooks


def test_local_trace_records_model_and_tool_durations(tmp_path):
    trace = LocalTraceHooks(
        meeting_id=1,
        question="分析课堂",
        trace_dir=tmp_path,
    )
    model = SimpleNamespace(model="deepseek-chat")
    agent = SimpleNamespace(model=model)
    tool = SimpleNamespace(name="get_classroom_statistics")
    tool_context = SimpleNamespace(tool_call_id="call-1", tool_arguments={"meeting_id": 1})

    async def run_hooks():
        await trace.on_llm_start(None, agent, None, [])
        await trace.on_llm_end(None, agent, None)
        await trace.on_tool_start(tool_context, agent, tool)
        await trace.on_tool_end(tool_context, agent, tool, {"ok": True})

    asyncio.run(run_hooks())
    trace.finish("success")
    path = trace.write()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == trace.run_id
    assert payload["outcome"] == "success"
    assert payload["events"][0]["kind"] == "model"
    assert payload["events"][1]["name"] == "get_classroom_statistics"
    assert payload["events"][1]["ok"] is True
    assert all(event["duration_ms"] >= 0 for event in payload["events"])
