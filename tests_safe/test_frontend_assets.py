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
   → `TestIndexHtmlWiring::test_every_local_reference_resolves_to_a_file`

3. **下载了没接上 / 接上了没下载。** 两个方向都要挡：
   清单里有但 `index.html` 没引用 = 白下载一份进仓库；
   `index.html` 引用了但清单里没有 = 漏下载。
   → `TestIndexHtmlWiring` 的两条

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

对齐 `pytest.ini` 的安全约定：本文件**只读文件**，不起服务、不发请求、不连数据库。
"""

from __future__ import annotations

import hashlib
import json
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


class TestIndexHtmlWiring:
    def test_every_local_reference_resolves_to_a_file(self):
        """`index.html` 引用的每个 `/static/...` 都必须真实存在。

        这条挡的是**路径笔误**：404 是静默的，页面会出来，只是白屏或缺图。
        """
        missing = [
            ref for ref in sorted(_index_local_refs())
            if not (STATIC_DIR / _ref_to_relpath(ref)).is_file()
        ]
        assert not missing, (
            f"index.html 引用了这些不存在的本地文件：{missing}。\n"
            f"（相对 {STATIC_DIR} 解析。）"
        )

    def test_manifest_is_fully_referenced(self):
        """清单里的每个文件都必须被 `index.html` 引用到。

        否则就是白下载一份进了仓库——占体积、还得跟着升版本。
        （允许显式豁免：条目里写 `"unused": true`。）
        """
        referenced = {_ref_to_relpath(ref) for ref in _index_local_refs()}
        unreferenced = sorted(
            entry["path"] for entry in _entries()
            if entry["path"] not in referenced and not entry.get("unused")
        )
        assert not unreferenced, (
            f"这些文件在 SOURCES.json 里，但 index.html 一处都没引用：{unreferenced}。"
        )

    def test_every_reference_is_declared_in_manifest(self):
        """反方向：`index.html` 引用的本地文件必须都在清单里。

        缺了就说明有人手工塞了个文件进去——那种文件没有来源与版本记录，
        下次谁也不知道能不能覆盖。
        """
        declared = {entry["path"] for entry in _entries()}
        undeclared = sorted(
            _ref_to_relpath(ref) for ref in _index_local_refs()
            if _ref_to_relpath(ref) not in declared
        )
        assert not undeclared, (
            f"index.html 引用了这些本地文件，但 SOURCES.json 里没有登记：{undeclared}。"
        )
