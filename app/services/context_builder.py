"""LLM 上下文的裁剪原语。

从 `llm_service` 抽出，供业务路由与 Agent 的 Context Layer 共用：
  - `normalize_text`：空白折叠 + 非字符串转 JSON + 截断
  - `normalize_context_lines`：取最近 N 条，压成 "用户: 内容" 行，再按总长截断

这两个函数是纯函数，不依赖数据库、模型或进程状态。
"""

import json
from typing import Any, List


def normalize_text(text: Any, max_len: int = 500) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    text = " ".join(text.split())
    return text[:max_len]


def normalize_context_lines(
    items: List[Any],
    max_items: int = 8,
    each_len: int = 80,
    total_len: int = 500,
) -> str:
    lines = []
    for item in items[-max_items:]:
        if isinstance(item, dict):
            user = (
                item.get("username")
                or item.get("student_name")
                or item.get("user")
                or "用户"
            )
            content = item.get("content") or item.get("text") or item.get("speech") or ""
            line = f"{user}: {normalize_text(content, each_len)}"
        else:
            line = normalize_text(item, each_len)
        if line.strip():
            lines.append(line)
    return "\n".join(lines)[:total_len]
