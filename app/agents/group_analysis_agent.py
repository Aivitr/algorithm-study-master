"""Classroom Group Analysis Agent 定义。"""

from typing import Any, Literal

from agents import Agent, ModelSettings
from pydantic import BaseModel, Field

from app.agents.model import deepseek_model
from app.agents.tools import CLASSROOM_TOOLS, ClassroomToolContext


class StructureSummary(BaseModel):
    groups: list[dict[str, Any]] = Field(default_factory=list)
    bridges: list[dict[str, Any]] = Field(default_factory=list)
    isolates: list[dict[str, Any]] = Field(default_factory=list)


class MetricReading(BaseModel):
    metric: str
    layer: Literal["facts", "quality"]
    value: float | int | None = None
    reading: str
    evidence: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    finding: str
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


class Intervention(BaseModel):
    target: str
    action: str
    script: str
    expected: str
    risk: str
    evidence: list[str] = Field(default_factory=list)


class ProductMetric(BaseModel):
    """预留的产品层指标（本期不填充）。"""

    # TODO(product-metrics): 参与均衡度 / 收敛健康度 / 跨模态一致性 / 共识分歧
    name: str
    value: float | int | None = None
    reading: str = ""
    evidence: list[str] = Field(default_factory=list)


class GroupAnalysisOutput(BaseModel):
    summary: str
    structure: StructureSummary
    metrics_reading: list[MetricReading]
    findings: list[Finding]
    interventions: list[Intervention]
    # TODO(product-metrics): 本期恒为空数组，接口先留好
    product_metrics: list[ProductMetric] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


INSTRUCTIONS = """你是课堂小组分析 Agent。只根据工具返回的数据作答。

指标分两层：
- facts（事实层）：发言数、参与人数、互动、质量分、情绪、知识覆盖，来自 get_classroom_* 工具；
- quality（质量层）：GCA 六指标与时间窗口趋势，来自 get_class_metrics 工具。

规则：
1. 结论必须挂证据：事实层引用 T# 发言编号；质量层暂用 M:<指标名>（如 M:newness）。
2. 两层冲突时以事实层为准，并在 data_gaps 说明原因。
3. GCA 数据不足（status 不是 success/single_speaker）时不要编造，退回事实层。
4. structure 目前没有数据来源时保持空数组，并在 data_gaps 注明“小组结构发现未实现”。
5. product_metrics 本期不要填写，保持空数组。
6. 工具返回 allowed=false 时说明边界，不得绕过门禁。
7. interventions 必须是可执行动作卡：对象、动作、话术、预期、风险、证据。"""


group_analysis_agent = Agent[ClassroomToolContext](
    name="Classroom Group Analysis Agent",
    instructions=INSTRUCTIONS,
    model=deepseek_model,
    model_settings=ModelSettings(temperature=0.2, max_tokens=1600),
    tools=list(CLASSROOM_TOOLS),
    output_type=GroupAnalysisOutput,
)
