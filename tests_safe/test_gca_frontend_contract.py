"""Static wiring checks for the teacher GCA dashboard."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_teacher_dashboard_markup_and_endpoint_are_wired():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/js/app.js").read_text(encoding="utf-8")

    assert 'class="gca-fab"' in html
    assert "data-frontend-probe-ignore" in html
    assert "currentUser.role === 'teacher'" in html
    assert "gcaDashboardVisible" in html
    assert "整体情况" in html
    assert "学生对比" in html
    assert "个人详情" in html
    assert "状态提醒" in html
    assert "/api/gca-dashboard/${this.meetingId}" in javascript
    assert "/api/agents/group-analysis" not in javascript


def test_dashboard_has_all_six_canonical_metrics():
    javascript = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    for metric in (
        "participation",
        "internal_cohesion",
        "overall_responsivity",
        "social_impact",
        "newness",
        "communication_density",
    ):
        assert f"key: '{metric}'" in javascript


def test_gca_demo_mode_is_explicit_and_database_free():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    demo = json.loads(
        (ROOT / "static/mock/gca-dashboard-demo.json").read_text(encoding="utf-8")
    )

    assert "?gca_demo=1" in javascript
    assert "/static/mock/gca-dashboard-demo.json" in javascript
    assert 'class="gca-demo-badge"' in html
    assert "不会写入数据库" in html
    assert demo["demo_data"] is True
    assert len(demo["students"]) == 4
    assert set(demo["group_metrics"]) == {
        "participation",
        "internal_cohesion",
        "overall_responsivity",
        "social_impact",
        "newness",
        "communication_density",
    }


def test_student_gca_view_has_role_scoped_ui_and_demo_fixture():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    demo = json.loads(
        (ROOT / "static/mock/gca-student-view-demo.json").read_text(encoding="utf-8")
    )

    assert "openStudentGca" in html
    assert "我的协作" in html
    assert "课堂协作" in html
    assert "改进建议" in html
    assert "/api/gca-student-view/${this.meetingId}" in javascript
    assert "/static/mock/gca-student-view-demo.json" in javascript
    assert "students" not in demo
    assert "student_metrics" not in demo
    assert set(demo["student"]) == {"id", "name", "student_id", "metrics"}
