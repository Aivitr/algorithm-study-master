"""
gca_engine.engagement.triggers —— Hint 触发候选（组长：陈虹宇）。

本轮（正式任务文档限定）只实现两类候选，纯 Python 计算，不调 LLM：

- low_participation  低参与（学生级）：最近滑动窗口内某学生发言明显偏少
- discussion_stall   讨论停滞（小组级）：全组超过阈值秒数没有新发言

阈值依据（重要，不虚构，全部指向 feat/gca 实际代码）：

- 120 秒沉默阈值：已有代码依据 —— app/realtime/connection.py 第 115 行
  is_group_silent(silence_seconds=120)，由 app/routers/realtime.py
  第 348 行 /api/check-silence 调用。
- 0.3 比例与"其他人平均 >= 3 次"：已有代码依据 ——
  app/realtime/connection.py get_quiet_members 第 107-112 行的
  条件 1（my_count == 0 且其他人都有发言）与
  条件 2（others_avg >= 3 且 my_count < others_avg * 0.3）。
  注意：get_quiet_members 的 docstring 还提到"条件 3 兜底：发言次数 <
  threshold（绝对阈值）且其他人都已超过"，但代码主体并未实现该分支，
  故本模块不采用条件 3。
- 连续 2 个更新点（60 秒）、学生冷却 120 秒、小组冷却 300 秒：
  候选配置，无实验依据。前端已有节流先例（static/js/app.js 第 129/133 行
  classroomHintCooldownMs=120000 / topicSuggestionCooldownMs=180000；
  第 3662-3685 行 startSilenceChecks 每 30 秒调 check-silence、
  每 60 秒调 check-quiet-members），需要课堂观察 / A/B 验证后再调整。
  见 HintTriggerConfig.NOTES。
- 5 分钟窗口 / 30 秒步长：与 gca_engine/config.py 的
  SLIDING_WINDOW_SECONDS=300 / SLIDING_STEP_SECONDS=30 一致。

口径约定：

- 输入沿用统一 Utterance 列表（meeting_id / speaker_id / timestamp 均为
  课堂开始后的相对秒数，与 gca_engine/schemas.py 同一口径）。
- 触发评估时刻 now_second 也是课堂相对秒数；实时场景由整合层把墙钟时间
  换算成同一零点后传入。不传时取最后一条发言的时间。
- 滑动窗口与 gca_engine/windows.py 同一口径：(now-300, now]，左开右闭，
  步长 30 秒。
- 低参与的比较对象（两种口径，由 online_members 是否提供决定）：
  * 未提供（None，默认）：只判断"已知发言人"（发言数据里出现过的成员），
    从未发过言的学生不在判断池内，不会被误判为低参与。
  * 提供（list[str]，user_id 转字符串，与 speaker_id 同一口径）：判断池
    为在线名单，与上游 get_quiet_members 口径一致（connection.py:91
    get_online_members 取 WS 连接表成员），从未发过言的在线成员也可能被
    条件 1 命中；空列表表示无人在线，不触发学生级候选。
  在线名单需由 Agent 侧传入（GCA 只能看到发言数据）。
- 数据不足 / 条件不满足时返回 []（不抛异常、不产出候选）；
  输入本身不合法（类型错、meeting_id 空、now_second 为负等）抛 ValueError。
- 本模块只做"候选级冷却"（同一 dedupe_key 在冷却期内只产出一次），
  发送级冷却、教师确认、提示文本生成与记录由 Agent 组负责。
"""

from dataclasses import asdict, dataclass, field
from math import isfinite

from gca_engine.engagement.protocols import HintCandidate
from gca_engine.schemas import Utterance


@dataclass
class HintTriggerConfig:
    """Hint 触发规则的参数（全部可在实例化时覆盖）。"""

    sliding_window_seconds: int = 300   # 与 gca_engine/config.py SLIDING_WINDOW_SECONDS 一致
    sliding_step_seconds: int = 30      # 与 gca_engine/config.py SLIDING_STEP_SECONDS 一致
    stall_silence_seconds: int = 120    # 已有依据：connection.py is_group_silent(120)
    low_participation_min_peers_spoken: int = 1  # 条件1：其他人至少都发过 1 次言
    low_participation_ratio: float = 0.3         # 已有依据：get_quiet_members 条件 2 的 0.3
    low_participation_peers_mean_min: int = 3    # 已有依据：get_quiet_members 的 others_avg >= 3
    min_utterances_total: int = 2       # 与 gca_engine/config.py EngineConfig.min_utterances 一致
    min_utterances_window: int = 2      # 窗口内发言总数少于这个数不触发（数据不足）
    consecutive_points_required: int = 2  # 候选：连续 N 个更新点满足才触发
    student_cooldown_seconds: int = 120   # 候选：学生级冷却（前端已有 120s 节流先例）
    group_cooldown_seconds: int = 300     # 候选：小组级冷却（等于一个完整滑动窗口）

    # 每个参数的依据（如实标注：已有代码依据 / 候选配置 / 口径一致）
    NOTES: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.sliding_window_seconds <= 0 or self.sliding_step_seconds <= 0:
            raise ValueError("窗口参数必须是正整数")
        if self.sliding_step_seconds > self.sliding_window_seconds:
            raise ValueError("sliding_step_seconds 不能大于 sliding_window_seconds")
        if self.stall_silence_seconds <= 0:
            raise ValueError("stall_silence_seconds 必须是正整数")
        if not 0 < self.low_participation_ratio < 1:
            raise ValueError("low_participation_ratio 必须在 (0, 1) 内")
        if self.consecutive_points_required < 1:
            raise ValueError("consecutive_points_required 必须 >= 1")
        if self.student_cooldown_seconds < 0 or self.group_cooldown_seconds < 0:
            raise ValueError("冷却秒数不能为负")
        self.NOTES.update(
            {
                "stall_silence_seconds": (
                    "已有代码依据：app/realtime/connection.py "
                    "is_group_silent(silence_seconds=120)"
                ),
                "low_participation_ratio": (
                    "已有代码依据：connection.py get_quiet_members 条件 2 的 0.3 比例"
                ),
                "low_participation_peers_mean_min": (
                    "已有代码依据：connection.py get_quiet_members 的 others_avg >= 3"
                ),
                "sliding_window_seconds": "与 gca_engine/config.py SLIDING_WINDOW_SECONDS 一致",
                "sliding_step_seconds": "与 gca_engine/config.py SLIDING_STEP_SECONDS 一致",
                "min_utterances_total": "与 gca_engine/config.py EngineConfig.min_utterances 一致",
                "consecutive_points_required": "候选配置，无实验依据",
                "student_cooldown_seconds": "候选配置（前端有 120s 节流先例）",
                "group_cooldown_seconds": "候选配置（等于一个完整滑动窗口）",
            }
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["notes"] = dict(self.NOTES)
        return data


@dataclass
class HintTriggerState:
    """候选级冷却状态（由调用方持有并在多次调用间传递）。

    last_fired: dedupe_key -> 最近一次产出该候选的课堂相对秒数。
    compute_hint_candidates 会原地更新本对象。
    """

    last_fired: dict[str, float] = field(default_factory=dict)


def _last_point_second(utterances: list[Utterance]) -> float:
    """课堂最后一个时间点：max(end_time 或 timestamp)，与 windows.py duration_seconds 口径一致。"""
    total = 0.0
    for u in utterances:
        point = float(u.end_time) if u.end_time is not None else float(u.timestamp)
        if point > total:
            total = point
    return total


def _recent_subset(utterances, end_second: float, window_seconds: int) -> list[Utterance]:
    """取 (end_second - window_seconds, end_second] 内的发言（左开右闭，与 windows.py _subset 同口径）。"""
    start = end_second - window_seconds
    return [u for u in utterances if start < u.timestamp <= end_second]


def _validate_inputs(meeting_id: str, utterances: list[Utterance]) -> None:
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(utterances, list) or not all(
        isinstance(u, Utterance) for u in utterances
    ):
        raise ValueError("utterances 必须是 Utterance 列表")


def _resolve_now(now_second: float | None, utterances: list[Utterance]) -> float:
    """校验并归一化评估时刻：必须是 >= 0 的有限数字；不传时取最后一条发言的时间。"""
    if now_second is None:
        return _last_point_second(utterances)
    if (
        not isinstance(now_second, (int, float))
        or isinstance(now_second, bool)
        or (isinstance(now_second, float) and not isfinite(now_second))
        or now_second < 0
    ):
        raise ValueError("now_second 必须是 >= 0 的有限数字（课堂相对秒数）")
    return float(now_second)


def _validate_online_members(online_members: list[str] | None) -> list[str] | None:
    """校验在线名单：None 表示未提供；否则必须是去重后的 user_id 字符串列表。

    输入格式（与 Agent 组约定）：user_id 转成字符串，与 Utterance.speaker_id
    同一口径。空列表是合法输入（表示无人在线，调用方据此不触发学生级候选）。
    """
    if online_members is None:
        return None
    if not isinstance(online_members, list):
        raise ValueError("online_members 必须是 user_id 字符串列表或 None")
    cleaned: list[str] = []
    for member in online_members:
        if not isinstance(member, str) or not member.strip():
            raise ValueError("online_members 的每项必须是非空字符串（user_id 转成字符串）")
        cleaned.append(member)
    return sorted(set(cleaned))


def _window_condition(utterances: list[Utterance]) -> dict | None:
    """发言统计（一个窗口内），供低参与判断。发言为空返回 None。"""
    if not utterances:
        return None
    counts: dict[str, int] = {}
    for u in utterances:
        counts[u.speaker_id] = counts.get(u.speaker_id, 0) + 1
    return {"counts": counts, "total": len(utterances)}


def _point_condition(
    speaker: str,
    member_pool: set[str],
    subset: list[Utterance],
    config: HintTriggerConfig,
) -> tuple[bool, dict | None]:
    """判断"在某个评估点的窗口内 speaker 是否满足低参与条件"。

    member_pool 是判断池：未提供在线名单时为已知发言人集合，
    提供时为在线名单集合。两条条件对应上游 get_quiet_members 的条件 1 /
    条件 2（其 docstring 里的条件 3 兜底未在代码中实现，本模块不采用）。
    """
    stats = _window_condition(subset)
    if stats is None or stats["total"] < config.min_utterances_window:
        return False, None
    counts: dict[str, int] = stats["counts"]
    peers = sorted(member_pool - {speaker})
    if not peers:
        return False, None
    self_count = counts.get(speaker, 0)
    peer_counts = [counts.get(p, 0) for p in peers]
    peers_spoken = sum(1 for c in peer_counts if c > 0)
    peers_mean = sum(peer_counts) / len(peer_counts) if peer_counts else 0.0

    # 条件1：自己 0 发言，且其他已知成员在窗口内都有发言
    if (
        self_count == 0
        and peers_spoken == len(peer_counts)
        and len(peer_counts) >= config.low_participation_min_peers_spoken
    ):
        return True, {
            "rule": "zero_speech",
            "self_utterances": 0,
            "peer_utterances_mean": peers_mean,
            "peers_spoken": peers_spoken,
            "peers_total": len(peer_counts),
        }
    # 条件2：自己的发言数不足其他人平均的 ratio（且平均 >= 阈值）
    if (
        peers_mean >= config.low_participation_peers_mean_min
        and self_count < peers_mean * config.low_participation_ratio
    ):
        return True, {
            "rule": "low_ratio",
            "self_utterances": self_count,
            "peer_utterances_mean": peers_mean,
            "peers_spoken": peers_spoken,
            "peers_total": len(peer_counts),
            "ratio_threshold": config.low_participation_ratio,
        }
    return False, None


def _reason_text(speaker: str, evidence: dict) -> str:
    if evidence["rule"] == "zero_speech":
        return (
            f"最近窗口内 {speaker} 0 次发言，"
            f"其余 {evidence['peers_total']} 名成员均有发言"
        )
    return (
        f"最近窗口内 {speaker} 发言 {evidence['self_utterances']} 次，"
        f"不足其他成员平均 {evidence['peer_utterances_mean']:g} 次的 "
        f"{int(evidence['ratio_threshold'] * 100)}%"
    )


def low_participation_candidates(
    meeting_id: str,
    utterances: list[Utterance],
    *,
    now_second: float | None = None,
    config: HintTriggerConfig | None = None,
    online_members: list[str] | None = None,
) -> list[HintCandidate]:
    """低参与候选（学生级）。

    条件：最近两个评估点（间隔 sliding_step_seconds）的滑动窗口内，
    判断池中的某成员都满足"0 发言且其他人都发言"或"发言数不足其他人
    平均的 0.3（且平均 >= 3）"，才产出候选。

    判断池由 online_members 决定：
    - None（默认）：已知发言人（发过言的成员）。从未发过言的学生不在池内，
      不会被误判为低参与。
    - list[str]（user_id 转字符串，与 speaker_id 同一口径）：在线名单，
      与上游 get_quiet_members 口径一致，从未发过言的在线成员也可能被
      条件 1 命中；空列表表示无人在线，不触发。

    数据不足（整节课发言 < min_utterances_total、判断池成员 < 2、
    窗口内发言 < min_utterances_window）时返回 []。

    教育口径：低发言不等于低学习投入（可能是在听讲、思考），因此要求
    "对比其他成员明显偏低"且"连续两个评估点"，并只产出候选，由教师把关。
    """
    _validate_inputs(meeting_id, utterances)
    config = config or HintTriggerConfig()
    if len(utterances) < config.min_utterances_total:
        return []
    online = _validate_online_members(online_members)
    if online is not None:
        # 提供了在线名单：判断池 = 在线名单（与上游 get_quiet_members 口径一致）
        pool: set[str] = set(online)
    else:
        # 未提供：判断池 = 已知发言人，从未发过言的学生不会被误判
        pool = {u.speaker_id for u in utterances}
    if len(pool) < 2:
        return []

    now = _resolve_now(now_second, utterances)
    step = config.sliding_step_seconds
    window = config.sliding_window_seconds

    candidates: list[HintCandidate] = []
    for speaker in sorted(pool):
        ok, evidence = _point_condition(
            speaker, pool, _recent_subset(utterances, now, window), config
        )
        if not ok:
            continue
        # 连续 N 个更新点：上一个评估点的窗口也要满足（课堂不足一个更新点时不触发）
        consecutive = 1
        if config.consecutive_points_required > 1:
            if now < step:
                continue
            prev_ok, _ = _point_condition(
                speaker, pool,
                _recent_subset(utterances, now - step, window), config,
            )
            if not prev_ok:
                continue
            consecutive = config.consecutive_points_required
        evidence["consecutive_points"] = consecutive
        candidates.append(
            HintCandidate(
                meeting_id=meeting_id,
                hint_type="low_participation",
                target_type="student",
                target_user_id=speaker,
                window={"start_second": max(0.0, now - window), "end_second": now},
                trigger_reason=_reason_text(speaker, evidence),
                evidence=evidence,
                data_status="ok",
                generated_at=now,
                dedupe_key=f"low_participation:{meeting_id}:student:{speaker}",
            )
        )
    return candidates


def discussion_stall_candidates(
    meeting_id: str,
    utterances: list[Utterance],
    *,
    now_second: float | None = None,
    config: HintTriggerConfig | None = None,
) -> list[HintCandidate]:
    """讨论停滞候选（小组级）。

    条件：距最后一条发言（max(end_time, timestamp)）超过
    stall_silence_seconds 秒。数据不足（整节课发言 < min_utterances_total）
    时返回 []。课堂状态（进行中/已结束）由调用方/Agent 侧把关。

    教育口径：无新发言不等于讨论无效（可能正在阅读或独立解题），
    停滞候选只是给教师/Agent 提供干预时机，不代表讨论失败。
    """
    _validate_inputs(meeting_id, utterances)
    config = config or HintTriggerConfig()
    if len(utterances) < config.min_utterances_total:
        return []
    now = _resolve_now(now_second, utterances)
    last = _last_point_second(utterances)
    silence = now - last
    if silence < config.stall_silence_seconds:
        return []
    window = config.sliding_window_seconds
    return [
        HintCandidate(
            meeting_id=meeting_id,
            hint_type="discussion_stall",
            target_type="group",
            target_user_id=None,
            window={"start_second": max(0.0, now - window), "end_second": now},
            trigger_reason=(
                f"全组已 {silence:g} 秒没有新发言"
                f"（阈值 {config.stall_silence_seconds} 秒）"
            ),
            evidence={
                "last_speech_second": last,
                "silence_seconds": silence,
                "threshold_seconds": config.stall_silence_seconds,
            },
            data_status="ok",
            generated_at=now,
            dedupe_key=f"discussion_stall:{meeting_id}:group:all",
        )
    ]


def compute_hint_candidates(
    meeting_id: str,
    utterances: list[Utterance],
    *,
    now_second: float | None = None,
    config: HintTriggerConfig | None = None,
    state: HintTriggerState | None = None,
    online_members: list[str] | None = None,
) -> list[HintCandidate]:
    """一次评估两类候选，并做候选级冷却。

    冷却：同一 dedupe_key 在冷却期内只产出一次。学生级冷却
    student_cooldown_seconds（默认 120），小组级 group_cooldown_seconds
    （默认 300）。state 会被原地更新，调用方跨轮持有同一个对象即可。

    online_members 只影响低参与候选（见 low_participation_candidates），
    停滞候选与在线名单无关。

    Agent 组集成方式（建议，不改 Agent 核心逻辑）：
    - 由整合层每 30 秒（与滑动窗口步长一致）调用本函数，课堂相对秒数
      由整合层换算后传入 now_second。
    - 拿到候选后用 trigger_reason / evidence 组装 Prompt（Agent 组职责），
      发送级冷却可复用 dedupe_key（两层冷却不冲突）。
    - 与旧接口 /api/check-silence、/api/check-quiet-members 的去留
      需与 Agent 组长确认（见 docs/engagement_protocol.md 待确认项）。
    """
    _validate_inputs(meeting_id, utterances)
    config = config or HintTriggerConfig()
    state = state if state is not None else HintTriggerState()
    now = _resolve_now(now_second, utterances)

    merged = low_participation_candidates(
        meeting_id, utterances, now_second=now, config=config,
        online_members=online_members,
    ) + discussion_stall_candidates(
        meeting_id, utterances, now_second=now, config=config
    )

    out: list[HintCandidate] = []
    for candidate in merged:
        cooldown = (
            config.student_cooldown_seconds
            if candidate.target_type == "student"
            else config.group_cooldown_seconds
        )
        last = state.last_fired.get(candidate.dedupe_key, float("-inf"))
        if now - last < cooldown:
            continue
        state.last_fired[candidate.dedupe_key] = now
        out.append(candidate)
    return out
