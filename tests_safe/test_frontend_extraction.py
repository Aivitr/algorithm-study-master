"""阶段 7（前端拆分）的守卫：内联源码外移之后，把等价性钉住。

背景
====
`index.html` 原本把两块**源码**内联在页面里：

| 位置 | 内容 | 行数 |
|---|---|---|
| 第 15–2000 行 `<style>` | 全站样式（含 `@import` 与 `@keyframes`） | 1986 |
| 第 5229–11297 行 `<script>` | 整个 Vue 根实例 + axios 配置 | 6069 |

阶段 7 把 `<style>` 外移为 `static/css/app.css`、`<script>` 外移为
`static/js/app.js`，仍由既有的 `/static` 挂载伺服。

**这是 ②b 里"可证明"的那一半。** ②b 的另一半（组件拆分）不是搬迁：
它要改结构，设计文档给的验收标准是"功能逐项对照通过"——那得在浏览器里逐项点，
本地没有这个能力，因而**无法证明没有改变行为**。所以本阶段只做逐字节可证明的部分，
另一半登记为待决事项（见 `docs/待验收事项.md` A27）。

为什么"外移"值得一套守卫
======================
内联与外链的语义差别其实只有一条，但它能静默毁掉整页：

1. **取不到就白屏。** 内联的脚本不可能"加载失败"；外链的会。`/static` 挂载写错、
   文件名笔误、文件没进版本库——三种情况下 HTML 结构完好、控制台一行 404、
   **整页功能全无**。这正是本文件开头反复说的那类"开发机上看得出来、但没人会去看"。
   → `TestServedByApp::test_first_party_asset_is_served_byte_identical`

2. **顺序变了就崩，且崩得莫名其妙。** `app.js` 用的是 `Vue` / `axios` /
   `echarts` / `marked` / `AgoraRTC` 这几个**全局**，由 `<head>` 里的 vendor
   脚本提供。把 app.js 的 `<script>` 挪到它们之前，页面立刻 `Vue is not defined`，
   而 HTML 看上去毫无问题。
   → `test_app_script_loads_after_vendor_scripts`

3. **搬的过程里漏了几行。** 外移最典型的事故是"复制过去、手滑漏掉中间一段"。
   两端各钉一句，加上根实例的**结构断言**，截断与漏行都能抓到。
   → `TestExtractedFiles::test_app_css_keeps_both_ends` 等

对齐 `pytest.ini` 的安全约定：本文件只读文件；走 HTTP 的那几条用
`tests_safe/conftest.py` 的隔离 app（SQLite + 禁网），不碰任何外部服务。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
STATIC_DIR = REPO_ROOT / "static"
URL_PREFIX = "/static"

APP_CSS_REL = "css/app.css"
APP_JS_REL = "js/app.js"

# `<head>` 里提供全局的那 5 个脚本。顺序即依赖顺序（app.js 必须排在全部之后）。
VENDOR_SCRIPTS = (
    "/static/vendor/vue-2.6.14.js",
    "/static/vendor/axios-1.20.0.min.js",
    "/static/vendor/echarts-5.4.0.min.js",
    "/static/vendor/marked-15.0.12.min.js",
    "/static/vendor/agora/AgoraRTC_N-4.22.0.js",
)

_SCRIPT_SRC_RE = re.compile(r"""<script[^>]*\bsrc=["']([^"']+)["']""")

# 带内容的内联 `<script>`（即没有 src 的那种）。`<script src=...></script>` 不算。
_INLINE_SCRIPT_RE = re.compile(r"""<script(?![^>]*\bsrc=)[^>]*>""")

_KEY_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*(?=[:(])")

# 正则字面量只可能出现在这些记号之后；否则 `/` 是除号。
# （第一版按缩进数的扫描脚本就是被 `/{2,}/` 这类字面量带偏的——见 A26 的核查留痕。）
_REGEX_CAN_FOLLOW = set("(,=:[!&|?{};+-*%~^<>")

# 根实例第一层的键。**末尾那个重复的 `watch` 是已知状态，不是笔误**：
# 对象字面量里后键整体覆盖前键，所以第 5730 行那个 watch 从未生效。
# 详见 `docs/待验收事项.md` A26。将来若决定合并或删除，**必须同时改这张表与那条记录**，
# 这正是把它钉在这里的意义——不让它被静默"顺手修掉"。
_EXPECTED_ROOT_KEYS = (
    "el",
    "data",
    "computed",
    "watch",
    "methods",
    "beforeDestroy",
    "watch",
)


def _index_html() -> str:
    assert INDEX_HTML.is_file(), f"找不到 {INDEX_HTML}"
    return INDEX_HTML.read_text(encoding="utf-8")


def _first_party(relpath: str) -> Path:
    return STATIC_DIR / relpath


def _app_css() -> str:
    path = _first_party(APP_CSS_REL)
    assert path.is_file(), f"找不到 {path}"
    return path.read_text(encoding="utf-8")


def _app_js() -> str:
    path = _first_party(APP_JS_REL)
    assert path.is_file(), f"找不到 {path}"
    return path.read_text(encoding="utf-8")


def _root_option_keys(js: str) -> list[tuple[str, int]]:
    """`new Vue({...})` 那个对象字面量**第一层**的键，按出现顺序。

    判据是**花括号深度**，不是缩进——重复键这种事必须用语法事实判定，
    缩进只是约定。本仓库正是靠它发现 `watch` 被写了两次（A26），
    而按缩进数的第一版脚本与没处理正则字面量的第二版都给出过错答案。

    深度 1 = 根实例自己的选项层；键一旦进入值对象内部，深度 ≥ 2。
    必须正确跳过字符串、模板串、行注释、块注释、正则字面量，
    否则任何一个含 `{`/`}` 的字面量都会把深度带偏。
    """
    i = js.index("new Vue(")
    depth = 0
    keys: list[tuple[str, int]] = []
    prev = ""
    size = len(js)

    while i < size:
        char = js[i]

        if char == "/" and i + 1 < size and js[i + 1] == "/":  # 行注释
            found = js.find("\n", i)
            i = size if found < 0 else found
            continue

        if char == "/" and i + 1 < size and js[i + 1] == "*":  # 块注释
            found = js.find("*/", i)
            i = size if found < 0 else found + 2
            continue

        if char == "/" and (prev == "" or prev in _REGEX_CAN_FOLLOW):  # 正则字面量
            i += 1
            in_class = False
            while i < size:
                inner = js[i]
                if inner == "\\":
                    i += 2
                    continue
                if inner == "\n":  # 正则不跨行，防御
                    break
                if inner == "[":
                    in_class = True
                elif inner == "]":
                    in_class = False
                elif inner == "/" and not in_class:
                    i += 1
                    break
                i += 1
            prev = "/"
            continue

        if char in "\"'`":  # 字符串 / 模板串
            quote = char
            i += 1
            while i < size:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == quote:
                    i += 1
                    break
                i += 1
            prev = quote
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1:
            match = _KEY_RE.match(js, i)
            if match and (i == 0 or js[i - 1] in " \t\n\r,{};"):
                keys.append((match.group(1), js.count("\n", 0, i) + 1))
                i = match.end()
                prev = match.group(1)[-1]
                continue

        if not char.isspace():
            prev = char
        i += 1

    return keys


# --------------------------------------------------------------------------
# 1. index.html 里不该再有任何内联源码
# --------------------------------------------------------------------------


class TestNoInlineSource:
    def test_index_html_has_no_style_block(self):
        """`<style>` 整块都得走。留下任何一个，样式就有两处定义源。"""
        html = _index_html()
        assert "<style" not in html, (
            "`index.html` 里还有内联 `<style>`。阶段 7 已把它整块外移为 "
            f"`{URL_PREFIX}/{APP_CSS_REL}`；留下残块会让样式的定义源变成两处。"
        )

    def test_index_html_has_no_inline_script_block(self):
        """允许 `<script src=...></script>`，不允许带内容的 `<script>`。"""
        html = _index_html()
        found = _INLINE_SCRIPT_RE.search(html)
        assert found is None, (
            f"`index.html` 里还有内联 `<script>`（{found.group(0)!r} 起）。"
            f"阶段 7 已把它整块外移为 `{URL_PREFIX}/{APP_JS_REL}`。"
        )

    def test_index_html_points_at_the_extracted_files(self):
        html = _index_html()
        assert f'href="{URL_PREFIX}/{APP_CSS_REL}"' in html, (
            f"`index.html` 没有引用 `{URL_PREFIX}/{APP_CSS_REL}`"
        )
        assert f'src="{URL_PREFIX}/{APP_JS_REL}"' in html, (
            f"`index.html` 没有引用 `{URL_PREFIX}/{APP_JS_REL}`"
        )


# --------------------------------------------------------------------------
# 2. 外移出来的两份文件，两端都在（截断守卫）
# --------------------------------------------------------------------------


class TestExtractedFiles:
    def test_app_css_keeps_both_ends(self):
        """首行与末段各钉一句。

        外移的典型事故是"复制过去、漏掉中间一段"。只断言"文件存在"抓不到它；
        两端各钉一句，加上 `@keyframes` 这类只出现一次的规则，能覆盖大多数漏行。
        """
        css = _app_css()
        assert css.lstrip().startswith("[v-cloak]"), (
            f"`{APP_CSS_REL}` 的开头不是预期内容：{css[:80]!r}"
        )
        assert "@keyframes topicSlideDown" in css, (
            f"`{APP_CSS_REL}` 里找不到原 `<style>` 末段的 `@keyframes topicSlideDown`，"
            f"外移可能漏掉了尾部。"
        )

    def test_app_js_keeps_both_ends(self):
        js = _app_js()
        assert js.startswith("// 配置axios"), (
            f"`{APP_JS_REL}` 的开头不是预期内容：{js[:80]!r}"
        )
        assert js.rstrip().endswith("})"), (
            f"`{APP_JS_REL}` 的结尾不是 `new Vue({...})` 的收尾，"
            f"外移可能漏掉了尾部。实际结尾：{js.rstrip()[-80:]!r}"
        )

    def test_app_js_defines_the_root_instance_unchanged(self):
        """根实例第一层的键，必须与搬迁前逐一相同。

        这一条同时起两个作用：
        * 抓"搬的过程中漏了一段"——少一个键就红；
        * 把 A26 那个**重复的 `watch`** 变成显式的、有名字的已知状态。
          将来真要合并或删掉它，红一次，然后你被迫同时改这张表与那条记录。
        """
        found = [name for name, _ in _root_option_keys(_app_js())]
        assert found == list(_EXPECTED_ROOT_KEYS), (
            f"根实例第一层的键与搬迁前不一致。\n"
            f"  预期：{list(_EXPECTED_ROOT_KEYS)}\n"
            f"  实际：{found}\n"
            f"（末尾重复的 `watch` 是 A26 记录的已知状态，见 docs/待验收事项.md。）"
        )


# --------------------------------------------------------------------------
# 3. 加载顺序
# --------------------------------------------------------------------------


class TestLoadOrder:
    def test_app_script_loads_after_vendor_scripts(self):
        """`app.js` 依赖 vendor 提供的全局，必须排在最后一个。

        顺序错了不会报 404，而是运行时 `Vue is not defined`——
        HTML 看着完全正常，属于最难从源码上定位的一类。
        """
        sources = _SCRIPT_SRC_RE.findall(_index_html())
        assert sources, "`index.html` 里一个带 src 的 `<script>` 都没有"

        app_url = f"{URL_PREFIX}/{APP_JS_REL}"
        assert sources[-1] == app_url, (
            f"最后一个脚本不是 `{app_url}`，实际顺序：{sources}。\n"
            f"`app.js` 用到 Vue / axios / echarts / marked / AgoraRTC 这几个全局，"
            f"排在 vendor 之前会直接 `Vue is not defined`。"
        )
        assert set(sources[:-1]) == set(VENDOR_SCRIPTS), (
            f"vendor 脚本清单与预期不符。\n"
            f"  预期：{sorted(VENDOR_SCRIPTS)}\n"
            f"  实际：{sorted(sources[:-1])}"
        )


# --------------------------------------------------------------------------
# 4. 真的经 app 伺服出去了吗
# --------------------------------------------------------------------------


class TestServedByApp:
    """磁盘上有文件 ≠ 浏览器拿得到。

    内联改写外链之后，这一条从"锦上添花"变成了**必需**：内联的内容不可能取不到，
    外链的取不到就是整页白屏。走 `tests_safe/conftest.py` 的隔离 app
    （SQLite + 禁网），不发真实请求、不连任何外部服务。
    """

    @pytest.mark.parametrize("relpath", [APP_CSS_REL, APP_JS_REL])
    def test_first_party_asset_is_served_byte_identical(self, relpath, client):
        path = _first_party(relpath)
        assert path.is_file(), f"找不到 {path}"

        url = f"{URL_PREFIX}/{relpath}"
        response = client.get(url)
        assert response.status_code == 200, (
            f"{url} 返回 HTTP {response.status_code}。"
            f"文件在磁盘上却发不出去时，浏览器只会看到 404 与白屏。"
        )
        assert response.content == path.read_bytes(), (
            f"{url} 送出的字节与磁盘上的 `{relpath}` 不一致"
        )

    def test_index_html_no_longer_carries_the_source(self, client):
        """反方向：页面本身应当**明显变小**。

        外移的全部意义就是把 8000 多行源码从 HTML 里拿出去。若 `GET /` 还是
        600 KB 量级，说明外移没接上。
        """
        response = client.get("/")
        assert response.status_code == 200
        assert len(response.content) < 300_000, (
            f"`GET /` 仍返回 {len(response.content):,} 字节（外移前约 615,940）。"
            f"源码没有真正移出 `index.html`。"
        )
