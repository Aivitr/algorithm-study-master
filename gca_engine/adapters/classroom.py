"""
课堂数据 → 统一 Utterance（负责人：岳柔）。

把课堂系统 transcripts 表的记录转成 schemas.py 的 Utterance。

输入记录（dict）至少需要这些字段（与 Transcript 表对应）：
    id        原始记录 ID          -> utterance_id
    user_id   发言学生 ID          -> speaker_id（转成字符串）
    content   发言文本             -> text
    timestamp 发言时间             -> timestamp（转成"课堂开始后的秒数"）

timestamp 可以是 datetime 或数字：
    - 数字：当作"课堂开始后的秒数"直接用；
    - datetime：按本组最早一条发言的时间作为课堂起点 0 秒。

待办（岳柔，配合 preprocessing/chinese.py 一起做）：
    - 中文分词接入（先定分词方案再动 LSA 的文本输入）
    - 口语词过滤
    - ASR 重复片段清理
    - 补测试样例（tests/test_classroom_*.py）
"""

"""课堂 Transcript → 统一 Utterance（负责人：岳柔）。"""

from datetime import datetime
from typing import Any

from gca_engine.schemas import Utterance
from gca_engine.preprocessing.chinese import normalize_text

_TRANSCRIPT_FIELDS = ("id", "user_id", "content", "timestamp")


def _to_seconds(value: Any, origin: float) -> float:
    """把一条记录的时间转成课堂开始后的秒数。"""
    if isinstance(value, datetime):
        return (value - datetime.fromtimestamp(origin, tz=value.tzinfo)).total_seconds() \
            if value.tzinfo else (value - datetime.fromtimestamp(origin)).total_seconds()
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"timestamp 必须是 datetime 或数字，got {type(value).__name__}")


def transcripts_to_utterances(
    transcripts: list[dict],
    meeting_id: str | int,
) -> list[Utterance]:
    """把课堂 transcripts 记录列表转成统一 Utterance 列表。

    - 空文本自动跳过
    - 按时间升序排列
    - user_id 统一转字符串
    """
    if not isinstance(transcripts, list):
        raise ValueError("transcripts 必须是列表")
    meeting_id = str(meeting_id)

    # 1. 找最早时间作为 origin
    origin: float | None = None
    has_datetime = False
    has_numeric = False
    for r in transcripts:
        if not isinstance(r, dict):
            raise ValueError("每条记录必须是 dict")
        missing = [f for f in _TRANSCRIPT_FIELDS if f not in r]
        if missing:
            raise ValueError(f"记录缺少字段: {missing}")
        ts = r["timestamp"]
        if isinstance(ts, datetime):
            has_datetime = True
            origin = min(ts.timestamp(), origin) if origin is not None else ts.timestamp()
        elif isinstance(ts, (int, float)) and not isinstance(ts, bool):
            has_numeric = True
            origin = min(float(ts), origin) if origin is not None else float(ts)
        else:
            raise ValueError(f"timestamp 必须是 datetime 或数字，got {type(ts).__name__}")
        if has_datetime and has_numeric:
            raise ValueError(
                "同一批 transcript 的 timestamp 不能混用 datetime 和数字（相对秒数）"
            )

    if origin is None:
        return []

    # 2. 逐条转换，跳过空文本
    utterances: list[Utterance] = []
    for r in transcripts:
        text = normalize_text(r.get("content"))
        if text == "":
            continue

        utterances.append(
            Utterance(
                meeting_id=meeting_id,
                speaker_id=str(r["user_id"]),
                text=text,
                timestamp=_to_seconds(r["timestamp"], origin),
                utterance_id=str(r["id"]),
                end_time=None,
            )
        )

    # 3. 排序
    utterances.sort(key=lambda u: (u.timestamp, u.utterance_id))
    return utterances