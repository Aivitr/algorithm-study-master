# -*- coding: utf-8 -*-
"""课堂小组分析智能体（Classroom Group Analysis Agent）——单文件实现。

这个小文件是"Agent Harness 第一版"的落地形态，刻意做成**单文件、零新依赖**：
复用项目里已经装好的 `openai`（走 DeepSeek 的 OpenAI 兼容接口）、已有的 SQLAlchemy
模型（database.py）和已有的研究算法模块（research_algorithm_fusion.py），不改动任何
现有业务链路。以后要换成 OpenAI Agents SDK，只需把 `MiniHarness` 换成
`agents.Runner`，工具函数可以原样用 `@function_tool` 包起来。

设计定位
--------
不做"拼一个巨型 Prompt 直接吐报表"的机器人，而是做一个**基于测量、可追溯、能收口**
的课堂协作诊断智能体：

1. **测量与推理分离**：所有数字都由确定性算法算出来（六个 GCA 指标、社群发现、
   历史基线），LLM 只负责选择工具、解读数据、给出建议，不允许自己估算指标。
2. **证据账本**：每次工具调用都会登记证据条目（E#序号），指向具体发言（T#id）或
   指标口径；最终报告里的每条结论都要挂证据编号，最后再跑一轮自检，把没有证据
   支持的结论降级为"推测"。
3. **无标签小组发现**：项目数据库里没有"小组"实体（`/api/class-groups` 实际是按学生
   个人统计，`MemberConnection` 只是在线状态），所以本 Agent 直接从交互网络做标签
   传播，自动发现协作子群、桥接人和被孤立者，不需要改表。
4. **跨模态错位检测**：利用项目独有的 `cross_modal_consistency`、`audio_tone`、
   `body_action` 字段，找"嘴上附和、表情困惑"的发言点。
5. **干预闭环**：输出结构化干预动作卡（对象/动作/话术/预期影响/风险），并可通过
   `dispatch_intervention` 一键下发（写操作，必须人工确认）。

课堂生命周期与工具白名单（Policy）
----------------------------------
数据库 meetings.status 只有 active/paused/ended，本模块在此基础上推导统一三态：

    created（已建课未开课） -> running（进行中） -> ended（已结束）

    Tool                      allowed_states          policy
    get_meeting_context       created/running/ended   read
    discover_groups           running/ended           read
    get_group_evidence        running/ended           read
    compute_group_metrics     running/ended           read
    get_knowledge_trace       running/ended           read
    find_learning_gaps        running/ended           read
    simulate_intervention     running/ended           read
    dispatch_intervention     running                 write（需人工确认）

每次工具调用前都会经过 `check_tool_allowed()`；状态不允许时**不抛异常**，而是把结构化
拒绝原因 + 替代工具建议交回给模型，避免 Agent 因为一次越权调用而整轮崩溃。

三档时延预算（模式）
--------------------
    realtime     只给测量类工具，最多 4 轮，不做自检，供课堂中实时提醒
    on_demand    全部只读工具，最多 8 轮，带自检，供教师随堂提问
    after_class  全部只读工具，最多 12 轮，带自检，供课后深度复盘

用法
----
    venv\\Scripts\\python.exe group_analysis_agent.py --tools      # 工具与策略表
    venv\\Scripts\\python.exe group_analysis_agent.py --selftest   # 纯算法自检（离线）
    venv\\Scripts\\python.exe group_analysis_agent.py --check      # 环境体检
    venv\\Scripts\\python.exe group_analysis_agent.py --meeting-id 12 --mode on_demand \\
        --question "分析这个班的讨论，参与是否均衡，我该不该干预"

挂到 FastAPI（在 server.py 里加一行即可，本文件不主动修改 server.py）：

    from group_analysis_agent import router as agent_router
    app.include_router(agent_router)

注意：`dispatch_intervention` 下发的 WebSocket 消息类型是 `agent_intervention`，前端目前
还没有对应渲染分支（现前端只处理 new_speech / new_speech_fast 等既有类型），首次演示
建议只跑到"生成动作卡"为止，前端接入后再开放一键下发。
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
import re
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import settings  # noqa: E402  复用现有配置层（内部已加载 .env）

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

STATE_CREATED = "created"
STATE_RUNNING = "running"
STATE_ENDED = "ended"

POLICY_READ = "read"
POLICY_WRITE = "write"

MODE_REALTIME = "realtime"
MODE_ON_DEMAND = "on_demand"
MODE_AFTER_CLASS = "after_class"

MODE_BUDGETS: Dict[str, Dict[str, Any]] = {
    MODE_REALTIME: {
        "max_turns": 4,
        "max_evidence": 6,
        "self_check": False,
        "temperature": 0.1,
        "note": "课堂中实时使用，只允许测量类工具，不做自检以控制时延",
    },
    MODE_ON_DEMAND: {
        "max_turns": 8,
        "max_evidence": 12,
        "self_check": True,
        "temperature": 0.2,
        "note": "教师随堂提问，允许全部只读工具并做证据自检",
    },
    MODE_AFTER_CLASS: {
        "max_turns": 12,
        "max_evidence": 24,
        "self_check": True,
        "temperature": 0.1,
        "note": "课后深度复盘，证据预算最大",
    },
}

NEGATIVE_EMOTIONS = {
    "sad", "angry", "anxious", "confused", "bored", "disgusted", "fearful",
    "frustrated", "tired", "worried", "upset", "悲伤", "生气", "焦虑", "困惑",
    "无聊", "厌恶", "害怕", "沮丧", "疲惫", "担心",
}
POSITIVE_EMOTIONS = {
    "happy", "excited", "surprised", "calm", "confident", "开心", "高兴",
    "兴奋", "惊喜", "平静", "自信",
}

SUPPORT_CUES = ("同意", "赞同", "没错", "对对", "支持", "确实", "有道理", "补充", "附议", "也是", "对呀", "是的")
DISSENT_CUES = ("但是", "不过", "然而", "不同意", "不赞同", "相反", "有问题", "不对", "质疑", "不一定", "其实不", "这个说法")

GCA_WEIGHTS = {
    "participation_balance": 0.20,
    "interaction_structure": 0.20,
    "information_gain": 0.15,
    "convergence_health": 0.15,
    "cross_modal_consistency": 0.15,
    "consensus_dissent": 0.15,
}

TRACE_DIR = BASE_DIR / "storage" / "agent_traces"
AGENT_NAME = "Classroom Group Analysis Agent"


# ---------------------------------------------------------------------------
# 基础工具函数
# ---------------------------------------------------------------------------

def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    if math.isnan(number):
        return low
    return max(low, min(high, number))


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _round(value: Any, digits: int = 3) -> Optional[float]:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _confidence(sample_size: int, *, good: int = 12, fair: int = 5) -> str:
    if sample_size >= good:
        return "high"
    if sample_size >= fair:
        return "medium"
    return "low"


def _db_module():
    """延迟导入项目现有 ORM 层，避免没有数据库时"导入即连接"。"""
    import database  # noqa: WPS433  复用现有模型定义

    return database


def _open_session():
    return _db_module().SessionLocal()


def _session_scope():
    """返回 (db, closer)，调用方负责在 finally 里 closer()。"""
    db = _open_session()
    return db, db.close


def _joinedload():
    from sqlalchemy.orm import joinedload

    return joinedload


# ---------------------------------------------------------------------------
# 证据账本
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    eid: str
    kind: str
    label: str
    ref: Optional[str] = None
    confidence: Optional[float] = None
    detail: Dict[str, Any] = field(default_factory=dict)


class EvidenceLedger:
    """登记本次 Run 用到的全部证据，供模型引用、供自检回查、供前端展示。"""

    def __init__(self) -> None:
        self._items: List[Evidence] = []

    def add(
        self,
        kind: str,
        label: str,
        detail: Optional[Dict[str, Any]] = None,
        ref: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> str:
        eid = "E%d" % (len(self._items) + 1)
        self._items.append(
            Evidence(
                eid=eid,
                kind=kind,
                label=_safe_text(label)[:160],
                ref=ref,
                confidence=confidence,
                detail=detail or {},
            )
        )
        return eid

    def items(self) -> List[Evidence]:
        return list(self._items)

    def table(self) -> List[Dict[str, Any]]:
        return [asdict(item) for item in self._items]

    def prompt_block(self, limit: int = 12) -> str:
        if not self._items:
            return "(暂无证据)"
        lines = []
        for item in self._items[-max(1, int(limit)):]:
            ref = " [%s]" % item.ref if item.ref else ""
            lines.append("%s(%s)%s %s" % (item.eid, item.kind, ref, item.label))
        return "\n".join(lines)

    def refs(self) -> List[str]:
        return [item.eid for item in self._items]


@dataclass
class ToolContext:
    ledger: EvidenceLedger
    mode: str = MODE_ON_DEMAND
    approved: bool = False
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 生命周期 + Policy
# ---------------------------------------------------------------------------

def resolve_classroom_state(meeting: Any, db: Any) -> str:
    """把数据库的 active/paused/ended 推导成统一的三态生命周期。"""
    dbm = _db_module()
    raw = _safe_text(getattr(meeting, "status", "")).lower()
    if raw in {"ended", "closed", "finished"}:
        return STATE_ENDED
    if raw in {"paused", "draft", "created"}:
        return STATE_CREATED

    meeting_id = getattr(meeting, "id", None)
    has_transcript = db.query(dbm.Transcript.id).filter(dbm.Transcript.meeting_id == meeting_id).first() is not None
    if has_transcript:
        return STATE_RUNNING
    has_member = db.query(dbm.MemberConnection.id).filter(dbm.MemberConnection.meeting_id == meeting_id).first() is not None
    return STATE_RUNNING if has_member else STATE_CREATED


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: Dict[str, Any]
    allowed_states: Tuple[str, ...]
    policy: str = POLICY_READ
    modes: Tuple[str, ...] = (MODE_REALTIME, MODE_ON_DEMAND, MODE_AFTER_CLASS)
    requires_approval: bool = False
    latency: str = "fast"

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


TOOL_SPECS: Dict[str, ToolSpec] = {}


def _register(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    allowed_states: Tuple[str, ...],
    *,
    policy: str = POLICY_READ,
    modes: Tuple[str, ...] = (MODE_REALTIME, MODE_ON_DEMAND, MODE_AFTER_CLASS),
    requires_approval: bool = False,
    latency: str = "fast",
):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        TOOL_SPECS[name] = ToolSpec(
            name=name,
            description=description,
            handler=func,
            parameters=parameters,
            allowed_states=allowed_states,
            policy=policy,
            modes=modes,
            requires_approval=requires_approval,
            latency=latency,
        )
        return func

    return decorator


def _tool_schemas(mode: str) -> List[Dict[str, Any]]:
    return [spec.schema() for spec in TOOL_SPECS.values() if mode in spec.modes]


def check_tool_allowed(spec: ToolSpec, meeting_id: int, db: Any, mode: str, approved: bool) -> Dict[str, Any]:
    """工具执行前的统一门禁：模式、课堂状态、人工审批三道检查，失败不抛异常。"""
    dbm = _db_module()
    if mode not in spec.modes:
        return {
            "allowed": False,
            "reason": "工具 %s 不支持 %s 模式" % (spec.name, mode),
            "suggested_tools": [s.name for s in TOOL_SPECS.values() if mode in s.modes][:4],
        }

    meeting = db.query(dbm.Meeting).filter(dbm.Meeting.id == meeting_id).first()
    if meeting is None:
        return {"allowed": False, "reason": "课堂 %s 不存在" % meeting_id}

    state = resolve_classroom_state(meeting, db)
    if state not in spec.allowed_states:
        alternatives = [
            s.name
            for s in TOOL_SPECS.values()
            if state in s.allowed_states and mode in s.modes and s.name != spec.name
        ]
        return {
            "allowed": False,
            "reason": "当前课堂状态为 %s，工具 %s 只允许在 %s 下调用" % (state, spec.name, "/".join(spec.allowed_states)),
            "state": state,
            "suggested_tools": alternatives[:4],
        }

    if spec.requires_approval and not approved:
        return {
            "allowed": False,
            "requires_approval": True,
            "state": state,
            "reason": "工具 %s 属于写操作，必须由教师确认后才能执行" % spec.name,
        }

    return {"allowed": True, "state": state}


# ---------------------------------------------------------------------------
# 纯计算层（不依赖数据库，可单测）
# ---------------------------------------------------------------------------

def normalized_entropy(counts: Sequence[float]) -> float:
    values = [float(c) for c in counts if c is not None and float(c) >= 0]
    total = sum(values)
    if len(values) <= 1 or total <= 0:
        return 0.0
    probs = [v / total for v in values]
    entropy = -sum(p * math.log(p) for p in probs if p > 0)
    return _clamp(entropy / math.log(len(values)))


def gini(counts: Sequence[float]) -> float:
    values = sorted(float(c) for c in counts if c is not None and float(c) >= 0)
    total = sum(values)
    if not values or total <= 0:
        return 0.0
    n = len(values)
    weighted = sum((index + 1) * value for index, value in enumerate(values))
    return _clamp((2.0 * weighted) / (n * total) - (n + 1.0) / n)


def metric_participation_balance(speech_counts: Sequence[int]) -> Dict[str, Any]:
    counts = [int(c or 0) for c in speech_counts]
    if not counts:
        return {"value": None, "raw": {}, "formula": "无数据", "sample_size": 0, "confidence": "low", "higher_is_better": True}
    entropy = normalized_entropy(counts)
    gini_value = gini(counts)
    value = _clamp(0.6 * entropy + 0.4 * (1.0 - gini_value))
    return {
        "value": _round(value),
        "raw": {
            "normalized_entropy": _round(entropy),
            "gini": _round(gini_value),
            "min_speeches": min(counts),
            "max_speeches": max(counts),
            "total_speeches": sum(counts),
        },
        "formula": "0.6 * 归一化熵(发言次数) + 0.4 * (1 - 基尼系数)",
        "sample_size": len(counts),
        "confidence": _confidence(len(counts), good=4, fair=3),
        "higher_is_better": True,
    }


def metric_interaction_structure(members: Sequence[str], interactions: Dict[Tuple[str, str], int]) -> Dict[str, Any]:
    people = list(dict.fromkeys([m for m in members if m]))
    if len(people) < 2:
        return {"value": None, "raw": {}, "formula": "成员不足 2 人", "sample_size": len(people), "confidence": "low", "higher_is_better": True}

    pair_weights: Dict[Tuple[str, str], List[int]] = {}
    for (src, dst), count in interactions.items():
        if src == dst or src not in people or dst not in people:
            continue
        key = (src, dst) if src < dst else (dst, src)
        slot = pair_weights.setdefault(key, [0, 0])
        if src == key[0]:
            slot[0] += int(count)
        else:
            slot[1] += int(count)

    possible = len(people) * (len(people) - 1) / 2.0
    active_pairs = len(pair_weights)
    density = active_pairs / possible if possible else 0.0

    mutual = 0.0
    total_weight = 0.0
    for left, right in pair_weights.values():
        weight = left + right
        if weight <= 0:
            continue
        mutual += 2.0 * min(left, right)
        total_weight += weight
    reciprocity = mutual / total_weight if total_weight > 0 else 0.0

    value = _clamp(0.5 * min(1.0, density / 0.6) + 0.5 * reciprocity)
    return {
        "value": _round(value),
        "raw": {
            "density": _round(density),
            "reciprocity": _round(reciprocity),
            "active_pairs": active_pairs,
            "possible_pairs": int(possible),
        },
        "formula": "0.5 * min(1, 交互密度/0.6) + 0.5 * 双向互惠率",
        "sample_size": sum(int(v) for v in interactions.values()),
        "confidence": _confidence(active_pairs, good=4, fair=2),
        "higher_is_better": True,
    }


def _normalize_emotion(label: Any) -> str:
    raw = _safe_text(label).lower()
    if not raw:
        return ""
    return raw.split("|", 1)[0].strip().replace(" ", "_").replace("-", "_")


def is_cross_modal_mismatch(row: Dict[str, Any]) -> Tuple[bool, str]:
    """判断一条发言是否出现"说的"和"表现出的"不一致。"""
    emotion = _normalize_emotion(row.get("emotion_tag"))
    tone = _normalize_emotion(row.get("audio_tone"))
    consistency = row.get("cross_modal_consistency")
    text = _safe_text(row.get("text"))

    if consistency is not None:
        try:
            if float(consistency) < 0.5:
                return True, "cross_modal_consistency<0.5"
        except (TypeError, ValueError):
            pass
    if emotion in NEGATIVE_EMOTIONS and tone in POSITIVE_EMOTIONS:
        return True, "表情负向但语调正向"
    if emotion in NEGATIVE_EMOTIONS and any(cue in text for cue in SUPPORT_CUES):
        return True, "表情负向但语言附和"
    return False, ""


def metric_cross_modal(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    considered: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    for row in rows:
        has_signal = (
            row.get("cross_modal_consistency") is not None
            or _normalize_emotion(row.get("emotion_tag"))
            or _normalize_emotion(row.get("audio_tone"))
        )
        if not has_signal:
            continue
        considered.append(row)
        hit, reason = is_cross_modal_mismatch(row)
        if hit:
            mismatches.append({"transcript_id": row.get("transcript_id"), "speaker": row.get("speaker"), "reason": reason})

    if not considered:
        return {
            "value": None,
            "raw": {"mismatch_count": 0, "considered": 0, "mismatches": []},
            "formula": "无多模态字段，无法计算",
            "sample_size": 0,
            "confidence": "low",
            "higher_is_better": True,
        }

    rate = len(mismatches) / len(considered)
    return {
        "value": _round(1.0 - rate),
        "raw": {
            "mismatch_rate": _round(rate),
            "mismatch_count": len(mismatches),
            "considered": len(considered),
            "mismatches": mismatches[:8],
        },
        "formula": "1 - 跨模态错位发言数 / 可判定发言数",
        "sample_size": len(considered),
        "confidence": _confidence(len(considered), good=15, fair=6),
        "higher_is_better": True,
    }


def _cue_label(text: str) -> str:
    sentence = _safe_text(text)
    support = sum(sentence.count(cue) for cue in SUPPORT_CUES)
    dissent = sum(sentence.count(cue) for cue in DISSENT_CUES)
    if dissent and dissent >= support:
        return "dissent"
    if support:
        return "support"
    return "neutral"


def metric_consensus_dissent(utterances: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    labels = [(row, _cue_label(row.get("text", ""))) for row in utterances]
    support = [row for row, label in labels if label == "support"]
    dissent = [row for row, label in labels if label == "dissent"]
    total_marked = len(support) + len(dissent)

    if len(labels) < 3 or total_marked == 0:
        return {
            "value": None,
            "raw": {"support": len(support), "dissent": len(dissent), "utterances": len(labels)},
            "formula": "讨论轮次或立场线索不足",
            "sample_size": len(labels),
            "confidence": "low",
            "higher_is_better": True,
        }

    support_ratio = len(support) / total_marked

    # 找到"多数人已经附和"的时刻，再看之后还有没有人提出不同意见
    convergence_index = None
    support_so_far = 0
    marked_so_far = 0
    for index, (_row, label) in enumerate(labels):
        if label in {"support", "dissent"}:
            marked_so_far += 1
            support_so_far += 1 if label == "support" else 0
            if marked_so_far >= 3 and support_so_far / marked_so_far >= 0.7:
                convergence_index = index
                break

    dissent_after = []
    if convergence_index is not None:
        dissent_after = [row for row, label in labels[convergence_index + 1:] if label == "dissent"]

    suppressed = convergence_index is not None and len(dissent) > 0 and not dissent_after
    pressure = _clamp(0.6 * support_ratio + (0.4 if suppressed else 0.0))
    minority_speakers = sorted({_safe_text(row.get("speaker")) for row in dissent_after})

    return {
        "value": _round(_clamp(1.0 - pressure)),
        "raw": {
            "support": len(support),
            "dissent": len(dissent),
            "support_ratio": _round(support_ratio),
            "dissent_ratio": _round(1.0 - support_ratio),
            "convergence_index": convergence_index,
            "dissent_after_convergence": len(dissent_after),
            "minority_speakers": minority_speakers,
        },
        "formula": "1 - (0.6 * 附和占比 + 0.4 * 收敛后是否再无异议)",
        "sample_size": len(labels),
        "confidence": _confidence(len(labels), good=12, fair=6),
        "higher_is_better": True,
    }


def metric_information_gain(keywords_per_utterance: Sequence[Sequence[str]]) -> Dict[str, Any]:
    seen: set = set()
    new_tokens: List[str] = []
    total_tokens = 0
    for keywords in keywords_per_utterance:
        for token in keywords or []:
            total_tokens += 1
            if token not in seen:
                seen.add(token)
                new_tokens.append(token)
    utterances = len([item for item in keywords_per_utterance if item])
    if not utterances or total_tokens == 0:
        return {
            "value": None,
            "raw": {"new_concepts": len(new_tokens)},
            "formula": "无可用关键词",
            "sample_size": 0,
            "confidence": "low",
            "higher_is_better": True,
        }

    new_rate = len(new_tokens) / utterances
    diversity = len(seen) / total_tokens
    value = _clamp(0.7 * min(1.0, new_rate / 1.5) + 0.3 * min(1.0, diversity / 0.8))
    return {
        "value": _round(value),
        "raw": {
            "distinct_concepts": len(seen),
            "new_concept_rate_per_utterance": _round(new_rate),
            "token_diversity": _round(diversity),
            "top_concepts": [item for item, _ in Counter(new_tokens).most_common(8)],
        },
        "formula": "0.7 * min(1, 每句新增概念数/1.5) + 0.3 * min(1, 词元多样性/0.8)",
        "sample_size": utterances,
        "confidence": _confidence(utterances, good=12, fair=6),
        "higher_is_better": True,
    }


def metric_convergence_health(vote_counts: Sequence[int], turnout: float) -> Dict[str, Any]:
    counts = [int(c or 0) for c in vote_counts]
    if not counts or sum(counts) <= 0:
        return {
            "value": None,
            "raw": {"reason": "没有投票数据"},
            "formula": "缺少观点投票分布",
            "sample_size": 0,
            "confidence": "low",
            "higher_is_better": True,
        }
    entropy = normalized_entropy(counts)
    pressure = _clamp((1.0 - entropy) * _clamp(turnout))
    return {
        "value": _round(1.0 - pressure),
        "raw": {"vote_entropy": _round(entropy), "turnout": _round(turnout), "vote_counts": counts},
        "formula": "1 - (1 - 投票分布熵) * 投票参与率",
        "sample_size": sum(counts),
        "confidence": _confidence(sum(counts), good=8, fair=3),
        "higher_is_better": True,
    }


def _label_propagation(
    members: Sequence[str],
    weighted_edges: Dict[Tuple[str, str], float],
    max_iterations: int = 50,
) -> List[List[str]]:
    """确定性的加权标签传播，用于无标签小组发现（不引入额外图计算依赖）。"""
    people = list(dict.fromkeys([m for m in members if m]))
    index = {name: position for position, name in enumerate(people)}
    adjacency: Dict[int, Dict[int, float]] = defaultdict(dict)
    for (left, right), weight in weighted_edges.items():
        if left == right or left not in index or right not in index or weight <= 0:
            continue
        i, j = index[left], index[right]
        adjacency[i][j] = adjacency[i].get(j, 0.0) + float(weight)
        adjacency[j][i] = adjacency[j].get(i, 0.0) + float(weight)

    labels = {position: position for position in range(len(people))}
    order = sorted(range(len(people)))
    for _ in range(max_iterations):
        changed = False
        for position in order:
            neighbours = adjacency.get(position)
            if not neighbours:
                continue
            scores: Dict[int, float] = defaultdict(float)
            for other, weight in neighbours.items():
                scores[labels[other]] += weight
            best = max(scores.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if labels[position] != best:
                labels[position] = best
                changed = True
        if not changed:
            break

    # 先按标签归并，再把同一标签内图上断开的部分拆成独立小组
    by_label: Dict[int, List[int]] = defaultdict(list)
    for position in order:
        by_label[labels[position]].append(position)

    result: List[List[str]] = []
    for nodes in by_label.values():
        node_set = set(nodes)
        visited: set = set()
        for position in nodes:
            if position in visited:
                continue
            component: List[int] = []
            queue = [position]
            visited.add(position)
            while queue:
                current = queue.pop(0)
                component.append(current)
                for other in adjacency.get(current, {}):
                    if other in node_set and other not in visited:
                        visited.add(other)
                        queue.append(other)
            result.append([people[slot] for slot in sorted(component)])

    result.sort(key=lambda chunk: (-len(chunk), chunk[0] if chunk else ""))
    return [chunk for chunk in result if chunk]


def analyze_group_structure(
    members: Sequence[str],
    speech_counts: Dict[str, int],
    interactions: Dict[Tuple[str, str], int],
) -> Dict[str, Any]:
    """小组发现 + 角色识别：核心贡献者 / 跨组桥接人 / 被孤立者。"""
    people = list(dict.fromkeys([m for m in members if m]))
    weighted_edges: Dict[Tuple[str, str], float] = defaultdict(float)
    for (src, dst), count in interactions.items():
        if src == dst or src not in people or dst not in people:
            continue
        key = (src, dst) if src < dst else (dst, src)
        weighted_edges[key] += float(count)

    communities = _label_propagation(people, weighted_edges)
    if not communities:
        communities = [[person] for person in people]

    community_of: Dict[str, int] = {}
    for position, chunk in enumerate(communities):
        for person in chunk:
            community_of[person] = position

    degrees: Dict[str, float] = defaultdict(float)
    internal: Dict[str, float] = defaultdict(float)
    external: Dict[str, float] = defaultdict(float)
    for (left, right), weight in weighted_edges.items():
        degrees[left] += weight
        degrees[right] += weight
        if community_of.get(left) == community_of.get(right):
            internal[left] += weight
            internal[right] += weight
        else:
            external[left] += weight
            external[right] += weight

    roles: Dict[str, str] = {}
    bridges: List[Dict[str, Any]] = []
    isolates: List[str] = []
    for person in people:
        degree = degrees.get(person, 0.0)
        if degree <= 0:
            roles[person] = "isolate"
            isolates.append(person)
            continue
        external_ratio = external.get(person, 0.0) / degree
        if len(communities) > 1 and external_ratio >= 0.35 and degree >= 2:
            roles[person] = "bridge"
            bridges.append({"username": person, "external_ratio": _round(external_ratio), "degree": _round(degree, 2)})
        else:
            roles[person] = "core"

    for chunk in communities:
        if not chunk:
            continue
        speaker = max(chunk, key=lambda name: (speech_counts.get(name, 0), name))
        if roles.get(speaker) == "core" and speech_counts.get(speaker, 0) > 0:
            roles[speaker] = "top_contributor"

    cohesion_values: List[float] = []
    for chunk in communities:
        inside = sum(internal.get(person, 0.0) for person in chunk)
        outside = sum(external.get(person, 0.0) for person in chunk)
        cohesion_values.append(inside / (inside + outside) if (inside + outside) > 0 else 0.0)

    return {
        "communities": [
            {
                "group_id": position + 1,
                "members": chunk,
                "size": len(chunk),
                "cohesion": _round(cohesion_values[position]) if position < len(cohesion_values) else None,
                "speech_total": sum(speech_counts.get(person, 0) for person in chunk),
            }
            for position, chunk in enumerate(communities)
        ],
        "roles": roles,
        "bridges": bridges,
        "isolates": isolates,
        "structure_note": (
            "自动发现 %d 个协作子群" % len(communities)
            + ("，存在 %d 名跨组桥接成员" % len(bridges) if bridges else "")
            + ("，%d 名成员没有任何接话关系" % len(isolates) if isolates else "")
        ),
    }


# ---------------------------------------------------------------------------
# 数据访问层（复用项目现有 ORM 模型）
# ---------------------------------------------------------------------------

def _is_teacher(user: Any) -> bool:
    return _safe_text(getattr(user, "role", "")).lower() == "teacher"


def _fetch_meeting(db: Any, meeting_id: int) -> Any:
    dbm = _db_module()
    return db.query(dbm.Meeting).filter(dbm.Meeting.id == meeting_id).first()


def _fetch_transcript_rows(
    db: Any,
    meeting_id: int,
    usernames: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    exclude_teacher: bool = True,
) -> List[Dict[str, Any]]:
    dbm = _db_module()
    joinedload = _joinedload()
    query = (
        db.query(dbm.Transcript)
        .options(joinedload(dbm.Transcript.user))
        .filter(dbm.Transcript.meeting_id == meeting_id)
        .order_by(dbm.Transcript.timestamp.asc(), dbm.Transcript.id.asc())
    )
    if limit:
        query = query.limit(limit)

    wanted = set(usernames) if usernames else None
    rows: List[Dict[str, Any]] = []
    for item in query:
        user = getattr(item, "user", None)
        if exclude_teacher and user is not None and _is_teacher(user):
            continue
        speaker = _safe_text(getattr(user, "username", "")) or ("user#%s" % getattr(item, "user_id", "?"))
        if wanted and speaker not in wanted:
            continue
        timestamp = getattr(item, "timestamp", None)
        rows.append(
            {
                "transcript_id": getattr(item, "id", None),
                "speaker": speaker,
                "text": _safe_text(getattr(item, "content", "")),
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else None,
                "ts": timestamp,
                "relevance": getattr(item, "relevance_score", None) or 0,
                "quality": getattr(item, "quality_score", None) or 0,
                "emotion_tag": getattr(item, "emotion_tag", None),
                "body_action": getattr(item, "body_action", None),
                "audio_tone": getattr(item, "audio_tone", None),
                "cross_modal_consistency": getattr(item, "cross_modal_consistency", None),
                "binding_source": getattr(item, "binding_source", None),
                "binding_confidence": getattr(item, "binding_confidence", None),
            }
        )
    return rows


def _speaker_stats(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        speaker = row["speaker"]
        bucket = stats.setdefault(
            speaker,
            {"speech_count": 0, "quality_sum": 0.0, "relevance_sum": 0.0, "first_ts": row.get("ts"), "last_ts": row.get("ts")},
        )
        bucket["speech_count"] += 1
        bucket["quality_sum"] += float(row.get("quality") or 0)
        bucket["relevance_sum"] += float(row.get("relevance") or 0)
        if row.get("ts") is not None:
            bucket["last_ts"] = row.get("ts")
    for bucket in stats.values():
        count = max(1, bucket["speech_count"])
        bucket["avg_quality"] = _round(bucket["quality_sum"] / count, 1)
        bucket["avg_relevance"] = _round(bucket["relevance_sum"] / count, 1)
        bucket["score"] = _round((bucket["quality_sum"] * 0.6 + bucket["relevance_sum"] * 0.4) / count, 1)
        bucket.pop("quality_sum", None)
        bucket.pop("relevance_sum", None)
    return stats


def _directed_interactions(rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], int]:
    """复用 server.py 实时统计里的相邻接话口径：相邻不同说话人算一次互动。"""
    interactions: Dict[Tuple[str, str], int] = defaultdict(int)
    for index in range(1, len(rows)):
        previous = rows[index - 1]["speaker"]
        current = rows[index]["speaker"]
        if previous and current and previous != current:
            interactions[(previous, current)] += 1
    return dict(interactions)


def _extract_keywords_safe(texts: Sequence[str], limit: int = 6) -> List[str]:
    """复用研究算法模块里的关键词抽取（_extract_keywords），失败则退化为本地实现。"""
    try:
        from research_algorithm_fusion import _extract_keywords  # noqa: WPS433

        return _extract_keywords(list(texts), limit)
    except Exception:
        counter: Counter = Counter()
        for text in texts:
            for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", _safe_text(text)):
                counter[token] += 1
        return [item for item, _ in counter.most_common(limit)]


def _knowledge_points(meeting: Any) -> List[str]:
    raw = getattr(meeting, "knowledge_points", None) or []
    points: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            label = item.get("desc") or item.get("title") or item.get("name") or item.get("content") or item.get("point")
            label = _safe_text(label)
        else:
            label = _safe_text(item)
        if label:
            points.append(label)
    return points


def _online_members(db: Any, meeting_id: int) -> List[str]:
    dbm = _db_module()
    rows = (
        db.query(dbm.MemberConnection)
        .filter(dbm.MemberConnection.meeting_id == meeting_id, dbm.MemberConnection.is_online == 1)
        .all()
    )
    return [_safe_text(row.username) for row in rows if _safe_text(row.username)]


# ---------------------------------------------------------------------------
# Tool 层
# ---------------------------------------------------------------------------

_MEETING_PARAM = {
    "type": "object",
    "properties": {"meeting_id": {"type": "integer", "description": "课堂(meeting) ID"}},
    "required": ["meeting_id"],
}


@_register(
    "get_meeting_context",
    "获取课堂基础上下文：主题、生命周期状态、成员、学习目标、数据量，以及当前状态允许调用的工具。任何分析都应先调用它。",
    _MEETING_PARAM,
    (STATE_CREATED, STATE_RUNNING, STATE_ENDED),
)
def tool_get_meeting_context(ctx: ToolContext, meeting_id: int) -> Dict[str, Any]:
    db, close = _session_scope()
    try:
        meeting = _fetch_meeting(db, meeting_id)
        if meeting is None:
            return {"ok": False, "error": "课堂 %s 不存在" % meeting_id}
        state = resolve_classroom_state(meeting, db)
        rows = _fetch_transcript_rows(db, meeting_id, limit=2000)
        stats = _speaker_stats(rows)
        members = sorted(set(_online_members(db, meeting_id)) | set(stats.keys()))
        allowed = [
            spec.name
            for spec in TOOL_SPECS.values()
            if state in spec.allowed_states and ctx.mode in spec.modes
        ]
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "topic": _safe_text(meeting.topic),
            "class_code": _safe_text(meeting.class_code),
            "state": state,
            "raw_status": _safe_text(meeting.status),
            "knowledge_points": _knowledge_points(meeting),
            "has_teaching_design": bool(meeting.teaching_design),
            "member_count": len(members),
            "members": members,
            "speech_counts": {name: bucket["speech_count"] for name, bucket in stats.items()},
            "transcript_count": len(rows),
            "allowed_tools": allowed,
            "note": "课堂状态为 %s，请不要调用 allowed_tools 之外的工具。" % state,
        }
    finally:
        close()


@_register(
    "discover_groups",
    "在没有分组名单的情况下，从发言接话关系中发现协作子群，并识别核心贡献者、跨组桥接人和被孤立成员。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "min_size": {"type": "integer", "description": "小组最小人数，默认 2"},
        },
        "required": ["meeting_id"],
    },
    (STATE_RUNNING, STATE_ENDED),
)
def tool_discover_groups(ctx: ToolContext, meeting_id: int, min_size: int = 2) -> Dict[str, Any]:
    db, close = _session_scope()
    try:
        rows = _fetch_transcript_rows(db, meeting_id)
        if not rows:
            return {"ok": False, "error": "该课堂还没有发言记录，无法发现小组结构"}
        stats = _speaker_stats(rows)
        interactions = _directed_interactions(rows)
        structure = analyze_group_structure(
            list(stats.keys()),
            {name: bucket["speech_count"] for name, bucket in stats.items()},
            interactions,
        )
        threshold = int(min_size or 2)
        big_groups = [chunk for chunk in structure["communities"] if chunk["size"] >= threshold]
        if big_groups:
            structure["communities"] = big_groups
        structure["transcript_count"] = len(rows)
        structure["evidence_id"] = ctx.ledger.add(
            "group_structure",
            structure["structure_note"],
            detail={
                "communities": structure["communities"],
                "bridges": structure["bridges"],
                "isolates": structure["isolates"],
            },
            confidence=0.7,
        )
        return {"ok": True, **structure}
    finally:
        close()


@_register(
    "get_group_evidence",
    "按关注点抽取原始发言证据（含质量分、情绪、语调、跨模态一致性），每条证据都带 T# 编号供最终结论引用。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "usernames": {"type": "array", "items": {"type": "string"}, "description": "只取这些成员的发言，留空表示全体"},
            "focus": {"type": "string", "enum": ["all", "dissent", "low_quality", "mismatch"], "description": "关注点，默认 all"},
            "limit": {"type": "integer", "description": "最多返回多少条，默认 20"},
        },
        "required": ["meeting_id"],
    },
    (STATE_RUNNING, STATE_ENDED),
)
def tool_get_group_evidence(
    ctx: ToolContext,
    meeting_id: int,
    usernames: Optional[List[str]] = None,
    focus: str = "all",
    limit: int = 20,
) -> Dict[str, Any]:
    db, close = _session_scope()
    try:
        rows = _fetch_transcript_rows(db, meeting_id, usernames=usernames)
        if not rows:
            return {"ok": False, "error": "没有符合条件的发言"}

        focus = _safe_text(focus) or "all"
        if focus == "dissent":
            selected = [row for row in rows if _cue_label(row.get("text", "")) == "dissent"]
        elif focus == "low_quality":
            selected = [row for row in rows if float(row.get("quality") or 0) < 60]
        elif focus == "mismatch":
            selected = [row for row in rows if is_cross_modal_mismatch(row)[0]]
        else:
            selected = []
        if not selected:
            selected = rows

        evidence_items = []
        for row in selected[-max(1, int(limit or 20)):]:
            eid = ctx.ledger.add(
                "transcript",
                "%s: %s" % (row["speaker"], row["text"][:80]),
                detail={
                    "quality": row.get("quality"),
                    "relevance": row.get("relevance"),
                    "emotion": row.get("emotion_tag"),
                    "audio_tone": row.get("audio_tone"),
                    "cross_modal_consistency": row.get("cross_modal_consistency"),
                },
                ref="T#%s" % row.get("transcript_id"),
                confidence=_round(row.get("binding_confidence")) if row.get("binding_confidence") is not None else None,
            )
            evidence_items.append(
                {
                    "evidence_id": eid,
                    "transcript_id": row.get("transcript_id"),
                    "speaker": row["speaker"],
                    "timestamp": row.get("timestamp"),
                    "text": row["text"][:300],
                    "quality": row.get("quality"),
                    "relevance": row.get("relevance"),
                    "emotion": row.get("emotion_tag"),
                    "audio_tone": row.get("audio_tone"),
                    "body_action": row.get("body_action"),
                    "cross_modal_consistency": row.get("cross_modal_consistency"),
                }
            )
        return {
            "ok": True,
            "focus": focus,
            "total_scanned": len(rows),
            "returned": len(evidence_items),
            "evidence": evidence_items,
        }
    finally:
        close()


@_register(
    "compute_group_metrics",
    "计算六个 GCA 小组协作指标（参与均衡度、互动结构、信息增量、收敛健康度、跨模态一致性、共识-分歧结构），返回数值、计算口径与样本量。所有数字必须来自本工具。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "usernames": {"type": "array", "items": {"type": "string"}, "description": "只统计这些成员，留空表示全体"},
        },
        "required": ["meeting_id"],
    },
    (STATE_RUNNING, STATE_ENDED),
    latency="medium",
)
def tool_compute_group_metrics(ctx: ToolContext, meeting_id: int, usernames: Optional[List[str]] = None) -> Dict[str, Any]:
    db, close = _session_scope()
    try:
        dbm = _db_module()
        rows = _fetch_transcript_rows(db, meeting_id, usernames=usernames)
        if not rows:
            return {"ok": False, "error": "没有发言记录，无法计算指标"}

        stats = _speaker_stats(rows)
        interactions = _directed_interactions(rows)
        metrics: Dict[str, Any] = {
            "participation_balance": metric_participation_balance([bucket["speech_count"] for bucket in stats.values()]),
            "interaction_structure": metric_interaction_structure(list(stats.keys()), interactions),
            "cross_modal_consistency": metric_cross_modal(rows),
            "consensus_dissent": metric_consensus_dissent(rows),
            "information_gain": metric_information_gain(
                [_extract_keywords_safe([row["text"]], limit=4) for row in rows]
            ),
        }

        vote = (
            db.query(dbm.ViewpointVote)
            .filter(dbm.ViewpointVote.meeting_id == meeting_id)
            .order_by(dbm.ViewpointVote.id.desc())
            .first()
        )
        if vote is not None and isinstance(vote.votes, dict) and vote.votes:
            counts = [len(value or []) for value in vote.votes.values()]
            turnout = sum(counts) / max(1, len(stats))
            metrics["convergence_health"] = metric_convergence_health(counts, turnout)
        else:
            text_only = metrics["consensus_dissent"]
            metrics["convergence_health"] = {
                "value": text_only.get("value"),
                "raw": {"note": "没有观点投票数据，用语言收敛线索近似", **(text_only.get("raw") or {})},
                "formula": "无投票数据时退化为 1 - (0.6 * 附和占比 + 0.4 * 收敛后是否再无异议)",
                "sample_size": text_only.get("sample_size", 0),
                "confidence": "low",
                "higher_is_better": True,
            }

        available = {key: item for key, item in metrics.items() if item.get("value") is not None}
        total_weight = sum(GCA_WEIGHTS.get(key, 0.1) for key in available)
        gca_score = None
        if available and total_weight > 0:
            gca_score = _round(
                sum(item["value"] * GCA_WEIGHTS.get(key, 0.1) for key, item in available.items()) / total_weight
            )

        for key, item in metrics.items():
            item["evidence_id"] = ctx.ledger.add(
                "metric",
                "%s = %s" % (key, item.get("value")),
                detail={"raw": item.get("raw"), "formula": item.get("formula")},
                confidence={"high": 0.9, "medium": 0.7, "low": 0.4}.get(item.get("confidence"), 0.5),
            )

        return {
            "ok": True,
            "gca_score": gca_score,
            "metrics": metrics,
            "speaker_stats": {
                name: {
                    "speech_count": bucket["speech_count"],
                    "avg_quality": bucket["avg_quality"],
                    "avg_relevance": bucket["avg_relevance"],
                    "score": bucket["score"],
                }
                for name, bucket in stats.items()
            },
            "missing_metrics": [key for key, item in metrics.items() if item.get("value") is None],
            "note": "gca_score 为各可用指标的加权平均，缺失指标已自动重新归一化权重。",
        }
    finally:
        close()


@_register(
    "get_knowledge_trace",
    "获取知识图谱轨迹：预设学习目标的覆盖情况、讨论中出现的高频概念、尚未触及的知识点。",
    _MEETING_PARAM,
    (STATE_RUNNING, STATE_ENDED),
    modes=(MODE_ON_DEMAND, MODE_AFTER_CLASS),
    latency="medium",
)
def tool_get_knowledge_trace(ctx: ToolContext, meeting_id: int) -> Dict[str, Any]:
    db, close = _session_scope()
    try:
        dbm = _db_module()
        meeting = _fetch_meeting(db, meeting_id)
        if meeting is None:
            return {"ok": False, "error": "课堂 %s 不存在" % meeting_id}

        graph = (
            db.query(dbm.KnowledgeGraph)
            .filter(dbm.KnowledgeGraph.meeting_id == meeting_id)
            .order_by(dbm.KnowledgeGraph.id.desc())
            .first()
        )
        if graph is None:
            # 复用 server.py 里现成的图谱构建函数（延迟导入，避免循环依赖）
            try:
                import server  # noqa: WPS433

                server.update_knowledge_graph(meeting_id, db)
                graph = (
                    db.query(dbm.KnowledgeGraph)
                    .filter(dbm.KnowledgeGraph.meeting_id == meeting_id)
                    .order_by(dbm.KnowledgeGraph.id.desc())
                    .first()
                )
            except Exception as exc:  # pragma: no cover - 依赖运行环境
                ctx.notes.append("知识图谱构建失败：%s" % exc)

        concepts: List[Dict[str, Any]] = []
        if graph is not None:
            nodes = (
                db.query(dbm.GraphNode)
                .filter(dbm.GraphNode.graph_id == graph.id)
                .order_by(dbm.GraphNode.frequency.desc())
                .limit(20)
                .all()
            )
            concepts = [
                {
                    "concept": _safe_text(node.concept_label),
                    "type": _safe_text(node.concept_type),
                    "frequency": int(node.frequency or 0),
                }
                for node in nodes
            ]

        points = _knowledge_points(meeting)
        rows = _fetch_transcript_rows(db, meeting_id, limit=3000)
        keywords = _extract_keywords_safe([row["text"] for row in rows], limit=40)
        joined = " ".join(row["text"] for row in rows)
        covered = [
            point
            for point in points
            if point and (point in joined or any(token in point for token in keywords))
        ]
        uncovered = [point for point in points if point not in covered]

        ctx.ledger.add(
            "knowledge_graph",
            "知识图谱概念 %d 个，预设目标覆盖 %d/%d" % (len(concepts), len(covered), len(points)),
            detail={"top_concepts": concepts[:8], "uncovered": uncovered},
            confidence=0.75,
        )
        return {
            "ok": True,
            "has_graph": graph is not None,
            "top_concepts": concepts,
            "knowledge_points": points,
            "covered_points": covered,
            "uncovered_points": uncovered,
            "coverage_ratio": _round(len(covered) / len(points)) if points else None,
            "keyword_cloud": keywords[:15],
        }
    finally:
        close()


@_register(
    "find_learning_gaps",
    "找出参与盲区：在线但很少发言的成员、跨模态表现错位的成员、持续负向情绪的成员（心理健康评估只返回聚合提示，不返回原始数据）。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "quiet_threshold": {"type": "integer", "description": "发言次数不超过多少算沉默，默认 2"},
        },
        "required": ["meeting_id"],
    },
    (STATE_RUNNING, STATE_ENDED),
)
def tool_find_learning_gaps(ctx: ToolContext, meeting_id: int, quiet_threshold: int = 2) -> Dict[str, Any]:
    db, close = _session_scope()
    try:
        dbm = _db_module()
        joinedload = _joinedload()
        rows = _fetch_transcript_rows(db, meeting_id)
        stats = _speaker_stats(rows)
        online = set(_online_members(db, meeting_id))

        threshold = int(quiet_threshold if quiet_threshold is not None else 2)
        silent_present = sorted(
            name for name in online if stats.get(name, {}).get("speech_count", 0) <= threshold
        )

        mismatch_counter: Counter = Counter()
        for row in rows:
            hit, _reason = is_cross_modal_mismatch(row)
            if hit:
                mismatch_counter[row["speaker"]] += 1

        emotion_counter: Counter = Counter()
        emotions = (
            db.query(dbm.EmotionLog)
            .options(joinedload(dbm.EmotionLog.user))
            .filter(dbm.EmotionLog.meeting_id == meeting_id)
            .all()
        )
        for item in emotions:
            label = _normalize_emotion(getattr(item, "emotion_type", ""))
            if label in NEGATIVE_EMOTIONS and float(getattr(item, "intensity", 0) or 0) >= 0.6:
                user = getattr(item, "user", None)
                if user is not None and not _is_teacher(user):
                    emotion_counter[_safe_text(getattr(user, "username", ""))] += 1

        risk_note = ""
        try:
            assessments = (
                db.query(dbm.MentalHealthAssessment)
                .filter(dbm.MentalHealthAssessment.meeting_id == meeting_id)
                .all()
            )
            high_risk = [
                item for item in assessments if _safe_text(getattr(item, "risk_level", "")).lower() == "high"
            ]
            if high_risk:
                # 隐私保护：只给数量与提示，不给原始评估内容
                risk_note = (
                    "存在 %d 条高风险心理健康评估记录，请通过线下渠道单独关心，不要在此处展开细节。" % len(high_risk)
                )
        except Exception as exc:  # pragma: no cover
            ctx.notes.append("心理健康评估读取失败：%s" % exc)

        ctx.ledger.add(
            "gap",
            "沉默成员 %d 人，跨模态错位 %d 人次，持续负向情绪 %d 人"
            % (len(silent_present), sum(mismatch_counter.values()), len(emotion_counter)),
            detail={
                "silent_present": silent_present,
                "mismatch": dict(mismatch_counter),
                "negative_emotion": dict(emotion_counter),
            },
            confidence=0.7,
        )
        return {
            "ok": True,
            "silent_present": silent_present,
            "mismatch_members": dict(mismatch_counter),
            "negative_emotion_members": dict(emotion_counter),
            "privacy_note": risk_note,
            "note": "silent_present 指在线但发言次数不超过 %d 的成员。" % threshold,
        }
    finally:
        close()


@_register(
    "simulate_intervention",
    "基于同一教师历史课堂的经验分布，估计某类干预的预期影响区间。明确标注为相关性估计而非因果推断。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "target_metric": {"type": "string", "description": "希望改善的指标名，例如 participation_balance"},
            "target_usernames": {"type": "array", "items": {"type": "string"}, "description": "干预对象"},
        },
        "required": ["meeting_id"],
    },
    (STATE_RUNNING, STATE_ENDED),
    modes=(MODE_ON_DEMAND, MODE_AFTER_CLASS),
    latency="slow",
)
def tool_simulate_intervention(
    ctx: ToolContext,
    meeting_id: int,
    target_metric: str = "participation_balance",
    target_usernames: Optional[List[str]] = None,
) -> Dict[str, Any]:
    db, close = _session_scope()
    try:
        dbm = _db_module()
        meeting = _fetch_meeting(db, meeting_id)
        if meeting is None:
            return {"ok": False, "error": "课堂 %s 不存在" % meeting_id}

        # 用同教师的历史课堂估计"沉默成员在下一个时间窗是否开口"的经验概率
        history = (
            db.query(dbm.Meeting)
            .filter(dbm.Meeting.teacher_id == meeting.teacher_id, dbm.Meeting.id != meeting_id)
            .order_by(dbm.Meeting.id.desc())
            .limit(8)
            .all()
        )

        window = timedelta(minutes=5)
        observed = 0
        spoke_later = 0
        for historical in history:
            rows = _fetch_transcript_rows(db, historical.id)
            timestamps = [row["ts"] for row in rows if row.get("ts") is not None]
            if len(rows) < 4 or not timestamps:
                continue
            start, end = min(timestamps), max(timestamps)
            if end - start < window * 2:
                continue
            speakers = {row["speaker"] for row in rows}
            cursor = start
            while cursor + window * 2 <= end:
                first_window = {
                    row["speaker"]
                    for row in rows
                    if row.get("ts") is not None and cursor <= row["ts"] < cursor + window
                }
                second_window = {
                    row["speaker"]
                    for row in rows
                    if row.get("ts") is not None and cursor + window <= row["ts"] < cursor + window * 2
                }
                for speaker in speakers - first_window:
                    observed += 1
                    if speaker in second_window:
                        spoke_later += 1
                cursor += window

        baseline = spoke_later / observed if observed else None

        rows = _fetch_transcript_rows(db, meeting_id)
        stats = _speaker_stats(rows)
        targets = [name for name in (target_usernames or []) if name]
        if not targets:
            targets = sorted(name for name, bucket in stats.items() if bucket["speech_count"] <= 2)[:5]

        expected = None
        if baseline is not None:
            expected = {"low": _round(max(0.0, baseline * 0.9)), "high": _round(min(1.0, baseline * 1.6))}

        ctx.ledger.add(
            "simulation",
            "历史课堂沉默窗口样本 %d 个，后续开口基线 %s" % (observed, _round(baseline)),
            detail={"targets": targets, "expected": expected, "history_meetings": len(history)},
            confidence=0.5 if observed >= 30 else 0.3,
        )
        return {
            "ok": True,
            "target_metric": _safe_text(target_metric) or "participation_balance",
            "targets": targets,
            "baseline_speak_next_window": _round(baseline),
            "expected_improvement_range": expected,
            "sample_size": observed,
            "history_meetings_used": len(history),
            "disclaimer": "该区间来自同教师历史课堂的相关性分布，不是因果推断；样本量为 %d。" % observed,
        }
    finally:
        close()


@_register(
    "dispatch_intervention",
    "把干预动作真正下发给学生（写操作，必须由教师确认）。action 可选 prompt_member（点名引导）、topic_hint（全班话题提示）。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "action": {"type": "string", "enum": ["prompt_member", "topic_hint"]},
            "target_usernames": {"type": "array", "items": {"type": "string"}, "description": "prompt_member 的接收人"},
            "content": {"type": "string", "description": "要下发的话术"},
            "approved": {"type": "boolean", "description": "教师是否已经确认，只有 true 才会真正执行"},
        },
        "required": ["meeting_id", "action"],
    },
    (STATE_RUNNING,),
    policy=POLICY_WRITE,
    modes=(MODE_ON_DEMAND,),
    requires_approval=True,
)
async def tool_dispatch_intervention(
    ctx: ToolContext,
    meeting_id: int,
    action: str,
    target_usernames: Optional[List[str]] = None,
    content: str = "",
    approved: bool = False,
) -> Dict[str, Any]:
    if not approved and not ctx.approved:
        return {
            "ok": False,
            "requires_approval": True,
            "message": "写操作需要教师确认后才会下发。请把动作卡交给教师，由教师在界面上点确认。",
        }
    try:
        import server  # noqa: WPS433  复用现有 WebSocket 连接管理器

        manager = server.manager
    except Exception as exc:
        return {"ok": False, "error": "无法获取课堂连接管理器：%s" % exc}

    payload = {
        "type": "agent_intervention",
        "source": "group_analysis_agent",
        "action": action,
        "content": _safe_text(content),
        "evidence": ctx.ledger.refs()[-6:],
        "ts": datetime.now().isoformat(timespec="seconds"),
    }

    sent: List[str] = []
    if action == "prompt_member":
        for username in (target_usernames or []):
            try:
                await manager.send_to_user(meeting_id, username, payload)
                sent.append(username)
            except Exception as exc:  # pragma: no cover
                ctx.notes.append("推送给 %s 失败：%s" % (username, exc))
    elif action == "topic_hint":
        try:
            await manager.broadcast_to_meeting(meeting_id, payload)
            sent.append("(all)")
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "error": "广播失败：%s" % exc}
    else:
        return {"ok": False, "error": "不支持的 action：%s" % action}

    ctx.ledger.add(
        "action",
        "已下发干预：%s -> %s" % (action, ", ".join(sent) or "无对象"),
        detail=payload,
        confidence=0.9,
    )
    return {
        "ok": True,
        "action": action,
        "delivered_to": sent,
        "note": "消息类型为 agent_intervention，前端渲染分支尚未接入（当前前端只处理 new_speech 等既有类型），演示时可先只展示动作卡。",
    }


# ---------------------------------------------------------------------------
# 迷你 Harness（OpenAI 兼容 function calling；以后可替换为 agents.Runner）
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = """你是「课堂小组分析智能体」，负责基于真实课堂数据评估一个班级的协作讨论质量。

分析维度：
1. 参与是否均衡（谁在主导、谁被边缘化）
2. 互动是否充分（是否有真实的互相接话，还是各说各话）
3. 是否产生了有效的新信息（而不是重复表态）
4. 讨论结构是否合理（是否存在孤立成员、是否需要桥接）
5. 是否出现过早收敛、少数意见被压制
6. 是否需要教师干预，用什么方式干预

硬性规则：
- 所有数字必须来自工具返回结果，禁止自行估算、外推或编造数据。
- 每条结论后面必须标注证据编号，例如 [E3] 或 [T#1834]；没有证据的判断必须写成"推测"。
- 工具返回 ok=false 或状态不允许时，说明原因并给出替代方案，不要伪造数据填补。
- 数据不足以支撑结论时，明确写"数据不足"，并指出还需要什么数据。
- 涉及具体学生的负面判断必须谨慎，用"需要关注"而不是定性描述。

最终输出必须是 JSON（不要包 markdown 代码块），结构：
{
  "summary": "一句话结论",
  "structure": {"groups": [], "bridges": [], "isolates": []},
  "metrics_reading": [{"metric": "指标名", "value": 0.0, "reading": "解读", "evidence": ["E1"]}],
  "findings": [{"finding": "发现", "evidence": ["E2", "T#100"], "confidence": "high|medium|low"}],
  "interventions": [{"target": "对象或全班", "action": "动作", "script": "话术草稿", "expected": "预期影响", "risk": "风险", "evidence": ["E3"]}],
  "data_gaps": ["还缺什么数据"],
  "unsupported_claims": []
}
"""


@dataclass
class RunTrace:
    run_id: str
    mode: str
    meeting_id: int
    started_at: str
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, kind: str, name: str, **extra: Any) -> None:
        step = {
            "index": len(self.steps) + 1,
            "kind": kind,
            "name": name,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        step.update(extra)
        self.steps.append(step)

    def save(self) -> Optional[str]:
        try:
            TRACE_DIR.mkdir(parents=True, exist_ok=True)
            path = TRACE_DIR / ("run_%s.json" % self.run_id)
            path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
            return str(path)
        except Exception:
            return None


class MiniHarness:
    """极简 Agent Loop：LLM 决定调用哪个工具 -> Policy 门禁 -> 执行 -> 回灌结果。"""

    def __init__(self, mode: str = MODE_ON_DEMAND) -> None:
        self.mode = mode if mode in MODE_BUDGETS else MODE_ON_DEMAND
        self.budget = MODE_BUDGETS[self.mode]
        self.ledger = EvidenceLedger()
        self.ctx = ToolContext(ledger=self.ledger, mode=self.mode)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI  # noqa: WPS433

            config = settings.llm
            if not config.api_key:
                raise RuntimeError("缺少 LLM_API_KEY，请在 .env 中配置")
            self._client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout_seconds,
            )
        return self._client

    async def _chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> Any:
        client = self._get_client()
        kwargs: Dict[str, Any] = {
            "model": settings.llm.model,
            "messages": messages,
            "temperature": self.budget["temperature"],
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message

    async def _execute(self, name: str, arguments: Dict[str, Any], trace: RunTrace) -> Dict[str, Any]:
        spec = TOOL_SPECS.get(name)
        if spec is None:
            return {"ok": False, "error": "未知工具 %s" % name}

        if name == "dispatch_intervention":
            arguments = {**arguments, "approved": bool(arguments.get("approved") or self.ctx.approved)}

        started = time.time()
        db, close = _session_scope()
        try:
            gate = check_tool_allowed(
                spec,
                int(arguments.get("meeting_id") or 0),
                db,
                self.mode,
                bool(arguments.get("approved")),
            )
        finally:
            close()

        if not gate.get("allowed"):
            trace.add("policy", name, allowed=False, reason=gate.get("reason"))
            return {"ok": False, "policy": gate, **gate}

        properties = (spec.parameters.get("properties") or {})
        call_kwargs = {key: value for key, value in arguments.items() if key == "meeting_id" or key in properties}
        try:
            result = spec.handler(self.ctx, **call_kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            trace.add("tool", name, allowed=True, duration_ms=int((time.time() - started) * 1000), error=str(exc))
            return {"ok": False, "error": "工具 %s 执行失败：%s" % (name, exc)}

        trace.add(
            "tool",
            name,
            allowed=True,
            state=gate.get("state"),
            arguments=call_kwargs,
            duration_ms=int((time.time() - started) * 1000),
            result_keys=list(result.keys()) if isinstance(result, dict) else str(type(result)),
        )
        return result

    async def run(self, meeting_id: int, question: str) -> Dict[str, Any]:
        trace = RunTrace(
            run_id=uuid.uuid4().hex[:12],
            mode=self.mode,
            meeting_id=meeting_id,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        tools = _tool_schemas(self.mode)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    "课堂 meeting_id = %d。教师的问题是：%s\n"
                    "请先调用工具获取真实数据，再给出结论。当前模式=%s（%s）。"
                    % (meeting_id, _safe_text(question) or "分析这个班的讨论情况", self.mode, self.budget["note"])
                ),
            },
        ]

        final_text: Optional[str] = None
        started = time.time()
        for turn in range(int(self.budget["max_turns"])):
            message = await self._chat(messages, tools)
            tool_calls = getattr(message, "tool_calls", None)
            assistant_message: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            if tool_calls:
                assistant_message["tool_calls"] = [call.model_dump() for call in tool_calls]
            messages.append(assistant_message)
            trace.add(
                "model",
                settings.llm.model,
                turn=turn + 1,
                tool_calls=[call.function.name for call in tool_calls] if tool_calls else [],
            )

            if not tool_calls:
                final_text = message.content or ""
                break

            for call in tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                arguments.setdefault("meeting_id", meeting_id)
                result = await self._execute(call.function.name, arguments, trace)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False)[:6000],
                    }
                )
            messages.append(
                {
                    "role": "system",
                    "content": "当前证据索引：\n" + self.ledger.prompt_block(int(self.budget["max_evidence"])),
                }
            )

        if final_text is None:
            final_text = "已达到最大轮次仍未得到最终结论，请缩小问题范围后重试。"

        self_check = None
        if self.budget["self_check"] and self.ledger.items():
            self_check = await self._verify(final_text)

        trace.add("final", "answer", duration_ms=int((time.time() - started) * 1000), self_check=bool(self_check))
        return {
            "run_id": trace.run_id,
            "mode": self.mode,
            "meeting_id": meeting_id,
            "answer": self._parse_json(final_text),
            "raw_answer": final_text,
            "self_check": self_check,
            "evidence_ledger": self.ledger.table(),
            "evidence_count": len(self.ledger.items()),
            "trace_path": trace.save(),
            "notes": self.ctx.notes,
        }

    @staticmethod
    def _parse_json(text: str) -> Any:
        cleaned = _safe_text(text)
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
            cleaned = re.sub(r"```\s*$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return {"raw": text}
            return {"raw": text}

    async def _verify(self, answer: str) -> Dict[str, Any]:
        """自检：把结论逐条回查证据，证据不足的直接标出来。"""
        prompt = (
            "下面是一份课堂分析结论和本次运行用到的证据清单。请检查每条结论是否有证据支持。\n"
            "只输出 JSON：{\"verdict\": \"pass|partial|fail\", \"unsupported\": [{\"claim\": \"...\", \"reason\": \"...\"}]}\n\n"
            "结论：\n%s\n\n证据清单：\n%s\n" % (answer[:4000], self.ledger.prompt_block(limit=40))
        )
        try:
            message = await self._chat([{"role": "user", "content": prompt}], None)
            return self._parse_json(message.content or "")
        except Exception as exc:
            return {"verdict": "unknown", "error": str(exc)}


# ---------------------------------------------------------------------------
# FastAPI 路由（需要时在 server.py 里 include_router 即可）
# ---------------------------------------------------------------------------

try:  # pragma: no cover - 仅在 FastAPI 环境生效
    from fastapi import APIRouter
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/agents", tags=["agents"])

    class GroupAnalysisRequest(BaseModel):
        meeting_id: int
        question: str = ""
        mode: str = MODE_ON_DEMAND
        approve_write: bool = False

    @router.get("/group-analysis/tools")
    async def list_tools() -> Dict[str, Any]:
        return {
            "agent": AGENT_NAME,
            "modes": MODE_BUDGETS,
            "tools": [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "policy": spec.policy,
                    "allowed_states": list(spec.allowed_states),
                    "modes": list(spec.modes),
                    "requires_approval": spec.requires_approval,
                }
                for spec in TOOL_SPECS.values()
            ],
        }

    @router.post("/group-analysis")
    async def run_group_analysis(request: GroupAnalysisRequest) -> Dict[str, Any]:
        harness = MiniHarness(mode=request.mode)
        harness.ctx.approved = bool(request.approve_write)
        return await harness.run(request.meeting_id, request.question)

except Exception:  # pragma: no cover
    router = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_tools() -> None:
    print("Agent: %s\n" % AGENT_NAME)
    print("%-26s %-10s %-28s %s" % ("tool", "policy", "allowed_states", "modes"))
    print("-" * 100)
    for spec in TOOL_SPECS.values():
        print("%-26s %-10s %-28s %s" % (spec.name, spec.policy, "/".join(spec.allowed_states), ",".join(spec.modes)))
    print("\n模式预算：")
    for mode, budget in MODE_BUDGETS.items():
        print(
            "  %-12s max_turns=%s max_evidence=%s self_check=%s"
            % (mode, budget["max_turns"], budget["max_evidence"], budget["self_check"])
        )


def _run_selftest() -> int:
    failures: List[str] = []
    total = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal total
        total += 1
        if condition:
            print("PASS  %s" % name)
        else:
            print("FAIL  %s %s" % (name, detail))
            failures.append(name)

    check("归一化熵：完全均衡 = 1", abs(normalized_entropy([2, 2, 2, 2]) - 1.0) < 1e-6)
    check("归一化熵：一人独占 = 0", normalized_entropy([9, 0, 0, 0]) < 1e-6)
    check("基尼系数：完全均衡约等于 0", gini([3, 3, 3, 3]) < 1e-6)

    balanced = metric_participation_balance([5, 5, 5, 5])["value"]
    skewed = metric_participation_balance([15, 1, 1, 1])["value"]
    check("参与均衡度：均衡 > 失衡", balanced > skewed, "%s vs %s" % (balanced, skewed))

    members = ["甲", "乙", "丙", "丁", "戊"]
    communities = _label_propagation(members, {("甲", "乙"): 7.0, ("丙", "丁"): 7.0})
    chunks = {frozenset(chunk) for chunk in communities}
    check(
        "标签传播：切出两个协作小组",
        frozenset({"甲", "乙"}) in chunks and frozenset({"丙", "丁"}) in chunks,
        str(communities),
    )

    structure = analyze_group_structure(
        members,
        {"甲": 8, "乙": 6, "丙": 7, "丁": 5, "戊": 0},
        {("甲", "乙"): 4, ("乙", "甲"): 3, ("丙", "丁"): 5, ("丁", "丙"): 2, ("乙", "丙"): 5},
    )
    check("角色识别：识别孤立成员", "戊" in structure["isolates"], str(structure["roles"]))
    check(
        "角色识别：识别跨组桥接人",
        any(item["username"] == "乙" for item in structure["bridges"]),
        str(structure["bridges"]),
    )

    rows = [
        {
            "transcript_id": 1,
            "speaker": "甲",
            "text": "我觉得这个方案可行",
            "emotion_tag": "confused",
            "audio_tone": "happy",
            "cross_modal_consistency": None,
        },
        {
            "transcript_id": 2,
            "speaker": "乙",
            "text": "数据支持这个结论",
            "emotion_tag": "happy",
            "audio_tone": "happy",
            "cross_modal_consistency": 0.9,
        },
    ]
    cross = metric_cross_modal(rows)
    check("跨模态：检出表情-语调错位", cross["raw"]["mismatch_count"] == 1, str(cross["raw"]))

    utterances = [
        {"speaker": "甲", "text": "我同意这个思路"},
        {"speaker": "乙", "text": "没错，我也觉得"},
        {"speaker": "丙", "text": "有道理，支持"},
        {"speaker": "丁", "text": "但是这里有个反例"},
    ]
    consensus = metric_consensus_dissent(utterances)
    check(
        "共识分歧：识别收敛后的异议",
        consensus["raw"]["dissent_after_convergence"] >= 1,
        str(consensus["raw"]),
    )

    info = metric_information_gain([["模型"], ["模型", "数据集"], ["数据集", "评估"]])
    check("信息增量：正增益", info["value"] is not None and info["value"] > 0, str(info["value"]))

    convergence = metric_convergence_health([9, 1, 0], turnout=0.9)
    check("收敛健康度：低熵时压力上升", convergence["value"] < 0.5, str(convergence["value"]))

    for name, spec in TOOL_SPECS.items():
        params = spec.parameters
        ok = params.get("type") == "object" and "meeting_id" in (params.get("properties") or {})
        check("工具契约：%s" % name, ok, str(params)[:80])

    print("\n共 %d 项检查，%d 项失败" % (total, len(failures)))
    return 1 if failures else 0


def _run_env_check() -> int:
    problems = 0

    def line(label: str, ok: bool, detail: str = "") -> None:
        nonlocal problems
        print("%-22s %s %s" % (label, "OK" if ok else "FAIL", detail))
        if not ok:
            problems += 1

    config = settings.llm
    line("LLM_API_KEY", bool(config.api_key), "provider=%s model=%s" % (config.provider, config.model))
    line("LLM base_url", bool(config.base_url), config.base_url)

    try:
        dbm = _db_module()
        db = dbm.SessionLocal()
        line("database", True, "meetings=%d" % db.query(dbm.Meeting).count())
        db.close()
    except Exception as exc:
        line("database", False, str(exc)[:120])

    try:
        from research_algorithm_fusion import _extract_keywords  # noqa: WPS433, F401

        line("research algorithms", True, "research_algorithm_fusion 可用")
    except Exception as exc:
        line("research algorithms", False, str(exc)[:120])

    return 1 if problems else 0


async def _run_agent(meeting_id: int, question: str, mode: str) -> int:
    harness = MiniHarness(mode=mode)
    result = await harness.run(meeting_id, question)
    print("run_id=%s mode=%s 证据数=%d" % (result["run_id"], result["mode"], result["evidence_count"]))
    print("trace=%s" % result["trace_path"])
    print("-" * 60)
    answer = result["answer"]
    print(json.dumps(answer, ensure_ascii=False, indent=2) if isinstance(answer, (dict, list)) else answer)
    if result.get("self_check"):
        print("-" * 60)
        print("自检：%s" % json.dumps(result["self_check"], ensure_ascii=False)[:1200])
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="课堂小组分析智能体（单文件版）")
    parser.add_argument("--tools", action="store_true", help="列出工具与策略表")
    parser.add_argument("--selftest", action="store_true", help="运行纯算法自检（离线）")
    parser.add_argument("--check", action="store_true", help="环境体检（配置/数据库/算法）")
    parser.add_argument("--meeting-id", type=int, default=0, help="要分析的课堂 ID")
    parser.add_argument("--question", type=str, default="", help="教师的问题")
    parser.add_argument("--mode", type=str, default=MODE_ON_DEMAND, choices=list(MODE_BUDGETS.keys()))
    args = parser.parse_args(argv)

    if args.tools:
        _print_tools()
        return 0
    if args.selftest:
        return _run_selftest()
    if args.check:
        return _run_env_check()
    if not args.meeting_id:
        parser.print_help()
        return 1
    return asyncio.run(_run_agent(args.meeting_id, args.question, args.mode))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
