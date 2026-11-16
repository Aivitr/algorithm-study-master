"""Deterministic collaboration-signal rules."""

from app.services.collaboration_signal_service import build_collaboration_signals


def _result(*, status="success", utterances=20, students=None, windows=None):
    return {
        "status": status,
        "metadata": {
            "n_utterances": utterances,
            "n_speakers": len(students or {}),
        },
        "student_metrics": students or {},
        "timeline": {"fixed_5min": windows or [], "sliding_5min": []},
        "warnings": [],
    }


def test_empty_transcript_only_returns_data_notice():
    signals = build_collaboration_signals(_result(status="empty_transcript"))
    assert [item["type"] for item in signals] == ["no_data"]
    assert signals[0]["level"] == "info"


def test_small_sample_does_not_make_strong_claims():
    result = _result(
        utterances=4,
        students={
            "1": {"participation": 0.75},
            "2": {"participation": 0.25},
        },
    )
    signals = build_collaboration_signals(result)
    assert [item["type"] for item in signals] == ["limited_sample"]


def test_concentrated_participation_has_explainable_evidence():
    result = _result(
        students={
            "1": {"participation": 0.40},
            "2": {"participation": 0.30},
            "3": {"participation": 0.20},
            "4": {"participation": 0.10},
        }
    )
    signal = next(
        item
        for item in build_collaboration_signals(result)
        if item["type"] == "participation_imbalance"
    )
    assert signal["evidence"]["top_two_share"] == 0.7
    assert signal["related_student_ids"] == ["1", "2"]


def test_fixed_window_declines_create_trend_signals():
    windows = [
        {
            "start_second": 0,
            "end_second": 300,
            "group_metrics": {
                "overall_responsivity": {"mean": 0.55},
                "newness": {"mean": 0.60},
            },
        },
        {
            "start_second": 300,
            "end_second": 600,
            "group_metrics": {
                "overall_responsivity": {"mean": 0.40},
                "newness": {"mean": 0.44},
            },
        },
    ]
    result = _result(
        students={
            "1": {"participation": 0.25},
            "2": {"participation": 0.25},
            "3": {"participation": 0.25},
            "4": {"participation": 0.25},
        },
        windows=windows,
    )
    types = {item["type"] for item in build_collaboration_signals(result)}
    assert {"responsivity_decline", "newness_decline"} <= types


def test_balanced_stable_data_gets_neutral_observation():
    result = _result(
        students={
            "1": {"participation": 0.25},
            "2": {"participation": 0.25},
            "3": {"participation": 0.25},
            "4": {"participation": 0.25},
        }
    )
    assert [item["type"] for item in build_collaboration_signals(result)] == [
        "no_obvious_signal"
    ]
