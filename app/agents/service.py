"""Classroom Group Analysis Agent 执行入口。"""

from agents import Runner, RunConfig
from sqlalchemy.orm import Session

from app.agents.group_analysis_agent import GroupAnalysisOutput, group_analysis_agent
from app.agents.tools import ClassroomToolContext
from app.agents.trace import LocalTraceHooks


RUN_CONFIG = RunConfig(
    workflow_name="classroom-group-analysis",
    tracing_disabled=True,
    trace_include_sensitive_data=False,
)


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
        output = result.final_output_as(
            GroupAnalysisOutput, raise_if_incorrect_type=True
        )
        trace.finish("success")
        return output
    except Exception as exc:
        trace.finish("error", str(exc))
        raise
    finally:
        trace.write()
