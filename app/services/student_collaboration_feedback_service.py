"""Student-facing, deterministic feedback derived from one GCA result.

No database access and no LLM calls live here.  The rules intentionally avoid
grades, ranks and diagnoses: they turn collaboration signals into small,
actionable participation suggestions for the current student only.
"""

from __future__ import annotations

from typing import Any, Dict


def _feedback(
    feedback_type: str,
    level: str,
    title: str,
    description: str,
    suggestion: str,
    *,
    metric: str | None = None,
) -> Dict[str, Any]:
    return {
        "type": feedback_type,
        "level": level,
        "title": title,
        "description": description,
        "suggestion": suggestion,
        "metric": metric,
    }


def build_student_collaboration_feedback(
    *,
    status: str,
    student_metrics: Dict[str, Any],
    class_average: Dict[str, Any],
    own_utterance_count: int,
    total_utterance_count: int,
) -> list[Dict[str, Any]]:
    """Return at most three conservative suggestions for the current student."""
    if own_utterance_count <= 0 or not student_metrics:
        return [
            _feedback(
                "not_yet_participated",
                "info",
                "还没有形成个人协作数据",
                "目前没有检测到你的有效发言，因此还不能计算个人协作特征。",
                "可以先回应一个已有观点，说明你赞同、质疑或想补充的部分。",
            )
        ]

    if status not in {"success", "single_speaker"}:
        return [
            _feedback(
                "limited_data",
                "info",
                "数据仍在积累",
                "当前课堂数据还不足以形成稳定的协作分析。",
                "继续参与讨论，稍后再刷新查看。",
            )
        ]

    suggestions: list[Dict[str, Any]] = []
    participation = float(student_metrics.get("participation") or 0.0)
    participation_average = float(class_average.get("participation") or 0.0)
    if participation < max(0.12, participation_average * 0.65):
        suggestions.append(
            _feedback(
                "participation_opportunity",
                "action",
                "可以增加一次有效参与",
                "你当前的发言参与比例低于课堂匿名平均水平。",
                "选择一个已有观点，用“我赞同/我有疑问，因为……”开始回应。",
                metric="participation",
            )
        )

    metric_rules = (
        (
            "overall_responsivity",
            "respond_to_peer",
            "多回应同伴观点",
            "你的发言与同伴观点的连接目前相对较少。",
            "先复述上一位同学的核心观点，再说明你的补充或不同意见。",
        ),
        (
            "newness",
            "add_new_angle",
            "尝试补充一个新角度",
            "你的发言对已有讨论的新信息补充目前相对较少。",
            "可以提出反例、适用条件，或者换一个比较维度继续讨论。",
        ),
        (
            "communication_density",
            "structure_expression",
            "让表达结构更清楚",
            "你的单位表达中可识别的信息密度目前相对较低。",
            "尝试使用“观点—理由—证据”三步结构组织下一次发言。",
        ),
        (
            "internal_cohesion",
            "connect_own_ideas",
            "连接自己的前后观点",
            "你当前几次发言之间的延续关系还不明显。",
            "下一次发言可以先说明“接着我刚才的观点……”，再补充理由。",
        ),
        (
            "social_impact",
            "invite_response",
            "给同伴留下回应入口",
            "你的观点目前较少引出后续回应。",
            "表达后补充一个具体问题，邀请同伴评价或提供证据。",
        ),
    )
    for metric, feedback_type, title, description, suggestion in metric_rules:
        own_value = float(student_metrics.get(metric) or 0.0)
        average = float(class_average.get(metric) or 0.0)
        if average > 0 and own_value <= average - 0.10:
            suggestions.append(
                _feedback(
                    feedback_type,
                    "action",
                    title,
                    description,
                    suggestion,
                    metric=metric,
                )
            )

    if total_utterance_count < 8:
        suggestions.insert(
            0,
            _feedback(
                "small_sample",
                "info",
                "当前结果可能变化较大",
                f"全班目前只有 {total_utterance_count} 条有效发言。",
                "请把指标作为参与提示，不要把它理解为成绩或能力结论。",
            ),
        )

    if not suggestions:
        suggestions.append(
            _feedback(
                "keep_exploring",
                "success",
                "保持当前协作方式",
                "当前没有触发明显的个人改进规则。",
                "继续回应同伴、补充证据，并尝试提出能推动讨论的问题。",
            )
        )
    return suggestions[:3]
