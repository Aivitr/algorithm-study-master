"""发言质量分有效性判定。

`Transcript.quality_score` 的默认值是 0，但 0 也完全可能是评分器给出的真实分；
两者只能靠 `quality_feedback` 区分：尚未打分时反馈为空或停留在“评估中”。
`app/realtime/stream.py` 就是不传质量分建行的，这些行在统计里必须视为未评分。
"""

from __future__ import annotations

_PENDING_OR_FAILED = {"评估中", "已断句，正在评分", "评估超时"}


def valid_quality_score(row) -> int | None:
    """返回可计入统计的质量分；未评分或非法值返回 None。"""
    score = getattr(row, "quality_score", None)
    if score is None:
        return None
    try:
        score = int(score)
    except (TypeError, ValueError):
        return None
    if not 0 <= score <= 100:
        return None
    if score != 0:
        return score
    feedback = (getattr(row, "quality_feedback", None) or "").strip().rstrip(".。…").strip()
    if not feedback or feedback in _PENDING_OR_FAILED:
        return None
    return 0
