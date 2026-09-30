"""WebSocket 路由与 `ConnectionManager` 的覆盖。

为什么值得单独测
----------------
`docs/route-inventory.md` 把 59 条路由分成了只读 / 写 / 外部服务 / 推理 / WebSocket
五类。前四类都有对应手段（冒烟基线、打桩、排除），**WebSocket 之前完全没有覆盖**——
3 条 WS 路由一条都没测。而 `/ws/{username}/{meeting_id}` 是课堂实时链路的主干：
成员上下线、音视频分片下发都走它。

好消息是它比看起来好测：`ConnectionManager`（`server.py:2667`）是**纯内存**结构，
不碰数据库、不碰网络；而 Starlette 的 `TestClient.websocket_connect` 是同步 API，
**不需要 pytest-asyncio**——原本以为要引入异步插件，实测用不着。

隔离
----
`manager` 是模块级单例（`server.py:2783`），会在整个测试会话中累积连接与计数。
因此 `fresh_manager` 夹具在每条用例前后做快照/还原，WS 用例也一律使用
**7001 以上的假 meeting_id**，不碰冒烟基线用的 1/2 号课堂。
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------- 搬迁契约（阶段 3）

def test_manager_classes_live_in_app_realtime():
    """两个管理器的类定义必须住在 app/realtime/ 下。

    防的是**搬迁被悄悄撤销**：若有人把类定义重新贴回 server.py，它会遮蔽
    顶部导入进来的同名类，而 `from server import ConnectionManager` 照样能用、
    全部 19 条行为测试照样通过——表面毫无异常，结构却退回了原样。
    只有身份断言能发现这件事。
    """
    import server
    from app.realtime.connection import ConnectionManager as Moved
    from app.realtime.signaling import SignalConnectionManager as MovedSignal

    assert server.ConnectionManager is Moved, "server.ConnectionManager 不是 app/realtime 里那个"
    assert server.SignalConnectionManager is MovedSignal
    assert type(server.manager) is Moved, "manager 单例的类不是迁出后的那个"
    assert type(server.signal_manager) is MovedSignal


@pytest.mark.parametrize("module", ["app.realtime.connection", "app.realtime.signaling"])
def test_realtime_module_is_self_contained(module):
    """app/realtime/ 下的模块必须能**单独导入**，不得依赖 server。

    这是搬迁是否真实完成的另一个侧面：若模块里还留着对 server 的引用
    （哪怕只是 `import server` 拿个常量），就说明它并没有真正独立，
    而 `server` 反过来导入它会形成循环——循环导入失败时信息往往很难读。

    在子进程里导入，避免污染本进程的 sys.modules。
    """
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        f"import {module};"
        "print('server' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"单独导入 {module} 失败：{result.stderr}"
    assert result.stdout.strip() == "False", (
        f"单独导入 {module} 时把 `server` 也拉了起来——该模块并非自足。"
    )


@pytest.fixture
def fresh_manager():
    """造一个全新的 `ConnectionManager`，避免与全局单例互相污染。"""
    from server import ConnectionManager

    return ConnectionManager()


@pytest.fixture(autouse=True)
def isolate_global_manager():
    """用例结束后把全局 `manager` 的内部状态还原。

    WS 路由用的是 `server.manager` 这个单例，不是夹具里那个新实例——二者
    都要照顾到：单例会被 WS 用例改动，必须还原。
    """
    from server import manager

    saved = {
        "active": list(manager.active),
        "meeting_connections": {k: dict(v) for k, v in manager.meeting_connections.items()},
        "last_speech_time": dict(manager.last_speech_time),
        "speech_counts": {k: dict(v) for k, v in manager.speech_counts.items()},
        "silence_notified": dict(manager.silence_notified),
    }
    try:
        yield
    finally:
        manager.active[:] = saved["active"]
        manager.meeting_connections.clear()
        manager.meeting_connections.update(saved["meeting_connections"])
        manager.last_speech_time.clear()
        manager.last_speech_time.update(saved["last_speech_time"])
        manager.speech_counts.clear()
        manager.speech_counts.update(saved["speech_counts"])
        manager.silence_notified.clear()
        manager.silence_notified.update(saved["silence_notified"])


def _connect(mgr, meeting_id, *usernames):
    """在 manager 里登记若干"连接"（用哨兵对象代替真实 websocket）。"""
    mgr.meeting_connections.setdefault(meeting_id, {})
    for name in usernames:
        mgr.meeting_connections[meeting_id][name] = object()
    return mgr.meeting_connections[meeting_id]


# ---------------------------------------------------- ConnectionManager 纯逻辑


def test_online_members_is_empty_for_unknown_meeting(fresh_manager):
    """没连接过的课堂返回空列表，而不是抛 KeyError。"""
    assert fresh_manager.get_online_members(999999) == []


def test_online_members_lists_connected_users(fresh_manager):
    """在线成员即该课堂的连接名，按加入顺序。"""
    _connect(fresh_manager, 101, "甲同学", "乙同学")

    assert fresh_manager.get_online_members(101) == ["甲同学", "乙同学"]


def test_disconnect_removes_only_that_user(fresh_manager):
    """断开一个人不影响同课堂其他人。"""
    conns = _connect(fresh_manager, 101, "甲同学", "乙同学")
    ws = conns["甲同学"]
    fresh_manager.active.append(ws)

    fresh_manager.disconnect(ws, 101, "甲同学")

    assert fresh_manager.get_online_members(101) == ["乙同学"]
    assert ws not in fresh_manager.active


def test_disconnect_is_idempotent(fresh_manager):
    """重复断开不得抛异常。"""
    conns = _connect(fresh_manager, 101, "甲同学")
    ws = conns["甲同学"]

    fresh_manager.disconnect(ws, 101, "甲同学")
    fresh_manager.disconnect(ws, 101, "甲同学")

    assert fresh_manager.get_online_members(101) == []


def test_record_speech_updates_count_and_clears_silence_flag(fresh_manager):
    """发言后计数 +1，并复位"已提醒沉默"标记。"""
    fresh_manager.silence_notified[101] = True

    fresh_manager.record_speech(101, "甲同学")
    fresh_manager.record_speech(101, "甲同学")
    fresh_manager.record_speech(101, "乙同学")

    assert fresh_manager.speech_counts[101] == {"甲同学": 2, "乙同学": 1}
    assert fresh_manager.silence_notified[101] is False


def test_group_is_not_silent_before_any_speech(fresh_manager):
    """从未有人发言时不判定为沉默——否则新课一开始就会被报"沉默"。"""
    assert fresh_manager.is_group_silent(101, silence_seconds=0) is False


def test_group_silent_threshold_is_respected(fresh_manager):
    """阈值判定：改用极小阈值即可稳定触发，无需 sleep 等待。"""
    fresh_manager.record_speech(101, "甲同学")

    assert fresh_manager.is_group_silent(101, silence_seconds=0) is True
    assert fresh_manager.is_group_silent(101, silence_seconds=3600) is False


def test_group_silent_uses_wall_clock(fresh_manager):
    """沉默时长按真实经过时间计算。"""
    fresh_manager.last_speech_time[101] = time.time() - 10

    assert fresh_manager.is_group_silent(101, silence_seconds=5) is True
    assert fresh_manager.is_group_silent(101, silence_seconds=30) is False


@pytest.mark.parametrize(
    "counts,expected",
    [
        ({}, []),                                                  # 无人发言
        ({"甲同学": 1}, []),                                        # 只有一人在线
        ({"甲同学": 1, "乙同学": 0}, ["乙同学"]),                     # 条件1：他人已发言，自己零发言
        ({"甲同学": 5, "乙同学": 5}, []),                            # 势均力敌
        ({"甲同学": 10, "乙同学": 1}, ["乙同学"]),                    # 条件2：远低于他人均值
        ({"甲同学": 0, "乙同学": 0}, []),                            # 都没发言，不触发
    ],
    ids=["nobody-spoke", "single-member", "one-silent", "balanced", "far-below-average", "all-silent"],
)
def test_quiet_member_detection(fresh_manager, counts, expected):
    """发言偏少成员的判定。

    这是"教师端该点名谁"的依据，属业务判断，规则有三条分支（详见
    `server.py:2743-2772`）。参数化把各分支各钉一条。
    """
    _connect(fresh_manager, 101, *counts)
    fresh_manager.speech_counts[101] = dict(counts)

    assert fresh_manager.get_quiet_members(101) == expected


def test_quiet_members_needs_at_least_two_people(fresh_manager):
    """只有一个人在线时无从"相对比较"，一律返回空。"""
    _connect(fresh_manager, 101, "甲同学")
    fresh_manager.speech_counts[101] = {}

    assert fresh_manager.get_quiet_members(101) == []


# ------------------------------------------------------- WebSocket 路由（真实握手）


def test_websocket_join_broadcasts_member_update(local_app):
    """连上即广播一条 `member_update / join`，含当前在线名单。"""
    with TestClient(local_app) as client:
        with client.websocket_connect("/ws/测试同学甲/7001") as ws:
            message = ws.receive_json()

    assert message["type"] == "member_update"
    assert message["action"] == "join"
    assert message["username"] == "测试同学甲"
    assert message["online_members"] == ["测试同学甲"]


def test_websocket_ping_responds_pong(local_app):
    """文本 `ping` 必须得到文本 `pong`——这是前端判活的心跳。"""
    with TestClient(local_app) as client:
        with client.websocket_connect("/ws/测试同学乙/7002") as ws:
            ws.receive_json()  # 先消费 join 广播

            ws.send_text("ping")

            assert ws.receive_text() == "pong"


def test_two_clients_in_same_meeting_see_each_other(local_app):
    """同课堂的两个连接互相可见。

    课堂隔离是这套系统的基本前提（`meeting_connections` 按 meeting_id 分桶），
    这条确认分桶在真实握手下确实生效。
    """
    with TestClient(local_app) as client:
        with client.websocket_connect("/ws/测试同学甲/7003") as ws_a:
            assert ws_a.receive_json()["online_members"] == ["测试同学甲"]

            with client.websocket_connect("/ws/测试同学乙/7003") as ws_b:
                joined = ws_b.receive_json()
                assert joined["username"] == "测试同学乙"
                assert joined["online_members"] == ["测试同学甲", "测试同学乙"]

                # 先连的那位也应收到"有人加入"
                relayed = ws_a.receive_json()
                assert relayed["username"] == "测试同学乙"
                assert relayed["online_members"] == ["测试同学甲", "测试同学乙"]


def test_clients_in_different_meetings_are_isolated(local_app):
    """不同课堂的连接互相不可见——房间隔离的核心断言。

    若 `meeting_connections` 哪天被改成不按 meeting_id 分桶，第二个连接看到的
    在线名单里就会混进第一个课堂的人。

    这里**只断言"看到了什么"，不去断言"没收到什么"**：后者要靠"在超时内收不到
    消息"来证明，而 TestClient 的 `receive_json()` 会一直阻塞，断言不存在的消息
    等于让测试挂死。用「在线名单的构成」间接验证隔离，既充分又不会卡住。
    """
    with TestClient(local_app) as client:
        with client.websocket_connect("/ws/测试同学甲/7004") as ws_a:
            assert ws_a.receive_json()["online_members"] == ["测试同学甲"]

            with client.websocket_connect("/ws/测试同学乙/7005") as ws_b:
                joined = ws_b.receive_json()

    assert joined["username"] == "测试同学乙"
    assert joined["online_members"] == ["测试同学乙"], (
        "另一个课堂的人出现在了 7005 的在线名单里，说明房间隔离失效"
    )
