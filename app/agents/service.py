"""Classroom Group Analysis Agent 执行入口。"""

import json
import re

from agents import RunConfig, Runner
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.group_analysis_agent import (
    GroupAnalysisOutput,
    StructureSummary,
    group_analysis_agent,
)
from app.agents.tools import ClassroomToolContext
from app.agents.trace import LocalTraceHooks

RUN_CONFIG = RunConfig(
    workflow_name="classroom-group-analysis",
    tracing_disabled=True,
    trace_include_sensitive_data=False,
)


def _fallback_output(text: str) -> GroupAnalysisOutput:
    summary = (text or "").strip()[:1000] or "模型未返回可用分析"
    return GroupAnalysisOutput(
        summary=summary,
        structure=StructureSummary(),
        metrics_reading=[],
        findings=[],
        interventions=[],
        data_gaps=["模型未按要求返回结构化 JSON"],
        unsupported_claims=[],
    )


def parse_agent_output(text: str) -> GroupAnalysisOutput:
    """解析模型返回的 JSON；失败时降级为纯文本摘要，不让接口 500。"""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return _fallback_output(text)
    try:
        return GroupAnalysisOutput.model_validate(data)
    except ValidationError:
        return _fallback_output(text)


async def run_group_analysis(
    db: Session,
    meeting_id: int,
    question: str,
    max_turns: int = 8,
) -> GroupAnalysisOutput:
    if not question.strip():
        raise ValueError("question 不能为空")
    trace = LocalTraceHooks(meeting_id=meeting_id, question=question.strip())
    try:
        result = await Runner.run(
            group_analysis_agent,
            f"课堂 ID：{meeting_id}\n教师问题：{question.strip()}",
            context=ClassroomToolContext(db),
            max_turns=max(1, min(int(max_turns), 12)),
            hooks=trace,
            run_config=RUN_CONFIG,
        )
        output = parse_agent_output(str(result.final_output or ""))
        trace.finish("success")
        return output
    except Exception as exc:
        trace.finish("error", str(exc))
        raise
    finally:
        trace.write()
