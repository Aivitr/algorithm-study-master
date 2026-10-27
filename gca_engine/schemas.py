"""
gca_engine 公共数据格式 —— 统一输入 / 统一输出（负责人：葛艾蓝）。

全员约定（四个人都必须遵守，不要自己另建一套）：

1. 一次 meeting = 一个讨论小组。
2. 学生身份只用 speaker_id（user_id 转成字符串），不用姓名。
3. 时间一律是相对秒数，同一小组使用同一零点，由适配器完成转换。
4. 输入只有一种：Utterance；输出只有一种：GroupAnalysisResult。
5. 状态只用 AnalysisStatus 里的 7 种，不要自己发明
   no_data / empty / error / failed / not_enough 之类的重复状态。
6. 学生六指标只叫这 6 个名字：SIX_METRICS。
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from math import isfinite

# 学生六指标的正式名字（全项目唯一，Agent 组也按这个名字对接）
SIX_METRICS = (
    "participation",
    "internal_cohesion",
    "overall_responsivity",
    "social_impact",
    "newness",
    "communication_density",
)


class AnalysisStatus(str, Enum):
    """分析状态。全项目只允许这 7 种。"""

    SUCCESS = "success"                      # 正常完成
    EMPTY_TRANSCRIPT = "empty_transcript"    # 没有任何发言
    SINGLE_SPEAKER = "single_speaker"        # 只有一名学生（指标仍会计算）
    INSUFFICIENT_DATA = "insufficient_data"  # 发言太少（<2 条）或全部为空
    INVALID_INPUT = "invalid_input"          # 输入格式不对
    NOT_FOUND = "not_found"                  # 找不到这个 meeting_id
    INTERNAL_ERROR = "internal_error"        # 引擎内部出错


@dataclass
class Utterance:
    """一条课堂发言 —— 全项目唯一的输入格式。

    Attributes:
        meeting_id:   讨论小组 ID（字符串）。
        speaker_id:   user_id 转成的字符串。
        text:         适配后的发言文本，尚未分词；课堂适配器已做基础清洗。
        timestamp:    相对秒数（float）；课堂 datetime 以本组最早发言为零点。
        utterance_id: 原 Transcript.id 或任何唯一记录 ID（字符串）。
        end_time:     同一零点的结束秒数，不早于 timestamp；允许 None。
    """

    meeting_id: str
    speaker_id: str
    text: str
    timestamp: float
    utterance_id: str
    end_time: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.meeting_id, str) or not self.meeting_id.strip():
            raise ValueError("meeting_id 必须是非空字符串")
        if not isinstance(self.speaker_id, str) or not self.speaker_id.strip():
            raise ValueError("speaker_id 必须是非空字符串（user_id 转成字符串）")
        if not isinstance(self.text, str):
            raise ValueError("text 必须是字符串")
        if (
            not isinstance(self.timestamp, (int, float))
            or isinstance(self.timestamp, bool)
            or self.timestamp < 0
            or (isinstance(self.timestamp, float) and not isfinite(self.timestamp))
        ):
            raise ValueError("timestamp 必须是 >= 0 的有限数字（课堂开始后的秒数）")
        if not isinstance(self.utterance_id, str) or not self.utterance_id.strip():
            raise ValueError("utterance_id 必须是非空字符串")
        if self.end_time is not None:
            if (
                not isinstance(self.end_time, (int, float))
                or isinstance(self.end_time, bool)
                or self.end_time < 0
                or (isinstance(self.end_time, float) and not isfinite(self.end_time))
            ):
                raise ValueError("end_time 必须是 >= 0 的有限数字或 None")
            if self.end_time < self.timestamp:
                raise ValueError("end_time 不能早于 timestamp")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GroupAnalysisResult:
    """analyze_group(meeting_id) 的统一输出格式。

    timeline 结构（v0.2 已实现，由 gca_engine/windows.py 计算）：
        {
            "fixed_5min": [    # 固定 5 分钟窗口：0-300, 300-600, ...
                {"start_second": 0, "end_second": 300, "group_metrics": {...}},
            ],
            "sliding_5min": [  # 最近 5 分钟滑动窗口，每 30 秒一个更新点
                {"center_second": 30, "group_metrics": {...}},
            ],
        }

    没有发言的窗口 group_metrics 为 {}（不是 None）。固定窗口每段
    左闭右开；滑动窗口取 (center-300, center]，课堂时长不足一个
    更新点时 sliding_5min 为 []。

    timeline 为 None 的情况：EngineConfig(timeline_enabled=False)、
    整体分析失败（错误状态）或 LSA 无法拟合。窗口配置与数量见
    metadata.timeline，失败窗口明细见 metadata.window_errors。
    服务层透传引擎结果，不自行生成时间窗口。
    """

    meeting_id: str
    status: str
    student_metrics: dict[str, dict[str, float]]  # speaker_id -> 六指标
    group_metrics: dict[str, dict[str, float]]    # 指标名 -> mean/min/max/std/count
    timeline: dict | None = None
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
