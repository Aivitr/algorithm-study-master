"""Deterministic student collaboration feedback rules."""

from app.services.student_collaboration_feedback_service import (
    build_student_collaboration_feedback,
)

AVERAGE = {
    "participation": 0.25,
    "internal_cohesion": 0.55,
    "overall_responsivity": 0.55,
    "social_impact": 0.55,
    "newness": 0.55,
    "communication_density": 0.55,
}


def test_student_without_speech_gets_participation_starting_point():
    feedback = build_student_collaboration_feedback(
        status="success",
        student_metrics={},
        class_average=AVERAGE,
        own_utterance_count=0,
        total_utterance_count=20,
    )
    assert [item["type"] for item in feedback] == ["not_yet_participated"]


def test_low_metrics_produce_at_most_three_actionable_items():
    feedback = build_student_collaboration_feedback(
        status="success",
        student_metrics={key: 0.1 for key in AVERAGE},
        class_average=AVERAGE,
        own_utterance_count=2,
        total_utterance_count=20,
    )
    assert 1 <= len(feedback) <= 3
    assert feedback[0]["type"] == "participation_opportunity"
    assert all(item["level"] == "action" for item in feedback)


def test_stable_metrics_do_not_invent_a_problem():
    feedback = build_student_collaboration_feedback(
        status="success",
        student_metrics={key: 0.7 for key in AVERAGE},
        class_average=AVERAGE,
        own_utterance_count=8,
        total_utterance_count=24,
    )
    assert [item["type"] for item in feedback] == ["keep_exploring"]
