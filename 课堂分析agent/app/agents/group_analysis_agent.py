"""Classroom Group Analysis Agent 定义。"""

from typing import Literal

from agents import Agent, ModelSettings
from pydantic import BaseModel

from app.agents.model import deepseek_model
from app.agents.tools import CLASSROOM_TOOLS, ClassroomToolContext


class AnalysisFinding(BaseModel):
    claim: str
    evidence_ids: list[str]
    confidence: Literal["high", "medium", "low"]


class GroupAnalysisOutput(BaseModel):
    summary: str
    structure: str
    metrics_reading: list[str]
    findings: list[AnalysisFinding]
    interventions: list[str]
    data_gaps: list[str]
    unsupported_claims: list[str]


INSTRUCTIONS = """你是课堂小组分析 Agent。只根据工具返回的数据作答。
先读取统计，再按问题读取发言或知识点；结论引用 T# 证据，不得补造数据。
工具返回 allowed=false 时说明边界，不得绕过门禁。数据不足写入 data_gaps。
structure 说明课堂参与与互动结构；metrics_reading 解释已有数值；interventions 只给可执行建议。
没有工具证据的判断不得写入 findings，放入 unsupported_claims。"""


group_analysis_agent = Agent[ClassroomToolContext](
    name="Classroom Group Analysis Agent",
    instructions=INSTRUCTIONS,
    model=deepseek_model,
    model_settings=ModelSettings(temperature=0.2, max_tokens=1600),
    tools=list(CLASSROOM_TOOLS),
    output_type=GroupAnalysisOutput,
)
