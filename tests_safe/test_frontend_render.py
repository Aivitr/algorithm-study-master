"""前端渲染与事件接线的守卫 —— ②b（组件拆分）的验收能力。

它补的是哪个洞
==============
阶段 7 只做了 ②b 里**逐字节可证明**的那一半（把内联的 `<style>`/`<script>`
外移成 `static/css/app.css` 与 `static/js/app.js`，见
`test_frontend_extraction.py`）。另一半是**组件拆分**：它要动模板结构，
设计文档给的验收标准是"功能逐项对照通过"。

当时把这一半挂起了，理由是"本地没有浏览器，没法逐项点，因而无法证明没有
改变行为"（`docs/待验收事项.md` A27）。

**那个理由是错的。** jsdom 能真跑 Vue 2：组件挂载、插值求值、事件绑定、
`$emit` 传播都按真实语义走。`tools/frontend_probe.js` 把两件事变成可自动比对的
对象：

* **多状态 DOM 快照** —— 11 个状态（5 个页块 + 学生/教师两种角色 + 4 个弹窗）
  各自的 `#app` 渲染结果，逐个做 SHA256。拆分前后逐字节相同 = 渲染结构没变。
* **点击序列断言** —— 4 条页面间导航各自真的点一下、再读 `pageState`。
  这一条不能用快照代替：`@click` 绑了什么，渲染成 DOM 之后**看不出痕迹**，
  只剩一个监听器。把 `pageState='login'` 换成 `$emit('go-login')` 而忘了接，
  快照照样全绿，只有点一下才露馅。

为什么它能给组件拆分背书
========================
组件拆分最典型的三类破坏，恰好被这两条覆盖：

1. **少传一个 prop。** 子组件里读到 `undefined`，`v-if` 求值成假 → 渲染出来的
   结构变了 → 哈希变。
   反面教材就在本仓库里：大厅模板第一句是 `currentUser.role`，`currentUser`
   为 `null` 时**渲染直接抛错**，而 Vue 的渲染是 `_update(vm._render())`——
   `_render()` 一抛，`_update` 不执行，DOM **静默保留上一次成功的快照**。
   症状是"两个语义不同的状态算出同一个哈希"，一条报错都没有。
   → `test_no_two_states_share_a_hash`

2. **事件没接上 / 接错了。** 点了没反应，或者跳错页。→ `TestClickWiring`

3. **搬的过程中漏了一段。** → 哈希变（覆盖了 11 个状态的全部内容）。

覆盖面的边界（有意为之，不是遗漏）
==================================
* **只覆盖"页面间导航"这一类点击。** 会发请求的按钮（提交登录/注册、拉课堂
  列表）不在里面：那要么得造一份 mock、要么就真发请求，两条都超出本探针的职责。
  真正带网络的流程改动，本探针不管，得靠人。
* **只覆盖初始渲染，不覆盖交互中途的重渲染。** 状态是直接注入的，不是点出来的。
* **快照不含时区/区域相关的渲染**——已实测（`TZ=UTC` 与 `TZ=Asia/Kolkata`
  两次结果逐字节相同）。但这是**当前 11 个状态的巧合**，不是结构保证：
  模板里有 `new Date(report.created_at).toLocaleDateString()` 这类表达式
  （`index.html:1876`、`2897`），只要将来给某个状态填上非空的时间字段，
  哈希就会随区域漂。届时要么把区域固定住，要么把该状态排除在快照之外。
* **换机器可能算不出同样的哈希。** 探针依赖 jsdom（本机是 npm 全局装的）。
  环境缺 jsdom 时**跳过**，不判失败——它不是本仓库的依赖，装不装是使用者的选择。

对齐 `pytest.ini` 的安全约定
============================
本文件只由子进程读文件、在内存里的 jsdom 中执行：**不发 HTTP、不连数据库、
不 import `app` 包**（因此不触发 `app.core.database` 的建表副作用）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tools" / "frontend_probe.js"
BASELINE = Path(__file__).resolve().parent / "baselines" / "frontend_render.json"

# 探针的退出码约定（见 `tools/frontend_probe.js` 头部）。
EXIT_MISSING_JSDOM = 5

# 基线至少要有这么多状态/接线，否则说明它被清空了或录歪了。
MIN_STATES = 11
MIN_CLICKS = 4

TIMEOUT_SECONDS = 180


@lru_cache(maxsize=1)
def _probe_result() -> dict:
    """跑一次探针，返回它打印的 JSON。缺 node / 缺 jsdom 时 skip。

    缓存：三个用例共用一份结果，不必跑三遍 node。
    """
    assert PROBE.is_file(), f"找不到探针脚本 {PROBE}"

    node = shutil.which("node")
    if node is None:
        pytest.skip("PATH 里没有 node，前端渲染探针跳过（它不是本仓库的运行期依赖）")

    proc = subprocess.run(
        [node, str(PROBE), "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SECONDS,
        cwd=str(REPO_ROOT),
    )

    if proc.returncode == EXIT_MISSING_JSDOM:
        pytest.skip(
            "环境里没有 jsdom，前端渲染探针跳过。要跑它：npm i -g jsdom\n"
            + proc.stderr.strip()
        )

    assert proc.returncode == 0, (
        f"探针异常退出（{proc.returncode}）。\n"
        f"stdout: {proc.stdout[-2000:]}\n"
        f"stderr: {proc.stderr[-2000:]}"
    )

    return json.loads(proc.stdout)


def _baseline() -> dict:
    assert BASELINE.is_file(), (
        f"找不到渲染基线 {BASELINE}。\n"
        f"重新录制：node tools/frontend_probe.js --write-baseline"
    )
    return json.loads(BASELINE.read_text(encoding="utf-8"))


class TestBaselineIsSound:
    """先确保**基线本身**可信，再拿它当尺子。

    录歪的基线比没有基线更坏：它会把"页面没变"判成红，或者把真正的改动
    判成绿。这里挡的是"基线被清空/录成半截/录的时候页面本来就在抛错"。
    """

    def test_baseline_has_enough_coverage(self):
        baseline = _baseline()
        assert len(baseline["states"]) >= MIN_STATES, (
            f"基线只有 {len(baseline['states'])} 个状态，少于 {MIN_STATES} 个。"
            f"覆盖不足的基线给不出保证。"
        )
        assert len(baseline["clicks"]) >= MIN_CLICKS, (
            f"基线只有 {len(baseline['clicks'])} 条接线，少于 {MIN_CLICKS} 条。"
        )

    def test_baseline_states_all_rendered(self):
        """基线的每个状态都得真的渲染出了东西——不能有 `error` 条目。"""
        broken = {
            name: entry["error"]
            for name, entry in _baseline()["states"].items()
            if "error" in entry
        }
        assert not broken, (
            f"基线里这些状态是渲染失败状态下录的：{broken}。\n"
            f"基线必须在页面健康时录制，否则等于把 bug 固化成了标准。"
        )

    def test_no_two_states_share_a_hash(self):
        """**冻结检测**：语义不同的状态不该算出同一个哈希。

        两个状态哈希相同只有一种常见解释——某个状态渲染时抛了异常，
        Vue 的 `_update(vm._render())` 里 `_render()` 一抛 `_update` 就不执行，
        DOM **静默冻在上一次成功的快照**（本仓库的大厅分支在 `currentUser`
        为 null 时正是如此）。

        这条断言同时看着基线与本次运行：**基线内部**有重号说明录制时就有状态
        没渲染出来，**运行结果**有重号说明这次改动把它弄坏了。
        """
        for label, payload in (("基线", _baseline()), ("本次运行", _probe_result())):
            assert not payload.get("collisions"), (
                f"{label}里有状态算出相同哈希：{payload['collisions']}。\n"
                f"这几乎一定是渲染抛错导致 DOM 冻结（不是'两个状态长得一样'），"
                f"先去看 `tools/frontend_probe.js` 里 `currentUser` 那一段注释。"
            )


class TestRenderedStructureIsUnchanged:
    def test_every_state_renders_byte_identically(self):
        """11 个状态的渲染结果必须与基线逐个相同。

        一次性报出**全部**差异，而不是断言在第一个差异上停住——分 11 次跑
        才能看全的测试，没人会跑第二遍。
        """
        expected = _baseline()["states"]
        actual = _probe_result()["states"]

        problems: list[str] = []
        for name, want in expected.items():
            got = actual.get(name)
            if got is None:
                problems.append(f"{name}：本次运行里没有这个状态")
                continue
            if "error" in got:
                problems.append(f"{name}：渲染失败 — {got['error']}")
                continue
            if got["hash"] != want["hash"]:
                problems.append(
                    f"{name}：渲染结果变了\n"
                    f"      基线 {want['hash']}（{want['length']:,} 字符）\n"
                    f"      本次 {got['hash']}（{got['length']:,} 字符）"
                )

        assert not problems, (
            "以下状态的渲染结果与基线不符：\n  "
            + "\n  ".join(problems)
            + "\n\n若这是**有意**的界面改动，重录基线："
              "node tools/frontend_probe.js --write-baseline\n"
              "若是组件拆分，逐字节相同才是目标——变了就说明改坏了。"
        )

    def test_page_emits_no_new_warnings(self):
        """页内不该出现新的 Vue 告警/错误。

        渲染期抛出的错误往往**不会**打断上面那条哈希断言（DOM 冻住，两种状态
        撞同一个哈希——那一类由 `test_no_two_states_share_a_hash` 抓）。
        但还有一类只告警不抛错（例如 prop 类型不符），DOM 照旧，只有这条能看见。
        """
        expected = _baseline().get("notes", [])
        actual = _probe_result().get("notes", [])
        assert actual == expected, (
            f"页内告警/错误与基线不符。\n  基线：{expected}\n  本次：{actual}"
        )


class TestClickWiring:
    """事件接线：快照看不见的那一半。

    `@click="pageState='login'"` 改成子组件的 `$emit('go-login')` 之后，
    只要父组件接上了，渲染出来的 DOM **一个字节都不差**——所以这一条不能用
    快照代替，必须真的点一下再读状态。
    """

    def test_every_click_sequence_still_holds(self):
        expected = _baseline()["clicks"]
        actual = _probe_result()["clicks"]

        problems: list[str] = []
        for name in expected:
            got = actual.get(name)
            if got is None:
                problems.append(f"{name}：本次运行里没有这条接线")
            elif not got.get("ok"):
                problems.append(f"{name}：\n      " + "\n      ".join(got.get("problems", [])))

        assert not problems, (
            "以下点击接线没接上或接错了：\n  "
            + "\n  ".join(problems)
            + "\n\n（这类问题不会改变任何静态 DOM，只有点一下才露馅。）"
        )
