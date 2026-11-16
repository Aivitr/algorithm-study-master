# -*- coding: utf-8 -*-
"""444dsh 命令行：注册 / 登录 / 建课堂 / 开课 / 灌样本 / 看 GCA。

为什么需要它：仓库自带的 `/api/register`、`/api/login` 原本直连 MSSQL（pymssql），
只给浏览器表单用；本地 SQLite 模式下没有 curl 能走通的注册登录入口，也没法
在不点页面的情况下把课堂推到 running。这里把这些步骤全部命令行化。

用法（在 D:\\444dsh 下，服务已由 tools/dev_server.py 起在 8000）：

    .venv\\Scripts\\python.exe tools\\dev_cli.py register   --id t01 --name 张老师 --password 123456 --role teacher
    .venv\\Scripts\\python.exe tools\\dev_cli.py login      --id t01 --password 123456
    .venv\\Scripts\\python.exe tools\\dev_cli.py classroom  --class-code 100 --topic 光合作用
    .venv\\Scripts\\python.exe tools\\dev_cli.py start-class --meeting-id 1
    .venv\\Scripts\\python.exe tools\\dev_cli.py seed       --meeting-id 1
    .venv\\Scripts\\python.exe tools\\dev_cli.py insight    --meeting-id 1

服务地址可用 --base 覆盖（默认 http://127.0.0.1:8000）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SESSION_FILE = ROOT / "storage" / "dev_session.json"


# ── 会话缓存 ─────────────────────────────────────────────────────────────
def _save_session(payload: dict) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_session() -> dict:
    if SESSION_FILE.is_file():
        try:
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _auth_headers() -> dict:
    token = os.getenv("DSH_TOKEN") or _load_session().get("session_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _pp(title: str, data) -> None:
    print(f"--- {title} ---")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ── 命令 ────────────────────────────────────────────────────────────────
def cmd_register(args) -> int:
    r = requests.post(
        f"{args.base}/api/register",
        data={
            "student_id": args.id,
            "username": args.name,
            "password": args.password,
            "role": args.role,
        },
        timeout=30,
    )
    _pp("register", r.json())
    return 0 if r.json().get("status") == "success" else 1


def cmd_login(args) -> int:
    r = requests.post(
        f"{args.base}/api/login",
        data={"student_id": args.id, "password": args.password, "device_id": args.device_id},
        timeout=30,
    )
    body = r.json()
    _pp("login", body)
    if body.get("status") != "success":
        return 1
    _save_session(body)
    print(f"\n[token] {body['session_token']}")
    print(f"[saved] {SESSION_FILE}")
    print("\n后续命令行直接复用该 token；换浏览器看页面时用同一账号登录即可。")
    return 0


def cmd_classroom(args) -> int:
    """等价于教师端「创建课堂」：POST /login（表单，ORM 路径）。"""
    r = requests.post(
        f"{args.base}/login",
        data={
            "username": args.username,
            "student_id": args.id,
            "class_code": args.class_code,
            "role": "teacher",
            "topic": args.topic,
        },
        timeout=120,
    )
    body = r.json()
    _pp("classroom", body)
    if body.get("status") == "success":
        sess = _load_session()
        sess["meeting_id"] = body.get("meeting_id")
        sess["class_code"] = args.class_code
        _save_session(sess)
        print(f"\n[meeting_id] {body.get('meeting_id')}  (class_code={args.class_code})")
        return 0
    return 1


def cmd_start_class(args) -> int:
    r = requests.post(
        f"{args.base}/api/start-class",
        data={"meeting_id": args.meeting_id, "username": args.username},
        headers=_auth_headers(),
        timeout=60,
    )
    _pp("start-class", r.json())
    return 0 if r.ok else 1


def cmd_seed(args) -> int:
    """灌课堂发言样本。

    真实链路里 Transcript 由 ASR 写入（WebSocket 语音流），命令行没有对应 REST
    入口；这里直接走同一套 ORM 写库，字段与 ASR 落库完全一致，供 GCA 引擎计算。
    """
    os.environ.setdefault("DATABASE_URL", "sqlite:///./storage/app.db")
    os.environ.setdefault("DB_AUTO_MIGRATE", "0")

    from app.core.database import SessionLocal
    from app.models import Meeting, Transcript, User

    samples = [
        ("2001", "光合作用分光反应和暗反应两个阶段，光反应在类囊体薄膜上进行。", 88, "neutral"),
        ("2002", "光反应把水分解产生氧气，同时生成 ATP 和 NADPH 给暗反应用。", 85, "excited"),
        ("2003", "那暗反应具体在哪儿发生？是在叶绿体基质里吗？", 70, "curious"),
        ("2001", "对，暗反应在叶绿体基质，主要是卡尔文循环固定二氧化碳。", 90, "neutral"),
        ("2004", "如果光照突然减弱，光反应先受影响，ATP 和 NADPH 减少，暗反应也会跟着慢下来。", 92, "excited"),
        ("2002", "那暗反应能不能自己独立进行？没有光的时候会怎样？", 78, "curious"),
        ("2003", "我觉得不能，因为暗反应需要光反应提供的能量和还原剂。", 86, "neutral"),
        ("2001", "实验里我们可以用碘液检测淀粉，判断光合作用有没有发生。", 82, "neutral"),
        ("2004", "遮光的那组叶片滴碘液不变蓝，说明没有产生淀粉。", 88, "excited"),
        ("2002", "所以光照是限制因素，那温度和二氧化碳浓度也会影响吧？", 80, "curious"),
        ("2003", "温度影响酶的活性，二氧化碳浓度影响暗反应的固定速率。", 87, "neutral"),
        ("2004", "我们可以设计对照实验，分别改变光照、温度、二氧化碳浓度来验证。", 91, "excited"),
        ("2001", "我补充一点，光反应产生的氧气来自水的光解，不是二氧化碳。", 89, "neutral"),
        ("2002", "那用同位素标记氧就能证明这个结论，课件上有类似实验。", 84, "curious"),
        ("2003", "对，用 18O 标记水，释放的氧气就是 18O2，能直接看出来。", 88, "excited"),
        ("2004", "如果只改温度不改光照，光反应速率也会受酶的影响吗？", 81, "curious"),
        ("2001", "光反应里的酶也怕高温，超过最适温度速率会掉下来。", 86, "neutral"),
        ("2002", "所以光合速率是多个因素共同限制的，不是单一变量。", 90, "thoughtful"),
        ("2003", "那我们设计实验时得控制变量，一次只改一个条件。", 85, "neutral"),
        ("2004", "我提议把全班数据汇总成一张表，比较不同处理组的淀粉量。", 89, "excited"),
        ("2001", "汇总时可以画柱状图，横轴是处理组，纵轴是淀粉检测强度。", 87, "neutral"),
        ("2002", "这样能看出遮光组明显低于对照组，结论比较有说服力。", 88, "excited"),
        ("2003", "我还有一个疑问，暗反应固定二氧化碳的酶受光照影响吗？", 79, "curious"),
        ("2004", "严格说不直接受光影响，但没有 ATP 和 NADPH 也跑不动。", 91, "thoughtful"),
        ("2001", "所以两个阶段是耦合的，缺一不可，这一点要写进结论。", 90, "neutral"),
        ("2002", "那我们下次课可以测不同光强下的氧气释放速率。", 83, "excited"),
        ("2003", "我可以负责记录数据，把每次测量结果填进表格。", 82, "neutral"),
        ("2004", "我来画图，最后一起核对结论和误差来源。", 86, "excited"),
    ]

    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == args.meeting_id).first()
        if meeting is None:
            print(f"[ERROR] meeting {args.meeting_id} 不存在，先跑 classroom 子命令")
            return 1

        users = {}
        for student_id, name in (("2001", "李同学"), ("2002", "王同学"), ("2003", "陈同学"), ("2004", "赵同学")):
            row = db.query(User).filter(User.student_id == student_id).first()
            if row is None:
                row = User(student_id=student_id, username=name, password="123456", role="student")
                db.add(row)
                db.flush()
            users[student_id] = row

        db.query(Transcript).filter(Transcript.meeting_id == meeting.id).delete()
        db.flush()

        base_time = meeting.started_at or datetime.now() - timedelta(minutes=40)
        # 课堂从 10 分钟前开始；发言按 20 秒间隔铺满整段，避免大量空窗口把
        # GCA 的窗口均值压到 0（引擎按 300s 窗口 / 150s 步长滑动统计）。
        meeting.started_at = datetime.now() - timedelta(minutes=10)
        base_time = meeting.started_at
        for index, (sid, text, quality, emotion) in enumerate(samples):
            occurred_at = base_time + timedelta(seconds=index * 20)
            db.add(
                Transcript(
                    meeting_id=meeting.id,
                    user_id=users[sid].id,
                    content=text,
                    quality_score=quality,
                    quality_feedback="内容与课堂目标相关",
                    relevance_score=quality,
                    emotion_tag=emotion,
                    audio_tone="normal",
                    body_action="listening",
                    created_at=occurred_at,
                    timestamp=occurred_at,
                )
            )
        db.commit()
        print(f"[seed] meeting {meeting.id}: 写入 {len(samples)} 条发言，4 名学生，覆盖 10 分钟窗口")
        return 0
    finally:
        db.close()


def cmd_insight(args) -> int:
    mid = args.meeting_id
    metrics = requests.get(f"{args.base}/api/agents/group-analysis/metrics/{mid}", timeout=120).json()
    tools = requests.get(f"{args.base}/api/agents/group-analysis/tools", timeout=30).json()
    transcripts = requests.get(f"{args.base}/api/transcripts/{mid}?limit=500", timeout=60).json()

    group = metrics.get("group_metrics") or {}
    print(f"--- GCA 六指标 (meeting {mid}) ---")
    for key, value in group.items():
        mean = value.get("mean")
        print(f"  {key:<24} {('%.0f%%' % (mean * 100)) if isinstance(mean, (int, float)) else mean}")
    print(f"  status={metrics.get('status')}  warnings={metrics.get('warnings')}")
    print(f"\n--- 可用工具 ({len(tools.get('tools', []))}) ---")
    for tool in tools.get("tools", []):
        print(f"  {tool['name']:<18} {tool['description']}")
    items = transcripts.get("transcripts") or transcripts.get("items") or []
    print(f"\n--- 证据（发言条数 {len(items)}）---")
    for item in items[:3]:
        print(f"  T#{item.get('id')} {item.get('content')}")
    print(f"\n页面入口：{args.base}/  → 教师登录 → 进入课堂 → 右栏「分析」")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="444dsh 本地命令行")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("register", help="注册账号")
    r.add_argument("--id", required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--password", default="123456")
    r.add_argument("--role", default="student", choices=["student", "teacher"])
    r.set_defaults(func=cmd_register)

    l = sub.add_parser("login", help="登录并缓存 session token")
    l.add_argument("--id", required=True)
    l.add_argument("--password", default="123456")
    l.add_argument("--device-id", default="cli-device")
    l.set_defaults(func=cmd_login)

    c = sub.add_parser("classroom", help="教师创建/进入课堂")
    c.add_argument("--class-code", required=True)
    c.add_argument("--topic", required=True)
    c.add_argument("--id", default="t01")
    c.add_argument("--username", default="张老师")
    c.set_defaults(func=cmd_classroom)

    s = sub.add_parser("start-class", help="开始课堂（created → running）")
    s.add_argument("--meeting-id", type=int, required=True)
    s.add_argument("--username", default="张老师")
    s.set_defaults(func=cmd_start_class)

    d = sub.add_parser("seed", help="写入课堂发言样本")
    d.add_argument("--meeting-id", type=int, required=True)
    d.set_defaults(func=cmd_seed)

    i = sub.add_parser("insight", help="打印 GCA 指标 / 工具 / 证据")
    i.add_argument("--meeting-id", type=int, required=True)
    i.set_defaults(func=cmd_insight)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
