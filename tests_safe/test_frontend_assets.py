"""前端外部依赖本地化的守卫（阶段 6）。

背景
----
`index.html` 原本从 5 个外部源拉 23 个资源（7 个库 + 1 个字体源 + 15 张图）。
阶段 6 把它们全部落到 `static/` 下，由 FastAPI 以 `/static` 挂载伺服。

本文件防的是**本地化做了一半**的四类故障。四类的共同点是
**在有外网的开发机上全都看不出来**，所以只能靠断言挡：

1. **半途而废。** 23 个引用里只改了 20 个，剩下 3 个仍指向 CDN。
   开发机有外网，页面照常渲染；部署到断外网的环境才表现为
   "Vue 加载了、图标没加载、图裂了"这种最难定位的组合故障。
   → `TestNoExternalReferences`

2. **路径笔误。** `/static/vendor/vue-2.6.14.js` 写成 `vue-2.6.14.js.old`。
   404 是**静默**的：浏览器只在控制台留一行，页面照样出来，只是白屏。
   → `TestReachability::test_every_reachable_asset_exists`

3. **下载了没接上 / 接上了没下载。** 两个方向都要挡，且必须**跟着 CSS 的
   `url()` 走**：Font Awesome 的 webfonts 与 Inter 的 woff2 不在 `index.html`
   里，只在那两份 CSS 里。只看 `index.html` 会把它们误判成"白下载"。
   走不到的清单项 = 真白下载；引用到却没登记的 = 来源不明。
   → `TestReachability` 的后两条

4. **文件被截断。** 下载中途断开，落一个半截的 `vue.js`。
   浏览器报的是 `Unexpected end of input`——**症状离原因很远**。
   SHA256 直接抓到，且能在 diff 里看出是哪一次下载坏的。
   → `TestVendoredFilesMatchManifest`

为什么 SHA256 记在 `SOURCES.json` 而不是写死在测试里
--------------------------------------------------
本仓库反复吃过"两份清单不会同时改、分叉后不报错"的亏
（见 `app/core/oss.py` 文件头、`tools/split_requirements.py` 文件头）。
清单只留**一处**（`static/vendor/SOURCES.json`，由生成脚本产出），
测试只负责核对现实与它是否一致。

5. **文件在磁盘上，但没被伺服出去。** 上面四条读的都是文件系统——而磁盘上有文件
   ≠ 应用会把它送出去。`/static` 挂载的目录参数写错、挂载点被别的路由抢先匹配、
   或者干脆忘了 `app.mount(...)`，这三种情况下前四条**全部为绿**，
   而浏览器拿到的是 404。→ `TestServedByApp`

对齐 `pytest.ini` 的安全约定：本文件只读文件；`TestServedByApp` 走的是
`tests_safe/conftest.py` 的隔离 app（SQLite + 禁网），**不碰任何外部服务**。
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"

# 本地资源的挂载点与目录。`server.py` 里的 `app.mount("/static", ...)` 指着它。
URL_PREFIX = "/static"
STATIC_DIR = REPO_ROOT / "static"
MANIFEST = STATIC_DIR / "vendor" / "SOURCES.json"

# `index.html` 曾经引用过的全部外部源。本地化完成后，一个都不该再出现。
#
# 这张名单是**穷举**过的实测结果，不是举例——`grep -o "https://[a-z.]*" index.html`
# 当时恰好给出这 5 个（外加 15 张图同属 unsplash）。多写一个无害，
# 少写一个就可能漏掉某条真实引用。
_FORBIDDEN_HOSTS = (
    "cdn.jsdelivr.net",          # vue / axios / echarts / marked / tailwind
    "cdnjs.cloudflare.com",      # font-awesome
    "fonts.googleapis.com",      # Inter 的 CSS
    "fonts.gstatic.com",         # Inter 的 woff2（CSS 内部指向它）
    "download.agora.io",         # AgoraRTC
    "images.unsplash.com",       # 15 张落地页配图
)

# `static/` 下从此也有了**第一方**源码（不是下载来的第三方件）。
#
# `SOURCES.json` 的含义是"下载物的来源与校验清单"——第一方文件没有来源 URL、
# 没有上游版本，硬塞进去只会让那份清单的含义变浑浊（`test_every_entry_has_provenance`
# 会立刻要求给它编一个 url 与 version）。
#
# 这里**显式列出**，而不是把断言放宽成"只查 vendor/"：显式名单能让
# "新增了一个第一方文件却忘了登记"在评审里看得见。详见 `docs/待验收事项.md` A27。
_FIRST_PARTY = {
    "css/app.css",  # index.html 原 <style> 块（阶段 7 外移）
    "js/app.js",    # index.html 原 <script> 块（阶段 7 外移）
}

_ABSOLUTE_URL_RE = re.compile(r"https?://([^/\"'\s)>]+)")

# 会真正发起网络请求的引用形式。只取这四种：
#   <script src> / <link href> / CSS 的 @import url() / <img src>
# 不用 `所有含 src= 的标签`——`:src="xxx"` 这类 Vue 动态绑定是模板表达式，
# 不是静态路径，混进来只会制造噪声。
_REF_PATTERNS = (
    re.compile(r"""<script[^>]*\ssrc=["']([^"']+)["']"""),
    re.compile(r"""<link[^>]*\shref=["']([^"']+)["']"""),
    re.compile(r"""@import\s+url\(\s*['"]?([^'")]+)"""),
    re.compile(r"""<img[^>]*\ssrc=["']([^"']+)["']"""),
)

# CSS 正文里的 url(...)。与落地脚本用的是同一个形状。
_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


def _index_html() -> str:
    assert INDEX_HTML.is_file(), f"找不到 {INDEX_HTML}"
    return INDEX_HTML.read_text(encoding="utf-8")


def _absolute_hosts() -> set[str]:
    return set(_ABSOLUTE_URL_RE.findall(_index_html()))


def _index_local_refs() -> set[str]:
    """`index.html` 里指向本地 `/static` 的路径（原样，带前缀）。"""
    refs: set[str] = set()
    html = _index_html()
    for pattern in _REF_PATTERNS:
        for raw in pattern.findall(html):
            if raw.startswith(URL_PREFIX + "/"):
                refs.add(raw)
    return refs


def _ref_to_relpath(ref: str) -> str:
    """`/static/vendor/vue.js` → `vendor/vue.js`（相对 `static/`）。"""
    return ref[len(URL_PREFIX) + 1:]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest() -> dict:
    assert MANIFEST.is_file(), (
        f"找不到 {MANIFEST}。它是本地化清单的唯一一处定义"
        f"（来源 URL、版本、SHA256 都在里面）。"
    )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _entries() -> list[dict]:
    return _manifest()["files"]


# --------------------------------------------------------------------------
# 1. 不能有任何残留的外部引用
# --------------------------------------------------------------------------


class TestNoExternalReferences:
    def test_index_html_exists(self):
        assert INDEX_HTML.is_file()

    def test_no_absolute_urls_remain(self):
        """本地化完成后，`index.html` 里不该再有任何绝对 URL。

        `index.html` 不发起任何 API 调用（那些都在 JS 里用相对路径），
        所以"绝对 URL 集合为空"是个干净、无例外的判据。
        真需要留一个例外时，请在此显式登记——不要放宽成 `startswith('https://api')`。
        """
        hosts = _absolute_hosts()
        assert not hosts, (
            "index.html 里仍有绝对 URL 指向外部主机：\n  "
            + "\n  ".join(sorted(hosts))
            + "\n阶段 6 的目标是断外网也能用；这些引用会让部署环境在 CDN 不可达时"
            "缺组件（且开发机有外网，看不出来）。"
        )

    @pytest.mark.parametrize("host", _FORBIDDEN_HOSTS)
    def test_specific_cdn_is_gone(self, host):
        """按主机逐条点名。

        与上一条的区别：上一条给的是"还剩哪些主机"的集合，
        本参数化直接指出"`images.unsplash.com` 还在"——定位成本差很多。
        """
        hosts = _absolute_hosts()
        assert host not in hosts, (
            f"index.html 仍在引用 {host}。"
            f"当前残留的外部主机：{sorted(hosts)}"
        )


# --------------------------------------------------------------------------
# 2. 落地的文件必须与清单逐字节相符
# --------------------------------------------------------------------------


class TestVendoredFilesMatchManifest:
    def test_manifest_exists_and_parses(self):
        manifest = _manifest()
        assert manifest.get("files"), "SOURCES.json 里没有任何条目"

    def test_manifest_paths_are_unique(self):
        paths = [entry["path"] for entry in _entries()]
        duplicates = sorted({p for p in paths if paths.count(p) > 1})
        assert not duplicates, f"SOURCES.json 里有重复条目：{duplicates}"

    def test_manifest_is_lf_only(self):
        """清单必须是纯 LF——它的**自证方式**依赖这一点。

        本仓库用"重跑一次生成脚本，看仓库有没有变"来证明清单是算出来的、不是抄的。
        而 `Path.write_text` 默认做平台换行转换：在 Windows 上写出的清单是 CRLF，
        入库时被 `.gitattributes` 的 `* text=auto eol=lf` 归一成 LF，
        于是**每次在 Windows 上重跑都会留下一条纯换行的假 diff**。
        假 diff 本身无害，有害的是它让上面那条自证失效，且失效得悄无声息。

        （这个坑是实打实踩到的：第一版清单就是这样进了一次提交。）
        """
        raw = MANIFEST.read_bytes()
        assert b"\r" not in raw, (
            f"{MANIFEST.name} 里出现了 CR（{raw.count(b'\\r')} 个）。"
            f"生成脚本的 write_manifest 需要 newline=\"\\n\"。"
        )

    def test_every_entry_has_provenance(self):
        """每个条目都要有来源 URL 与版本——"这个文件是哪来的"必须可回答。

        没有它，下次要升级 Vue 时就只能靠猜：仓库里躺着一个 `vue.js`，
        没人知道它是 2.6.14 还是被人手改过。
        """
        incomplete = [
            entry.get("path")
            for entry in _entries()
            if not entry.get("url") or not entry.get("version")
        ]
        assert not incomplete, (
            f"这些条目缺 来源 URL 或 版本：{incomplete}。"
            f"本地化把 CDN 的「随时可查」换成了「仓库里的一坨二进制」，"
            f"provenance 是这笔交易的必要补偿。"
        )

    def test_files_exist_and_match_hash(self):
        """逐个核对存在性、非空、SHA256、字节数。

        合并成一条而不是参数化：需要同时报告所有坏文件（一次修完），
        而不是修一个跑一次。
        """
        problems: list[str] = []
        for entry in _entries():
            path = STATIC_DIR / entry["path"]
            if not path.is_file():
                problems.append(f"{entry['path']}：文件不存在")
                continue

            raw = path.read_bytes()
            if not raw:
                problems.append(f"{entry['path']}：文件是空的（下载中断？）")
                continue

            actual = _sha256(path)
            if entry.get("sha256") and actual != entry["sha256"]:
                problems.append(
                    f"{entry['path']}：SHA256 不符\n"
                    f"      清单 {entry['sha256']}\n"
                    f"      实际 {actual}"
                )
            if entry.get("bytes") is not None and len(raw) != entry["bytes"]:
                problems.append(
                    f"{entry['path']}：字节数不符（清单 {entry['bytes']}，实际 {len(raw)}）"
                )

        assert not problems, (
            "以下本地文件与 SOURCES.json 不一致：\n  "
            + "\n  ".join(problems)
            + "\n（截断的文件在浏览器里报 `Unexpected end of input`，症状离原因很远，"
            "所以在这里挡。）"
        )


# --------------------------------------------------------------------------
# 3. index.html 与清单必须**互相**覆盖
# --------------------------------------------------------------------------


def _reachable_assets() -> dict[str, str]:
    """从 `index.html` 出发，跟着 CSS 的 `url()` 往下走，返回 {路径: 谁引用的}。

    为什么要跟着走，而不是只看 `index.html`
    --------------------------------------
    Font Awesome 的 webfonts 与 Inter 的 woff2 **不在 `index.html` 里**——
    它们只在那两份 CSS 的 `url()` 里。只看 `index.html` 的话，这 15 个字体
    会被误判成"下载了没用上"。而它们恰恰是本阶段最容易漏、漏了症状又最隐蔽的
    那一半：图标静默变空框、字体静默回退到系统字体，页面**照常渲染**。

    （这条模型最初写错了，测试红过一次。红得对——错的是模型。）
    """
    queue: list[tuple[str, str]] = [
        (_ref_to_relpath(ref), "index.html") for ref in _index_local_refs()
    ]
    seen: dict[str, str] = {}

    while queue:
        relpath, source = queue.pop()
        if relpath in seen:
            continue
        seen[relpath] = source

        if not relpath.endswith(".css"):
            continue
        css_path = STATIC_DIR / relpath
        if not css_path.is_file():
            continue  # 缺失由"必须存在"那条断言报，这里不重复报

        base = posixpath.dirname(relpath)
        for match in _CSS_URL_RE.finditer(
            css_path.read_text(encoding="utf-8", errors="replace")
        ):
            ref = match.group(2)
            if ref.startswith(("data:", "http://", "https://", "#")):
                continue
            if ref.startswith(URL_PREFIX + "/"):
                # 站内绝对路径，以挂载点为根——**不能**按 CSS 所在目录解析。
                #
                # 这条分支此前不存在，因为那时 `@import url('/static/vendor/inter/inter.css')`
                # 写在 `index.html` 里，由 `_REF_PATTERNS` 的 `@import` 那条式子接走，
                # 根本走不到这里。阶段 7 把它连同整个 `<style>` 块搬进了
                # `static/css/app.css`，CSS 分支这才第一次遇到它——
                # 若按相对路径解析，会得到 `css/static/vendor/inter/inter.css`，
                # 于是"被引用的文件不存在"报红，而真实原因只是解析基准错了。
                queue.append((_ref_to_relpath(ref), relpath))
                continue
            queue.append((posixpath.normpath(posixpath.join(base, ref)), relpath))

    return seen


class TestReachability:
    def test_every_reachable_asset_exists(self):
        """浏览器会请求的每一个本地文件都必须真实存在。

        这条挡的是**路径笔误**：404 是静默的，页面会出来，只是白屏或缺图。
        """
        missing = [
            path for path in sorted(_reachable_assets())
            if not (STATIC_DIR / path).is_file()
        ]
        assert not missing, (
            f"这些被引用到的本地文件不存在：{missing}。\n"
            f"（相对 {STATIC_DIR} 解析。）"
        )

    def test_every_reachable_asset_is_declared(self):
        """反方向：被引用到的文件必须都在清单里。

        缺了就说明有人手工塞了个文件进去——那种文件没有来源与版本记录，
        下次谁也不知道能不能覆盖。

        第一方源码是例外，且**只能是显式登记的那几个**（见 `_FIRST_PARTY`）：
        它们本来就该留在仓库里由人维护，谈不上"来源与版本"。
        """
        declared = {entry["path"] for entry in _entries()}
        undeclared = sorted(
            path
            for path in _reachable_assets()
            if path not in declared and path not in _FIRST_PARTY
        )
        assert not undeclared, (
            f"这些本地文件被引用了，但既不在 SOURCES.json 里、"
            f"也不在 _FIRST_PARTY 名单里：{undeclared}。\n"
            f"若是第一方源码，请加进 `_FIRST_PARTY` 并说明它的由来。"
        )

    def test_nothing_is_downloaded_but_unused(self):
        """清单里的每一项都必须**可达**。

        否则就是白下载一份进仓库——占体积、还得跟着升版本。
        "可达"含传递引用（见 `_reachable_assets`），所以字体文件不该在这里出现。
        （允许显式豁免：条目里写 `"unused": true`。）
        """
        reachable = set(_reachable_assets())
        unreferenced = sorted(
            entry["path"] for entry in _entries()
            if entry["path"] not in reachable and not entry.get("unused")
        )
        assert not unreferenced, (
            f"这些文件在 SOURCES.json 里，但从 index.html 出发走不到：{unreferenced}。"
        )


# --------------------------------------------------------------------------
# 5. 真的经 app 伺服出去了吗
# --------------------------------------------------------------------------


class TestServedByApp:
    """端到端：从 HTTP 入口拿到的字节，必须与磁盘上那份逐字节相同。

    前面四条全部读文件系统。磁盘上有文件 ≠ 应用会把它送出去：
    `/static` 挂载的目录参数指错、挂载点被别的路由抢先匹配、或者
    `app.mount(...)` 被误删——这三种情况下前面**全都为绿**，
    而浏览器拿到的是 404（正是本文件开头说的那类"有外网就看不出来"）。

    这一条走 `tests_safe/conftest.py` 的隔离 app：SQLite + 禁网，
    不发真实请求、不连任何外部服务。注意它验证的是**挂载行为**，
    不是 CDN 是否可达——后者本地无从验证，只能靠 `TestNoExternalReferences`
    保证页面压根不再去外面要东西。
    """

    def test_every_manifest_file_is_served_byte_identical(self, client):
        problems: list[str] = []
        for entry in _entries():
            url = f"{URL_PREFIX}/{entry['path']}"
            response = client.get(url)
            if response.status_code != 200:
                problems.append(f"{url}：HTTP {response.status_code}")
                continue
            digest = hashlib.sha256(response.content).hexdigest()
            if digest != entry["sha256"]:
                problems.append(
                    f"{url}：送出的内容与磁盘不符"
                    f"（清单 {entry['sha256'][:12]}，实际 {digest[:12]}）"
                )
        assert not problems, (
            "以下本地资源无法经 /static 正确伺服：\n  "
            + "\n  ".join(problems)
            + "\n（文件在磁盘上却发不出去，浏览器只会看到 404 与白屏。）"
        )

    def test_index_html_is_served(self, client):
        """`GET /` 就是那份 index.html——上面所有本地路径都挂在它身上。"""
        response = client.get("/")
        assert response.status_code == 200
        assert b"/static/" in response.content, (
            "`GET /` 返回的内容里找不到任何 /static/ 引用。"
            "要么它是另一份文件，要么本地化没接上。"
        )
