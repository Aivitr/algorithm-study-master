"""Agent 输出 JSON 解析与降级。"""

from __future__ import annotations

import json

from app.agents.service import parse_agent_output


def _payload():
    return {
        "summary": "测试总结",
        "structure": {"groups": [], "bridges": [], "isolates": []},
        "metrics_reading": [],
        "findings": [],
        "interventions": [],
        "engagement": [],
        "hint_recommendations": [],
        "validation": [],
        "product_metrics": [],
        "data_gaps": [],
        "unsupported_claims": [],
    }


def test_parse_plain_json():
    output = parse_agent_output(json.dumps(_payload(), ensure_ascii=False))
    assert output.summary == "测试总结"


def test_parse_json_code_fence_and_surrounding_text():
    text = "分析如下：\n```json\n" + json.dumps(_payload(), ensure_ascii=False) + "\n```"
    output = parse_agent_output(text)
    assert output.summary == "测试总结"


def test_invalid_json_falls_back_to_text():
    output = parse_agent_output("这不是 JSON，只是一段分析")
    assert output.summary == "这不是 JSON，只是一段分析"
    assert output.data_gaps == ["模型未按要求返回结构化 JSON"]


def test_schema_mismatch_falls_back():
    output = parse_agent_output('{"summary": "只有摘要"}')
    assert output.summary == '{"summary": "只有摘要"}'
    assert output.data_gaps == ["模型未按要求返回结构化 JSON"]
