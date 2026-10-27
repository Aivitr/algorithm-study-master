"""
旧 AMI 语料 conversation.json → 统一 Utterance（负责人：陈虹宇）。

旧实验（final/ami_parser）产出的 conversation.json 是一条条记录：
    {"meeting": "EN2002a", "speaker": "A", "start": 0.0,
     "end": 1.0, "message": "...", ...}

这里把它读进来并转成新项目的统一 Utterance，用途：
    - 历史基线验证：拿旧语料在新引擎上重跑，对比新旧结果；
    - 旧语料在开发期当测试数据用。

字段映射：
    meeting  -> meeting_id（字符串）
    speaker  -> speaker_id（字符串）
    start    -> timestamp（秒，直接当课堂开始后的秒数）
    end      -> end_time
    message  -> text
    utterance_id -> "{meeting}:{序号}"（旧语料没有记录 ID）
"""

import json
from pathlib import Path

from gca_engine.schemas import Utterance

_REQUIRED_KEYS = ("meeting", "speaker", "start", "message")


def records_to_utterances(records: list[dict]) -> list[Utterance]:
    """把旧格式记录列表转成统一 Utterance 列表。

    Raises:
        ValueError: 记录不是列表 / 缺少必要字段。
    """
    if not isinstance(records, list):
        raise ValueError("conversation 数据集必须是记录列表")

    utterances: list[Utterance] = []
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            raise ValueError(f"第 {i} 条记录不是 dict")
        missing = [k for k in _REQUIRED_KEYS if k not in r]
        if missing:
            raise ValueError(f"第 {i} 条记录缺少字段: {missing}")
        utterances.append(Utterance(
            meeting_id=str(r["meeting"]),
            speaker_id=str(r["speaker"]),
            text=str(r["message"]),
            timestamp=float(r["start"]),
            utterance_id=f"{r['meeting']}:{i:04d}",
            end_time=float(r["end"]) if r.get("end") is not None else None,
        ))
    return utterances


def load_conversation_json(path: Path | str) -> list[Utterance]:
    """读一个旧格式 conversation.json 文件，返回统一 Utterance 列表。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 内容不是合法的旧格式数据集。
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"conversation JSON not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list) or not data:
        raise ValueError(f"not a conversation dataset (expected non-empty list): {path.name}")
    return records_to_utterances(data)
