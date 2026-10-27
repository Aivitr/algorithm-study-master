"""
gca_engine.windows —— 时间窗口分析（负责人：雷梦琪）。

两个窗口：

- 固定 5 分钟窗口：[0,300)、[300,600)、…，每段内独立重算 GCA，
  用来看"这节课每个阶段小组状态"。
- 滑动 5 分钟窗口：每 30 秒一个更新点（首版），取最近 5 分钟的发言
  重算 GCA，用来看"小组状态怎么漂移"。

三个设计约束（改动前先想清楚）：

1. **不重新拟合 LSA**。整个课堂的语义空间在 engine 里只拟合一次，
   窗口只拿同一空间的向量子集重算 GCA。否则每个窗口都换一套语义坐标，
   窗口之间不可比，时间趋势就没意义了。
2. **窗口只做切子集 + 重算 + 汇总**，不碰 LSA/GCA 的数学细节。
   具体怎么算由调用方通过 `analyzer` 回调注入（engine 传真实实现，
   测试可以传假实现），这样 windows.py 不依赖 fit_lsa_space，好测也好改。
3. **单个窗口出错不许让整体崩**。某个窗口的发言向量异常、算不出指标时，
   该窗口按"无数据窗口"（group_metrics 为空）处理，原因写进 errors，
   由 engine 汇总成 warnings。空窗口、单人窗口同理，都不抛异常。

输出严格遵循 schemas.py 里约定的 timeline 结构：

    {
      "fixed_5min":   [{"start_second": 0, "end_second": 300, "group_metrics": {...}}, ...],
      "sliding_5min": [{"center_second": 30, "group_metrics": {...}}, ...],
    }

没有发言的窗口，`group_metrics` 就是 {}（不是 None、不是 NaN）。
消费者可以用 `group_metrics["participation"]["count"]` 判断该窗口里有几个人。
"""

import logging
import math
from typing import Callable

from gca_engine.aggregation import group_metric_stats
from gca_engine.config import (
    FIXED_WINDOW_SECONDS,
    SLIDING_STEP_SECONDS,
    SLIDING_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)

# analyzer 的契约：吃一个发言子集，吐出 {speaker_id: {六个指标: 值}}。
# 返回 {} 表示"这个子集算不出指标"（空子集、全部空文本等）。
Analyzer = Callable[[list], dict[str, dict[str, float]]]


def _timestamp(utterance) -> float:
    return float(utterance.timestamp)


def duration_seconds(utterances) -> float:
    """课堂时长：每条发言取 max(end_time 或 timestamp)，再取全局最大值。

    注意不能"只要有 end_time 就只看 end_time"——真实数据里 end_time
    经常只有一部分记录有，那样会把课堂时长算短，窗口数量跟着少。

    空列表返回 0.0，不抛异常。
    """
    if not utterances:
        return 0.0
    total = 0.0
    for u in utterances:
        end = getattr(u, "end_time", None)
        point = float(end) if end is not None else _timestamp(u)
        if point > total:
            total = point
    return float(total)


def _subset(utterances, start: float, end: float, include_start: bool) -> list:
    """取 [start, end) 或 (start, end] 内的发言（时间戳口径见各窗口说明）。

    调用方保证 utterances 已按时间排序（engine 会先排序），这里只过滤不排序。
    """
    out = []
    for u in utterances:
        ts = _timestamp(u)
        if include_start:
            # 左闭右开：[start, end)
            if start <= ts < end:
                out.append(u)
        else:
            # 左开右闭：(start, end]
            if start < ts <= end:
                out.append(u)
    return out


def _window_entry(utterances, analyzer, errors, kind, **bounds) -> dict:
    """算一个窗口：切子集 → analyzer → 小组统计，异常按空窗口处理。"""
    entry = dict(bounds)
    entry["group_metrics"] = {}
    if not utterances:
        return entry
    try:
        student = analyzer(utterances)
    except Exception as exc:  # 单个窗口失败不拖垮整节课
        logger.warning("window analyzer failed (%s): %s", kind, exc)
        errors.append(
            {
                "kind": kind,
                **bounds,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return entry
    if student:
        entry["group_metrics"] = group_metric_stats(student)
    return entry


def build_fixed_windows(
    utterances,
    window_seconds: int = FIXED_WINDOW_SECONDS,
    analyzer: Analyzer | None = None,
    errors: list | None = None,
    duration: float | None = None,
) -> list[dict]:
    """固定时间窗口：把课堂按 window_seconds 切成 [0,300)、[300,600)…

    Args:
        utterances:      已排序的 Utterance 列表。
        window_seconds:  窗口长度（默认 5 分钟）。
        analyzer:        子集指标计算回调；None 时全部窗口为空。
        errors:          可选，失败窗口的错误信息会 append 进来。
        duration:        课堂时长；None 时自动从 utterances 推算。

    Returns:
        [{"start_second", "end_second", "group_metrics"}, ...]

    边界约定：
        - 一个发言正好落在窗口边界上时，归入后一个窗口（左闭右开）。
        - 课堂时长为 0（只有一条 t=0 的发言）时也会有一个 [0,300) 窗口。
        - 时长不是窗口整数倍时，最后一个窗口是完整的 300 秒，
          不会截断成半截（Agent 侧看到的窗口长度始终一致）。
    """
    window_seconds = int(window_seconds)
    if window_seconds <= 0:
        raise ValueError("window_seconds 必须是正整数")
    errors = errors if errors is not None else []

    if duration is None:
        duration = duration_seconds(utterances)

    n_windows = max(1, int(math.ceil(duration / window_seconds)))

    windows = []
    for i in range(n_windows):
        start = i * window_seconds
        end = start + window_seconds
        subset = _subset(utterances, start, end, include_start=True)
        windows.append(
            _window_entry(
                subset,
                analyzer,
                errors,
                "fixed",
                start_second=start,
                end_second=end,
            )
        )
    return windows


def build_sliding_windows(
    utterances,
    window_seconds: int = SLIDING_WINDOW_SECONDS,
    step_seconds: int = SLIDING_STEP_SECONDS,
    analyzer: Analyzer | None = None,
    errors: list | None = None,
    duration: float | None = None,
) -> list[dict]:
    """滑动时间窗口：每 step_seconds 一个更新点，取"最近 window_seconds"内的发言。

    Args:
        utterances:     已排序的 Utterance 列表。
        window_seconds: 窗口长度（默认 5 分钟）。
        step_seconds:   更新粒度（首版 30 秒）。
        analyzer:       子集指标计算回调。
        errors:         可选，失败窗口的错误信息 append 进来。
        duration:       课堂时长；None 时自动推算。

    Returns:
        [{"center_second", "group_metrics"}, ...]

    边界约定：
        - center_second 是**更新时刻**（课堂第几秒做这次统计），
          和 schemas.py 里的示例一致：第一个点是 30。
        - 每个窗口取 (center-window_seconds, center]，即"最近 5 分钟"，
          正好在 5 分钟前的那条发言不算进来（左开右闭，避免重复计入）。
        - 更新点取 step 的整数倍；课堂结束时间不在整数倍上时，
          额外补一个以课堂结束时刻为 center 的点，保证末尾发言不被漏掉。
        - 课堂时长不足一个 step 时返回空列表（由 engine 给 warning 说明）。
    """
    window_seconds = int(window_seconds)
    step_seconds = int(step_seconds)
    if window_seconds <= 0 or step_seconds <= 0:
        raise ValueError("window_seconds / step_seconds 必须是正整数")
    if step_seconds > window_seconds:
        raise ValueError("step_seconds 不能大于 window_seconds")
    errors = errors if errors is not None else []

    if duration is None:
        duration = duration_seconds(utterances)

    centers: list[float] = []
    point = float(step_seconds)
    while point <= duration:
        centers.append(point)
        point += step_seconds
    if not centers:
        # 课堂比一个更新点还短：不放任何点，交给 engine 说明"数据不足"
        return []
    if duration > centers[-1]:
        centers.append(float(duration))

    windows = []
    for center in centers:
        start = max(0.0, center - window_seconds)
        subset = _subset(utterances, start, float(center), include_start=False)
        windows.append(
            _window_entry(
                subset,
                analyzer,
                errors,
                "sliding",
                center_second=int(center),
            )
        )
    return windows


def build_timeline(
    utterances,
    analyzer: Analyzer,
    fixed_window_seconds: int = FIXED_WINDOW_SECONDS,
    sliding_window_seconds: int = SLIDING_WINDOW_SECONDS,
    sliding_step_seconds: int = SLIDING_STEP_SECONDS,
    duration: float | None = None,
) -> tuple[dict, list[str]]:
    """一次算出完整 timeline。

    Returns:
        (timeline, warnings, errors)
        timeline = {"fixed_5min": [...], "sliding_5min": [...]}
        warnings 是给人看的说明（空窗口、失败窗口、时长不足等），
        engine 会把它并进 GroupAnalysisResult.warnings；
        errors 是失败窗口的结构化明细，engine 放进 metadata.window_errors。
    """
    if duration is None:
        duration = duration_seconds(utterances)

    errors: list = []
    fixed = build_fixed_windows(
        utterances,
        window_seconds=fixed_window_seconds,
        analyzer=analyzer,
        errors=errors,
        duration=duration,
    )
    sliding = build_sliding_windows(
        utterances,
        window_seconds=sliding_window_seconds,
        step_seconds=sliding_step_seconds,
        analyzer=analyzer,
        errors=errors,
        duration=duration,
    )

    warnings: list[str] = []

    n_fixed_empty = sum(1 for w in fixed if not w["group_metrics"])
    if n_fixed_empty:
        warnings.append(
            f"固定 {fixed_window_seconds // 60} 分钟窗口中有 {n_fixed_empty} 个窗口没有发言"
        )

    if not sliding:
        warnings.append(
            f"课堂时长 {duration:g} 秒不足一个滑动更新点（{sliding_step_seconds} 秒），"
            "sliding_5min 为空"
        )
    else:
        n_sliding_empty = sum(1 for w in sliding if not w["group_metrics"])
        if n_sliding_empty:
            warnings.append(
                f"滑动窗口中有 {n_sliding_empty} 个更新点最近 "
                f"{sliding_window_seconds // 60} 分钟内没有发言"
            )

    if errors:
        warnings.append(
            f"有 {len(errors)} 个时间窗口计算失败，已按无数据窗口处理"
            "（详见 metadata.window_errors）"
        )

    timeline = {
        "fixed_5min": fixed,
        "sliding_5min": sliding,
    }
    return timeline, warnings, errors
