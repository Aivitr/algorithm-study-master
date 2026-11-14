"""
gca_engine.engagement.protocols —— 第二阶段三维学习投入公共数据结构（组长：陈虹宇）。

本包是 gca_engine 的新增子包（非上游 vendor 快照内容），只依赖 gca_engine.schemas
与 Python 标准库，不新增任何第三方依赖、数据库表或 LLM 调用。

两个层面、两套状态（互不替代）：

- 整体分析状态：沿用 gca_engine.schemas.AnalysisStatus 的 7 种
  （success / empty_transcript / single_speaker / insufficient_data /
  invalid_input / not_found / internal_error），Agent 组已按它对接，
  EngagementResult.status 用它。
- 单维度数据状态：本文件的 DIMENSION_STATUS 三值
  （ok / insufficient / unavailable），回答"某一个维度的数据够不够"，
  EngagementDimensionResult.status 用它。

对应任务文档的三条评论：评论 1（统一成什么）→ EngagementResult /
EngagementDimensionResult；评论 2（状态定义）→ 上面两套状态；
评论 3（Hint 规则与输出字段）→ gca_engine/engagement/triggers.py 与 HintCandidate。
详细口径与 JSON 样例见 docs/engagement_protocol.md。

上游数据对应关系（feat/gca 实际代码，2026-11-14 核对）：

- EmotionRecord       对应 app/models/emotion.py 的 EmotionLog
  （meeting_id / user_id / emotion_type / intensity / created_at）。
  注意 EmotionLog 没有"课堂相对秒数"字段：created_at 是墙钟时间、
  video_start_time 是视频内秒数。适配层必须像 app/services/gca_service.py
  analyze_meeting_metrics 那样，用 meeting.started_at 换算成课堂零点相对秒数。
- SpeechQualityRecord 对应 app/models/transcript.py 的 Transcript
  quality_score（Integer 0-100，默认 0）/ relevance_score（Integer，默认 0）/
  quality_feedback（NVARCHAR）。注意默认值 0 表示"尚未打分"，
  缺失率统计应由适配层依据 quality_feedback 是否有值来判定，不能只看 0。
- Utterance           复用 gca_engine.schemas.Utterance；当前课堂适配器
  gca_engine/adapters/classroom.py 一律传 end_time=None（第 99 行），
  因此行为维度的"发言时长"在真实数据里暂不可用，本轮只统计次数/频率。
"""

from dataclasses import asdict, dataclass, field
from math import isfinite

from gca_engine.schemas import AnalysisStatus

# 三个维度的正式名字（全项目唯一，整合层与前端按这个名字读）
DIMENSIONS = ("emotional", "behavioral", "cognitive")

# 单维度数据状态：与整体 AnalysisStatus 7 种互不替代
DIMENSION_STATUS = ("ok", "insufficient", "unavailable")

# Hint 候选类型：本轮只有两类（正式任务文档限定）
HINT_TYPES = ("low_participation", "discussion_stall")

# Hint 候选目标类型
TARGET_TYPES = ("student", "group")


@dataclass
class EmotionRecord:
    """一条情绪记录（上游 EmotionLog 的适配输入）。

    Attributes:
        meeting_id:  讨论小组 ID（字符串，与 Utterance.meeting_id 同一口径）。
        user_id:     user_id 转成的字符串（与 Utterance.speaker_id 同一口径）。
        emotion_type: 归一化情绪标签（上游 app/core/emotions.py
                     normalize_emotion_label 的词表）。
        timestamp:   课堂开始后的相对秒数（float）；适配层用 meeting.started_at
                     换算，与 Utterance.timestamp 同一零点。
        intensity:   情绪强度（可选，上游 EmotionLog.intensity）。
        source:      来源（可选，"video" / "audio" / "transcript"）。
        record_id:   上游 EmotionLog.id（可选，用于排查）。
    """

    meeting_id: str
    user_id: str
    emotion_type: str
    timestamp: float
    intensity: float | None = None
    source: str | None = None
    record_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.meeting_id, str) or not self.meeting_id.strip():
            raise ValueError("meeting_id 必须是非空字符串")
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("user_id 必须是非空字符串（user_id 转成字符串）")
        if not isinstance(self.emotion_type, str) or not self.emotion_type.strip():
            raise ValueError("emotion_type 必须是非空字符串")
        if (
            not isinstance(self.timestamp, (int, float))
            or isinstance(self.timestamp, bool)
            or self.timestamp < 0
            or (isinstance(self.timestamp, float) and not isfinite(self.timestamp))
        ):
            raise ValueError("timestamp 必须是 >= 0 的有限数字（课堂开始后的秒数）")
        for name in ("intensity",):
            value = getattr(self, name)
            if value is not None and not (isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))):
                raise ValueError(f"{name} 必须是有限数字或 None")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpeechQualityRecord:
    """一条发言质量评分（上游 Transcript 的 LLM 打分适配输入）。

    Attributes:
        utterance_id:   对应 Utterance.utterance_id（Transcript.id 字符串）。
        quality_score:  0-100 质量分（可选；上游默认 0 表示未打分）。
        relevance_score: 相关性分（可选；上游为 Integer）。
        feedback:       质量反馈文本（可选；上游 quality_feedback）。
    """

    utterance_id: str
    quality_score: float | None = None
    relevance_score: float | None = None
    feedback: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.utterance_id, str) or not self.utterance_id.strip():
            raise ValueError("utterance_id 必须是非空字符串")
        for name in ("quality_score", "relevance_score"):
            value = getattr(self, name)
            if value is not None and not (isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))):
                raise ValueError(f"{name} 必须是有限数字或 None")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EngagementDimensionResult:
    """单维度输出（三个维度模块统一返回它）。

    约定（三人必须遵守）：
    - status 只允许 DIMENSION_STATUS 三值，不允许用 AnalysisStatus 的
      success 等 7 种（两套状态体系不能混）。
    - student_metrics / group_metrics 无数据时给 {}（不是 None）；
      timeline 不可用时给 None。
    - 小组统计口径与 gca_engine/aggregation.py 的 group_metric_stats 一致：
      {指标名: {mean, min, max, std, count}}，无数据时 {}。
    - 本轮不输出 E_e / E_b / E_c 综合分（无标注数据，权重阈值无依据），
      只输出可解释的基础指标（分布、计数、趋势、质量）。
    """

    dimension: str
    status: str
    student_metrics: dict = field(default_factory=dict)
    group_metrics: dict = field(default_factory=dict)
    timeline: dict | None = None
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"dimension 必须是 {DIMENSIONS} 之一")
        if self.status not in DIMENSION_STATUS:
            raise ValueError(f"status 必须是 {DIMENSION_STATUS} 之一（不是 AnalysisStatus）")
        if not isinstance(self.student_metrics, dict):
            raise ValueError("student_metrics 必须是 dict")
        if not isinstance(self.group_metrics, dict):
            raise ValueError("group_metrics 必须是 dict")

    def to_dict(self) -> dict:
        return asdict(self)


def dimension_result(
    dimension: str,
    status: str,
    *,
    student_metrics: dict | None = None,
    group_metrics: dict | None = None,
    timeline: dict | None = None,
    metadata: dict | None = None,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> EngagementDimensionResult:
    """单维度结果工厂：无数据时自动给 {} / None，避免手写空结构。"""
    return EngagementDimensionResult(
        dimension=dimension,
        status=status,
        student_metrics=student_metrics or {},
        group_metrics=group_metrics or {},
        timeline=timeline,
        metadata=metadata or {},
        warnings=warnings or [],
        error=error,
    )


@dataclass
class EngagementResult:
    """三维学习投入整合输出。

    - dimensions 必须三键齐全（emotional / behavioral / cognitive），
      缺任一键即校验失败——保证前端/Agent 组可以无条件读三个键。
    - status 用 AnalysisStatus 7 种（success / insufficient_data 等）。
    - student_metrics / group_metrics 是三个维度结果的投影
      （{user_id: {维度名: 指标}} / {维度名: {指标名: 统计}}），
      由整合层投影，不重复计算。
    - timeline 整合层的（可选）；metadata 带 engine 版本与各维度状态。
    """

    meeting_id: str
    status: str
    dimensions: dict[str, EngagementDimensionResult]
    student_metrics: dict = field(default_factory=dict)
    group_metrics: dict = field(default_factory=dict)
    timeline: dict | None = None
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.meeting_id, str) or not self.meeting_id.strip():
            raise ValueError("meeting_id 必须是非空字符串")
        if self.status not in {s.value for s in AnalysisStatus}:
            raise ValueError(f"status 必须是 AnalysisStatus 7 种之一：{[s.value for s in AnalysisStatus]}")
        if not isinstance(self.dimensions, dict):
            raise ValueError("dimensions 必须是 dict，且 emotional/behavioral/cognitive 三键齐全")
        missing = [d for d in DIMENSIONS if d not in self.dimensions]
        if missing:
            raise ValueError(f"dimensions 缺少维度键：{missing}（三键必须齐全）")
        for name, dim_result in self.dimensions.items():
            if not isinstance(dim_result, EngagementDimensionResult):
                raise ValueError(f"dimensions[{name!r}] 必须是 EngagementDimensionResult")

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


@dataclass
class HintCandidate:
    """Hint 触发候选（GCA → Agent 的输出，见 docs/engagement_protocol.md 第 6 节）。

    GCA 组只产候选 + 可解释证据，不调用 LLM、不发送任何提示；
    LLM 文本生成 / 教师确认 / WebSocket 发送 / 记录由 Agent 组负责。

    上游旧触发逻辑与本候选的分工差异（feat/gca 实际代码）：
    - 旧实现 app/routers/realtime.py /api/check-silence（第 348 行）与
      /api/check-quiet-members（第 393 行）：触发判断 + LLM 生成 + 发送
      在同一端点，无教师确认、无记录反馈、按"在线成员"
      （app/realtime/connection.py get_online_members，WS 连接表）比较。
    - 本候选：只做触发判断（按"已知发言人"，即发言数据里的成员），
      生成/发送/确认留给 Agent 组。旧接口去留需与 Agent 组长确认。
    """

    meeting_id: str
    hint_type: str
    target_type: str
    target_user_id: str | None
    window: dict
    trigger_reason: str
    evidence: dict
    data_status: str
    generated_at: float
    dedupe_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.meeting_id, str) or not self.meeting_id.strip():
            raise ValueError("meeting_id 必须是非空字符串")
        if self.hint_type not in HINT_TYPES:
            raise ValueError(f"hint_type 必须是 {HINT_TYPES} 之一")
        if self.target_type not in TARGET_TYPES:
            raise ValueError(f"target_type 必须是 {TARGET_TYPES} 之一")
        if self.target_type == "student" and (
            not isinstance(self.target_user_id, str) or not self.target_user_id.strip()
        ):
            raise ValueError("学生级候选必须给非空 target_user_id")
        if self.target_type == "group" and self.target_user_id is not None:
            raise ValueError("小组级候选的 target_user_id 必须是 None")
        if not isinstance(self.window, dict) or "start_second" not in self.window or "end_second" not in self.window:
            raise ValueError("window 必须是含 start_second / end_second 的 dict")
        for key in ("start_second", "end_second"):
            value = self.window.get(key)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or (isinstance(value, float) and not isfinite(value))
            ):
                raise ValueError(f"window[{key!r}] 必须是有限数字")
        if self.window["start_second"] > self.window["end_second"]:
            raise ValueError("window 的 start_second 不能大于 end_second")
        if self.data_status != "ok":
            raise ValueError("data_status 恒为 ok（数据不足时不产出候选）")
        if (
            not isinstance(self.generated_at, (int, float))
            or isinstance(self.generated_at, bool)
            or self.generated_at < 0
            or (isinstance(self.generated_at, float) and not isfinite(self.generated_at))
        ):
            raise ValueError("generated_at 必须是 >= 0 的有限数字（课堂相对秒数）")
        if not isinstance(self.dedupe_key, str) or not self.dedupe_key.strip():
            raise ValueError("dedupe_key 必须是非空字符串")

    def to_dict(self) -> dict:
        return asdict(self)
