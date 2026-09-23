import pytest
from llm_service import llm


def test_json_clean():
    raw = "```json\n{\"a\":1}\n```"
    result = llm._clean_json(raw)
    assert result == {"a": 1}


def test_json_invalid_fallback():
    raw = "not a json"
    result = llm._clean_json(raw)
    assert isinstance(result, dict)  # 不崩溃


def test_fallback_trigger(monkeypatch):
    def fail(*args, **kwargs):
        raise Exception("primary failed")

    def success(*args, **kwargs):
        return "ok"

    monkeypatch.setattr(llm, "_chat_once", fail)
    monkeypatch.setattr(llm, "_fallback_chat", success)

    result = llm._chat_with_fallback([{"role": "user", "content": "test"}])
    assert result == "ok"