from __future__ import annotations

import asyncio

from app.realtime.asr_manager import ASRSessionManager
from app.services import ai_core


def test_transcriber_reports_token_failure(monkeypatch):
    monkeypatch.setattr(ai_core, "refresh_aliyun_token", lambda: None)
    errors = []
    transcriber = ai_core.RealtimeTranscriber(on_error=errors.append)

    assert transcriber.start() is False
    assert "AccessKey" in transcriber.last_error
    assert errors == [transcriber.last_error]


def test_start_session_returns_provider_error(monkeypatch):
    class FakeTranscriber:
        last_error = "AccessKey disabled"

        def __init__(self, **kwargs):
            pass

        def start(self):
            return False

        def stop(self):
            pass

    monkeypatch.setattr(ai_core, "RealtimeTranscriber", FakeTranscriber)
    manager = ASRSessionManager()

    ok, error = asyncio.run(manager.start_session("u", 1, object()))

    assert ok is False
    assert error == "AccessKey disabled"
