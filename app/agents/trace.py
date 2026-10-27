"""Agent 运行的本地 JSON trace。"""

import json
import logging
import os
from collections import deque
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from agents import RunHooks

from app.core.paths import STORAGE_DIR


logger = logging.getLogger(__name__)


class LocalTraceHooks(RunHooks[Any]):
    def __init__(
        self,
        *,
        meeting_id: int,
        question: str,
        trace_dir: Path | None = None,
    ) -> None:
        self.run_id = uuid4().hex
        self.trace_dir = trace_dir or STORAGE_DIR / "agent_traces"
        self._started_at = datetime.now().astimezone()
        self._started = perf_counter()
        self._events: list[dict[str, Any]] = []
        self._llm_calls: deque[tuple[dict[str, Any], float]] = deque()
        self._tool_calls: dict[str, tuple[dict[str, Any], float]] = {}
        self._payload: dict[str, Any] = {
            "run_id": self.run_id,
            "workflow": "classroom-group-analysis",
            "meeting_id": meeting_id,
            "question": question,
            "started_at": self._started_at.isoformat(),
            "events": self._events,
        }
        self._finished = False

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        event = {
            "kind": "model",
            "model": getattr(agent.model, "model", str(agent.model)),
            "input_items": len(input_items),
        }
        self._events.append(event)
        self._llm_calls.append((event, perf_counter()))

    async def on_llm_end(self, context, agent, response) -> None:
        if self._llm_calls:
            event, started = self._llm_calls.popleft()
            event["duration_ms"] = round((perf_counter() - started) * 1000, 2)

    async def on_tool_start(self, context, agent, tool) -> None:
        call_id = str(getattr(context, "tool_call_id", "") or f"{tool.name}-{len(self._events)}")
        event = {
            "kind": "tool",
            "name": tool.name,
            "arguments": getattr(context, "tool_arguments", None),
        }
        self._events.append(event)
        self._tool_calls[call_id] = (event, perf_counter())

    async def on_tool_end(self, context, agent, tool, result) -> None:
        call_id = str(getattr(context, "tool_call_id", "") or f"{tool.name}-{len(self._events) - 1}")
        call = self._tool_calls.pop(call_id, None)
        if call is None:
            return
        event, started = call
        event["duration_ms"] = round((perf_counter() - started) * 1000, 2)
        event["result_type"] = type(result).__name__
        if isinstance(result, dict) and "ok" in result:
            event["ok"] = result["ok"]

    def finish(self, outcome: str, error: str = "") -> None:
        if self._finished:
            return
        self._finished = True
        self._payload.update(
            outcome=outcome,
            ended_at=datetime.now().astimezone().isoformat(),
            duration_ms=round((perf_counter() - self._started) * 1000, 2),
        )
        if error:
            self._payload["error"] = error

    def write(self) -> Path | None:
        if not self._finished:
            self.finish("incomplete")
        try:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            path = self.trace_dir / f"{self.run_id}.json"
            temp_path = path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(self._payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(temp_path, path)
            return path
        except OSError:
            logger.exception("Unable to write local agent trace")
            return None
