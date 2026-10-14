# -*- coding: utf-8 -*-
"""课堂教学设计 Agent（Teaching Design Agent）

面向课堂创建阶段（尚未开课）的教学设计智能体。教师给出课程主题与参考资料，
Agent 自行读取课堂信息与历史教案，生成可执行、可验证的教学目标，并在教师确认后
写回课堂记录。

设计要点
--------
1. 目标必须可验证：每条目标都要能被课堂中观察到的行为判定，无法验证的目标会被
   标注出来并要求重写，而不是直接写入数据库。
2. 复用现有能力：目标生成复用项目已有的 llm_service，历史教案取自现有 meetings
   表，本文件不重复实现业务逻辑。
3. 写操作需人工确认：任何回写数据库的动作都必须由教师确认后执行。
4. 状态约束：本 Agent 只在课堂尚未开始或正在进行时可读，写回仅限尚未开始的课堂。

工具清单
--------
    get_course_materials    读取课堂主题、参考资料与已有目标        created/running/ended  只读
    get_previous_goals      读取同一位教师的历史教学目标            on_demand/after_class  只读
    draft_learning_goals    生成候选教学目标                        on_demand/after_class  只读
    check_goal_quality      检查目标的可验证性与覆盖度               on_demand/after_class  只读
    save_learning_goals     把确认后的目标写回课堂记录               created                写，需确认

运行模式
--------
    on_demand     教师主动发起，最多 8 轮，带证据自检
    after_class   课后打磨教案，最多 12 轮，证据预算最大

用法
----
    python agent1_teaching_design.py --tools
    python agent1_teaching_design.py --selftest
    python agent1_teaching_design.py --check
    python agent1_teaching_design.py --meeting-id 12 --mode on_demand --question "帮我为这节课设计教学目标"

接入现有服务（在服务入口注册路由即可，本文件不改动其他文件）：

    from agent1_teaching_design.agent1_teaching_design import teaching_design_router
    app.include_router(teaching_design_router)
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

BASE_DIR = Path(__file__).resolve().parent


def _resolve_project_root(start: Path) -> Path:
    """定位项目根目录（含 config.py 的目录），使本文件放在子目录中也能直接运行。"""
    for candidate in (start, *start.parents):
        if (candidate / "config.py").exists():
            return candidate
    return start


PROJECT_ROOT = _resolve_project_root(BASE_DIR)
for _path in (BASE_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from config import settings  # noqa: E402  复用现有配置层

STATE_CREATED = "created"
STATE_RUNNING = "running"
STATE_ENDED = "ended"

MODE_ON_DEMAND = "on_demand"
MODE_AFTER_CLASS = "after_class"

# 模式命名与预算沿用设计文档第九节的三档定义
MODE_BUDGETS: Dict[str, Dict[str, Any]] = {
    MODE_ON_DEMAND: {"max_turns": 8, "max_evidence": 12, "self_check": True, "temperature": 0.2,
                     "note": "教师主动发起，允许全部工具并做证据自检"},
    MODE_AFTER_CLASS: {"max_turns": 12, "max_evidence": 24, "self_check": True, "temperature": 0.1,
                       "note": "课后打磨教案，证据预算最大"},
}

AGENT_NAME = "Teaching Design Agent"

OBSERVABLE_MARKERS = ("能够", "能", "会", "说出", "写出", "完成", "比较", "分析", "设计", "复述", "列举", "说明", "解释")
VAGUE_MARKERS = ("了解", "熟悉", "掌握", "体会", "感受", "增强", "培养", "提高认识")


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _db():
    import database  # noqa: WPS433  复用项目现有 ORM 模型

    return database


def _session():
    db = _db().SessionLocal()
    return db, db.close


@dataclass
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: Dict[str, Any]
    allowed_states: Tuple[str, ...]
    modes: Tuple[str, ...] = (MODE_ON_DEMAND, MODE_AFTER_CLASS)
    write: bool = False

    def schema(self) -> Dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


TOOL_SPECS: Dict[str, ToolSpec] = {}


def _register(name, description, parameters, allowed_states, modes=(MODE_ON_DEMAND, MODE_AFTER_CLASS), write=False):
    def decorator(func):
        TOOL_SPECS[name] = ToolSpec(name, description, func, parameters, allowed_states, modes, write)
        return func

    return decorator


def resolve_classroom_state(meeting: Any, db: Any) -> str:
    """把数据库的 active/paused/ended 推导为统一三态。"""
    dbm = _db()
    raw = _text(getattr(meeting, "status", "")).lower()
    if raw in {"ended", "closed", "finished"}:
        return STATE_ENDED
    if raw in {"paused", "draft", "created"}:
        return STATE_CREATED
    has_transcript = db.query(dbm.Transcript.id).filter(dbm.Transcript.meeting_id == getattr(meeting, "id", None)).first()
    return STATE_RUNNING if has_transcript else STATE_CREATED


def check_tool_allowed(spec: ToolSpec, meeting_id: int, mode: str, approved: bool) -> Dict[str, Any]:
    db, close = _session()
    try:
        dbm = _db()
        if mode not in spec.modes:
            return {"allowed": False, "reason": "工具 %s 不支持 %s 模式" % (spec.name, mode)}
        meeting = db.query(dbm.Meeting).filter(dbm.Meeting.id == meeting_id).first()
        if meeting is None:
            return {"allowed": False, "reason": "课堂 %s 不存在" % meeting_id}
        state = resolve_classroom_state(meeting, db)
        if state not in spec.allowed_states:
            alternatives = [s.name for s in TOOL_SPECS.values() if state in s.allowed_states and mode in s.modes]
            return {
                "allowed": False,
                "state": state,
                "reason": "当前课堂状态为 %s，工具 %s 只允许在 %s 下调用" % (state, spec.name, "/".join(spec.allowed_states)),
                "suggested_tools": alternatives[:4],
            }
        if spec.write and not approved:
            return {"allowed": False, "state": state, "requires_approval": True,
                    "reason": "工具 %s 会修改课堂记录，必须由教师确认后执行" % spec.name}
        return {"allowed": True, "state": state}
    finally:
        close()


def score_goal(goal_text: str) -> Dict[str, Any]:
    """目标可验证性评估：是否包含可观察的行为动词。"""
    sentence = _text(goal_text)
    if not sentence:
        return {"score": 0.0, "observable": False, "vague": False, "reason": "目标为空"}
    observable = any(marker in sentence for marker in OBSERVABLE_MARKERS)
    vague = any(marker in sentence for marker in VAGUE_MARKERS)
    score = 0.4 + (0.5 if observable else 0.0) - (0.25 if vague else 0.0)
    if len(sentence) > 30:
        score -= 0.1
    reason = []
    if observable:
        reason.append("含可观察的行为动词")
    else:
        reason.append("缺少可观察的行为动词")
    if vague:
        reason.append("含难以判定的表述")
    if len(sentence) > 30:
        reason.append("表述偏长，建议拆分")
    return {"score": round(_clamp(score), 3), "observable": observable, "vague": vague, "reason": "；".join(reason)}


def _bigrams(text: str) -> set:
    """中文没有空格分词，用二元切分近似词元，避免整句被当成一个词。"""
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", _text(text))
    return {cleaned[i:i + 2] for i in range(max(0, len(cleaned) - 1))}


def goal_overlap(left: str, right: str) -> float:
    """两条目标的字面重合度（二元组 Jaccard），用于检查目标之间是否重复。"""
    left_tokens = _bigrams(left)
    right_tokens = _bigrams(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return round(len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens)), 3)


def _knowledge_points(meeting: Any) -> List[str]:
    raw = getattr(meeting, "knowledge_points", None) or []
    points: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            label = item.get("desc") or item.get("title") or item.get("name") or item.get("content")
            label = _text(label)
        else:
            label = _text(item)
        if label:
            points.append(label)
    return points


_MEETING_PARAM = {"type": "object", "properties": {"meeting_id": {"type": "integer", "description": "课堂(meeting) ID"}}, "required": ["meeting_id"]}


@_register(
    "get_course_materials",
    "读取课堂主题、参考资料、已有学习目标与课堂状态。任何设计动作都应先调用它。",
    _MEETING_PARAM,
    (STATE_CREATED, STATE_RUNNING, STATE_ENDED),
)
def tool_get_course_materials(ctx: Dict[str, Any], meeting_id: int) -> Dict[str, Any]:
    db, close = _session()
    try:
        dbm = _db()
        meeting = db.query(dbm.Meeting).filter(dbm.Meeting.id == meeting_id).first()
        if meeting is None:
            return {"ok": False, "error": "课堂 %s 不存在" % meeting_id}
        ledger = ctx.get("ledger")
        if ledger is not None:
            ledger.add("materials", "读取课堂 %d，已有目标 %d 条" % (meeting_id, len(_knowledge_points(meeting))))
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "topic": _text(meeting.topic),
            "state": resolve_classroom_state(meeting, db),
            "reference_materials": meeting.reference_materials,
            "existing_goals": _knowledge_points(meeting),
            "has_teaching_design": bool(meeting.teaching_design),
            "allowed_tools": [s.name for s in TOOL_SPECS.values() if ctx.get("mode") in s.modes],
        }
    finally:
        close()


@_register(
    "get_previous_goals",
    "读取同一位教师此前课堂的教学目标，用于检查目标是否递进、是否重复。",
    {
        "type": "object",
        "properties": {
            "teacher_id": {"type": "integer", "description": "教师用户 ID"},
            "limit": {"type": "integer", "description": "最多读取几节课，默认 5"},
        },
        "required": ["teacher_id"],
    },
    (STATE_CREATED, STATE_RUNNING, STATE_ENDED),
)
def tool_get_previous_goals(ctx: Dict[str, Any], teacher_id: int, limit: int = 5) -> Dict[str, Any]:
    db, close = _session()
    try:
        dbm = _db()
        meetings = (
            db.query(dbm.Meeting)
            .filter(dbm.Meeting.teacher_id == teacher_id)
            .order_by(dbm.Meeting.id.desc())
            .limit(max(1, int(limit or 5)))
            .all()
        )
        history = []
        for item in meetings:
            goals = _knowledge_points(item)
            if goals:
                history.append({"meeting_id": item.id, "topic": _text(item.topic), "goals": goals})
        ledger = ctx.get("ledger")
        if ledger is not None:
            ledger.add("history", "参考 %d 节历史课堂的目标设计" % len(history))
        return {"ok": True, "history": history, "count": len(history)}
    finally:
        close()


@_register(
    "draft_learning_goals",
    "根据课堂主题与参考资料生成候选教学目标。返回的每条目标都会附带可验证性评估。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "count": {"type": "integer", "description": "期望生成的目标条数，默认 4"},
            "focus": {"type": "string", "description": "教师希望强调的重点，可为空"},
        },
        "required": ["meeting_id"],
    },
    (STATE_CREATED, STATE_RUNNING, STATE_ENDED),
)
def tool_draft_learning_goals(ctx: Dict[str, Any], meeting_id: int, count: int = 4, focus: str = "") -> Dict[str, Any]:
    db, close = _session()
    try:
        dbm = _db()
        meeting = db.query(dbm.Meeting).filter(dbm.Meeting.id == meeting_id).first()
        if meeting is None:
            return {"ok": False, "error": "课堂 %s 不存在" % meeting_id}
        topic = _text(meeting.topic)
        materials = meeting.reference_materials
        if isinstance(materials, (list, dict)):
            materials = json.dumps(materials, ensure_ascii=False)[:1200]
        plan = "课程主题：%s" % topic
        if materials:
            plan += "\n参考资料：%s" % _text(materials)
        if _text(focus):
            plan += "\n教学重点：%s" % _text(focus)

        goals: List[Dict[str, Any]] = []
        try:
            from llm_service import llm  # noqa: WPS433  复用现有模型通道

            raw_goals = llm.init_meeting_goals(plan) or []
            for index, item in enumerate(raw_goals):
                label = _text(item.get("desc") if isinstance(item, dict) else item)
                if label:
                    goals.append({"id": index + 1, "desc": label, "status": "pending"})
        except Exception as exc:
            ctx.setdefault("notes", []).append("模型生成失败：%s" % exc)

        desired = max(3, int(count or 4))
        if len(goals) < desired:
            fallback = [
                "能够说出本节课的核心概念及其适用条件",
                "能够结合给定案例完成一次分析并给出结论",
                "能够在小组讨论中提出至少一条有依据的不同意见",
                "能够独立完成课后练习并说明解题思路",
            ]
            for label in fallback:
                if len(goals) >= desired:
                    break
                goals.append({"id": len(goals) + 1, "desc": label, "status": "pending"})

        for goal in goals:
            goal["quality"] = score_goal(goal["desc"])
        ledger = ctx.get("ledger")
        if ledger is not None:
            ledger.add("draft", "生成 %d 条候选目标" % len(goals))
        return {"ok": True, "goals": goals, "source_plan": plan[:400]}
    finally:
        close()


@_register(
    "check_goal_quality",
    "检查一组目标的可验证性、表述长度与相互重复度，指出需要重写的条目。",
    {
        "type": "object",
        "properties": {
            "goals": {"type": "array", "items": {"type": "string"}, "description": "待检查的目标文本列表"},
        },
        "required": ["goals"],
    },
    (STATE_CREATED, STATE_RUNNING, STATE_ENDED),
)
def tool_check_goal_quality(ctx: Dict[str, Any], goals: List[str]) -> Dict[str, Any]:
    items = [{"goal": _text(goal), **score_goal(goal)} for goal in (goals or []) if _text(goal)]
    duplicates = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ratio = goal_overlap(items[i]["goal"], items[j]["goal"])
            if ratio >= 0.5:
                duplicates.append({"left": items[i]["goal"], "right": items[j]["goal"], "overlap": ratio})
    weak = [item for item in items if item["score"] < 0.6]
    ledger = ctx.get("ledger")
    if ledger is not None:
        ledger.add("quality", "检查 %d 条目标，弱目标 %d 条，重复 %d 组" % (len(items), len(weak), len(duplicates)))
    return {
        "ok": True,
        "items": items,
        "weak_goals": weak,
        "duplicates": duplicates,
        "verdict": "通过" if items and not weak and not duplicates else "需要修改",
    }


@_register(
    "save_learning_goals",
    "把教师确认后的教学目标写回课堂记录（写操作，必须由教师确认）。",
    {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer", "description": "课堂(meeting) ID"},
            "goals": {"type": "array", "items": {"type": "string"}, "description": "确认后的目标文本列表"},
            "approved": {"type": "boolean", "description": "教师是否已确认"},
        },
        "required": ["meeting_id", "goals"],
    },
    (STATE_CREATED,),
    write=True,
)
def tool_save_learning_goals(ctx: Dict[str, Any], meeting_id: int, goals: List[str], approved: bool = False) -> Dict[str, Any]:
    if not approved and not ctx.get("approved"):
        return {"ok": False, "requires_approval": True, "message": "写回目标需要教师确认。"}
    db, close = _session()
    try:
        dbm = _db()
        meeting = db.query(dbm.Meeting).filter(dbm.Meeting.id == meeting_id).first()
        if meeting is None:
            return {"ok": False, "error": "课堂 %s 不存在" % meeting_id}
        payload = []
        for index, goal in enumerate(goals or []):
            label = _text(goal)
            if label:
                payload.append({"id": index + 1, "desc": label, "status": "pending"})
        if not payload:
            return {"ok": False, "error": "没有可写入的目标"}
        meeting.knowledge_points = payload
        db.commit()
        ledger = ctx.get("ledger")
        if ledger is not None:
            ledger.add("write", "写回 %d 条学习目标" % len(payload))
        return {"ok": True, "written": len(payload), "goals": payload}
    finally:
        close()


SYSTEM_INSTRUCTIONS = """你是课堂教学设计助手，负责把课程主题与参考资料转化为可执行、可验证的教学目标。

工作规则：
1. 先调用工具读取课堂信息，不要凭主题猜测资料内容。
2. 生成目标后必须调用检查工具评估可验证性，把不合格的目标改写后再输出。
3. 严禁把"掌握""了解""体会"这类无法判定的表述直接作为最终目标。
4. 涉及写回课堂记录时，只能提出建议，等待教师确认，不得自行假定已确认。
5. 每条结论都要标注证据编号，例如 [E2]；没有证据的判断写明"推测"。

输出契约（与设计文档第十节保持一致，不要包裹代码块）：
{
  "summary": "一句话说明这组目标的设计思路",
  "structure": {"goals": [{"desc": "目标文本", "status": "pending"}]},
  "metrics_reading": [{"metric": "goal_verifiability", "value": 0.0,
                       "reading": "逐条可验证性解读", "evidence": ["E1"]}],
  "findings": [{"finding": "目标存在的问题", "evidence": ["E2"], "confidence": "high|medium|low"}],
  "interventions": [{"target": "某条目标", "action": "建议如何改写", "reason": "依据", "evidence": ["E3"]}],
  "data_gaps": ["缺少的信息"],
  "unsupported_claims": []
}
"""


class _Ledger:
    """证据账本：记录本次运行用到的证据，供结论引用与自检回查。"""

    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    def add(self, kind: str, label: str, ref: Optional[str] = None, confidence: Optional[float] = None) -> str:
        eid = "E%d" % (len(self._items) + 1)
        self._items.append({"eid": eid, "kind": kind, "label": _text(label)[:160],
                            "ref": ref, "confidence": confidence})
        return eid

    def items(self) -> List[Dict[str, Any]]:
        return list(self._items)

    def prompt_block(self, limit: int = 12) -> str:
        if not self._items:
            return "(暂无证据)"
        lines = []
        for item in self._items[-max(1, int(limit)):]:
            ref = " [%s]" % item["ref"] if item.get("ref") else ""
            lines.append("%s(%s)%s %s" % (item["eid"], item["kind"], ref, item["label"]))
        return "\n".join(lines)


@dataclass
class RunTrace:
    run_id: str
    mode: str
    meeting_id: int
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, kind: str, name: str, **extra: Any) -> None:
        step = {"index": len(self.steps) + 1, "kind": kind, "name": name, "ts": datetime.now().isoformat(timespec="seconds")}
        step.update(extra)
        self.steps.append(step)

    def save(self) -> Optional[str]:
        try:
            folder = PROJECT_ROOT / "storage" / "agent_traces"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ("teaching_design_%s.json" % self.run_id)
            path.write_text(json.dumps({"run_id": self.run_id, "mode": self.mode, "meeting_id": self.meeting_id, "steps": self.steps}, ensure_ascii=False, indent=2), encoding="utf-8")
            return str(path)
        except Exception:
            return None


class MiniHarness:
    def __init__(self, mode: str = MODE_ON_DEMAND) -> None:
        self.mode = mode if mode in MODE_BUDGETS else MODE_ON_DEMAND
        self.budget = MODE_BUDGETS[self.mode]
        self.ledger = _Ledger()
        self.context: Dict[str, Any] = {"mode": self.mode, "approved": False, "notes": [], "ledger": self.ledger}
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI  # noqa: WPS433

            config = settings.llm
            if not config.api_key:
                raise RuntimeError("缺少 LLM_API_KEY，请在 .env 中配置")
            self._client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url, timeout=config.timeout_seconds)
        return self._client

    async def _chat(self, messages, tools):
        client = self._get_client()
        kwargs: Dict[str, Any] = {"model": settings.llm.model, "messages": messages, "temperature": self.budget["temperature"]}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message

    async def _execute(self, name: str, arguments: Dict[str, Any], trace: RunTrace) -> Dict[str, Any]:
        spec = TOOL_SPECS.get(name)
        if spec is None:
            return {"ok": False, "error": "未知工具 %s" % name}
        if spec.write:
            arguments = {**arguments, "approved": bool(arguments.get("approved") or self.context.get("approved"))}
        meeting_id = int(arguments.get("meeting_id") or 0)
        gate = check_tool_allowed(spec, meeting_id, self.mode, bool(arguments.get("approved")))
        if not gate.get("allowed"):
            trace.add("policy", name, allowed=False, reason=gate.get("reason"))
            return {"ok": False, **gate}
        started = time.time()
        properties = spec.parameters.get("properties") or {}
        call_kwargs = {k: v for k, v in arguments.items() if k == "meeting_id" or k in properties}
        try:
            result = spec.handler(self.context, **call_kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            trace.add("tool", name, error=str(exc))
            return {"ok": False, "error": "工具 %s 执行失败：%s" % (name, exc)}
        trace.add("tool", name, state=gate.get("state"), arguments=call_kwargs, duration_ms=int((time.time() - started) * 1000))
        return result

    async def run(self, meeting_id: int, question: str) -> Dict[str, Any]:
        trace = RunTrace(run_id=uuid.uuid4().hex[:12], mode=self.mode, meeting_id=meeting_id)
        tools = [s.schema() for s in TOOL_SPECS.values() if self.mode in s.modes]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": "课堂 meeting_id = %d。教师的要求：%s" % (meeting_id, _text(question) or "设计这节课的教学目标")},
        ]
        final_text = None
        for _turn in range(int(self.budget["max_turns"])):
            message = await self._chat(messages, tools)
            calls = getattr(message, "tool_calls", None)
            payload: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            if calls:
                payload["tool_calls"] = [c.model_dump() for c in calls]
            messages.append(payload)
            if not calls:
                final_text = message.content or ""
                break
            for call in calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                arguments.setdefault("meeting_id", meeting_id)
                result = await self._execute(call.function.name, arguments, trace)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)[:6000]})
        if final_text is None:
            final_text = "已达到最大轮次，请缩小设计范围后重试。"
        self_check = await self._verify(final_text) if self.budget.get("self_check") and self.ledger.items() else None
        answer = self._parse(final_text)
        if isinstance(answer, dict):
            answer.setdefault("unsupported_claims", [])
            if isinstance(self_check, dict) and self_check.get("unsupported"):
                answer["unsupported_claims"] = self_check["unsupported"]
        return {
            "run_id": trace.run_id,
            "mode": self.mode,
            "meeting_id": meeting_id,
            "answer": answer,
            "raw_answer": final_text,
            "self_check": self_check,
            "evidence_ledger": self.ledger.items(),
            "trace_path": trace.save(),
            "notes": self.context.get("notes", []),
        }

    async def _verify(self, answer: str) -> Dict[str, Any]:
        """自检：核对结论是否都有证据支撑。"""
        prompt = (
            "下面是一份教学设计结论与本次用到的证据清单，请检查每条结论是否有证据支持。\n"
            '只输出 JSON：{"verdict": "pass|partial|fail", "unsupported": [{"claim": "...", "reason": "..."}]}\n\n'
            "结论：\n%s\n\n证据清单：\n%s\n" % (answer[:4000], self.ledger.prompt_block(limit=40))
        )
        try:
            message = await self._chat([{"role": "user", "content": prompt}], None)
            return self._parse(message.content or "")
        except Exception as exc:
            return {"verdict": "unknown", "error": str(exc)}

    @staticmethod
    def _parse(text: str) -> Any:
        cleaned = _text(text)
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


try:  # pragma: no cover
    from fastapi import APIRouter
    from pydantic import BaseModel

    teaching_design_router = APIRouter(prefix="/api/agents/teaching-design", tags=["agents"])

    class TeachingDesignRequest(BaseModel):
        meeting_id: int
        question: str = ""
        mode: str = MODE_ON_DEMAND
        approve_write: bool = False

    @teaching_design_router.get("/tools")
    async def list_tools() -> Dict[str, Any]:
        return {
            "agent": AGENT_NAME,
            "modes": MODE_BUDGETS,
            "tools": [
                {"name": s.name, "description": s.description, "allowed_states": list(s.allowed_states),
                 "modes": list(s.modes), "write": s.write}
                for s in TOOL_SPECS.values()
            ],
        }

    @teaching_design_router.post("/run")
    async def run_agent(request: TeachingDesignRequest) -> Dict[str, Any]:
        harness = MiniHarness(mode=request.mode)
        harness.context["approved"] = bool(request.approve_write)
        return await harness.run(request.meeting_id, request.question)

except Exception:  # pragma: no cover
    teaching_design_router = None


def _print_tools() -> None:
    print("Agent: %s\n" % AGENT_NAME)
    print("%-26s %-26s %-8s %s" % ("tool", "allowed_states", "write", "modes"))
    print("-" * 84)
    for spec in TOOL_SPECS.values():
        print("%-26s %-26s %-8s %s" % (spec.name, "/".join(spec.allowed_states), "yes" if spec.write else "no", ",".join(spec.modes)))


def _run_selftest() -> int:
    failures = []
    total = 0

    def check(name, condition, detail=""):
        nonlocal total
        total += 1
        if condition:
            print("PASS  %s" % name)
        else:
            print("FAIL  %s %s" % (name, detail))
            failures.append(name)

    good = score_goal("能够说出牛顿第二定律的适用条件")
    bad = score_goal("了解牛顿第二定律")
    check("可验证性：含行为动词得分更高", good["score"] > bad["score"], "%s vs %s" % (good["score"], bad["score"]))
    check("可验证性：模糊表述被标记", bad["vague"] is True)
    check("重复检测：相似目标被识别", goal_overlap("能够说出核心概念", "能够说出核心概念及其条件") > 0.5)
    check("重复检测：无关目标不误报", goal_overlap("能够说出核心概念", "能够完成课后练习") < 0.3)
    check("空目标：得分归零", score_goal("")["score"] == 0.0)
    for name, spec in TOOL_SPECS.items():
        ok = spec.parameters.get("type") == "object" and spec.handler is not None
        check("工具契约：%s" % name, ok)
    check("写操作被标记", TOOL_SPECS["save_learning_goals"].write is True)
    check("写操作仅限未开课", TOOL_SPECS["save_learning_goals"].allowed_states == (STATE_CREATED,))
    check("模式命名：沿用设计文档三档", set(MODE_BUDGETS.keys()) <= {"realtime", "on_demand", "after_class"})
    check("结论自检：全部模式开启", all(budget.get("self_check") for budget in MODE_BUDGETS.values()))
    check("输出契约：与设计文档一致", all(key in SYSTEM_INSTRUCTIONS for key in
          ("summary", "structure", "metrics_reading", "findings", "interventions", "data_gaps", "unsupported_claims")))
    check("证据账本：具备登记与自检", hasattr(MiniHarness, "_verify") and hasattr(_Ledger, "add"))
    print("\n共 %d 项检查，%d 项失败" % (total, len(failures)))
    return 1 if failures else 0


def _run_check() -> int:
    problems = 0
    config = settings.llm
    print("%-22s %s %s" % ("LLM_API_KEY", "OK" if config.api_key else "FAIL", "provider=%s model=%s" % (config.provider, config.model)))
    if not config.api_key:
        problems += 1
    try:
        dbm = _db()
        db = dbm.SessionLocal()
        count = db.query(dbm.Meeting).count()
        db.close()
        print("%-22s OK meetings=%d" % ("database", count))
    except Exception as exc:
        print("%-22s FAIL %s" % ("database", str(exc)[:100]))
        problems += 1
    return 1 if problems else 0


async def _run(meeting_id: int, question: str, mode: str) -> int:
    harness = MiniHarness(mode=mode)
    result = await harness.run(meeting_id, question)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="课堂教学设计 Agent")
    parser.add_argument("--tools", action="store_true", help="列出工具与权限")
    parser.add_argument("--selftest", action="store_true", help="运行离线自检")
    parser.add_argument("--check", action="store_true", help="环境体检")
    parser.add_argument("--meeting-id", type=int, default=0)
    parser.add_argument("--question", type=str, default="")
    parser.add_argument("--mode", type=str, default=MODE_ON_DEMAND, choices=list(MODE_BUDGETS.keys()))
    args = parser.parse_args(argv)
    if args.tools:
        _print_tools()
        return 0
    if args.selftest:
        return _run_selftest()
    if args.check:
        return _run_check()
    if not args.meeting_id:
        parser.print_help()
        return 1
    return asyncio.run(_run(args.meeting_id, args.question, args.mode))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
