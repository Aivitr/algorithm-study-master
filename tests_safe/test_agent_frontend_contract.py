"""课堂 AI 面板的静态接线契约。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_analyze_buttons_do_not_pass_click_event_as_question():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '@click="runClassroomAgent()"' in html
    assert '@click="runClassroomAgent"' not in html


def test_analysis_handler_only_accepts_string_override():
    javascript = (ROOT / "static/js/classroom-insights.js").read_text(encoding="utf-8")
    assert "typeof overrideQuestion === 'string'" in javascript


def test_teacher_hint_inbox_is_wired():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/js/classroom-insights.js").read_text(encoding="utf-8")

    assert "待发送提示" in html
    assert "/api/hint-logs/${meetingId}" in javascript
    assert "/api/hint-logs/${item.id}/send" in javascript
    assert "/api/hint-logs/${item.id}/ignore" in javascript


def test_silent_script_does_not_overwrite_agent_question():
    javascript = (ROOT / "static/js/classroom-insights.js").read_text(encoding="utf-8")
    start = javascript.index("makeSilentScript()")
    body = javascript[start : javascript.index("copyText(script", start)]
    assert "agentQuestion" not in body
    assert "currentTopic" in body


def test_ai_tutor_chat_is_reset_on_logout_and_session_invalidation():
    javascript = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "resetAITutorState()" in javascript
    assert javascript.count("this.resetAITutorState();") >= 2
    start = javascript.index("resetAITutorState() {")
    body = javascript[start : javascript.index("},", start)]
    assert "this.aiMessages = [];" in body
