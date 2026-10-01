"""把 `index.html` 的外部资源抓到 `static/` 下，并产出 `SOURCES.json`。

为什么要有这个脚本（而不是手工 curl 一遍）
------------------------------------------
手工下载会留下一个**无法回答的问题**：仓库里那个 `vue.js` 是官方 2.6.14 的原文，
还是谁手改过一行的版本？`SOURCES.json` 记下来源 URL、版本、SHA256、字节数，
把"随时可查"从 CDN 搬回仓库里。脚本本身则保证这份记录**是算出来的、不是抄的**。

`tests_safe/test_frontend_assets.py` 反过来核对现实与它是否一致。

为什么 CSS 要特殊处理
--------------------
`all.min.css`（Font Awesome）与 Google Fonts 返回的 CSS 里还有 `url(...)`
指向字体文件。只抓 CSS 不抓字体，页面会**静默**变成空框图标 / 回退字体。
所以样式表走 `fetch_stylesheet()`：把 `url()` 指的东西一并抓下来，按需改写相对路径。

Font Awesome 的 CSS 用的是 `../webfonts/xxx` 这种**相对**路径，只要本地目录
层级与原站一致就不必改写；Google Fonts 用的是 `fonts.gstatic.com` 的
**绝对** URL，必须改写成同目录下的文件名。

为什么 jsdelivr 要走镜像
----------------------
**实测：本机 Python 抓 `cdn.jsdelivr.net` 必然握手失败**（`ConnectionResetError
[WinError 10054]`，非偶发），而同一时刻 `curl` 取同一 URL 返回 200，其余 CDN
（cdnjs / fonts.googleapis.cn / download.agora.io / images.unsplash.com）用
Python 均正常。所以这不是"外网不通"，是 jsdelivr 单独拒绝这一族 TLS 指纹。

对策是换运输路线，不是换内容：npmmirror（阿里云的 npm 镜像）的 `/files/`
端点回的是发布包里的原件。清单里 `url` 仍记权威地址，另加 `fetched_from` 记
这一份实际从哪条路来——**换源必须留痕**，否则下一个人看到 `url` 写 jsdelivr
会以为真是从那儿下的。

用法
----
    py -3.12 tools/vendor_frontend.py            # 抓取并重写 SOURCES.json
    py -3.12 tools/vendor_frontend.py --check    # 只校验，不下载（CI/测试友好）

本脚本**只发 HTTP GET、不碰数据库**，可以放心在开发机上跑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"
MANIFEST = STATIC_DIR / "vendor" / "SOURCES.json"

# 抓 Google Fonts 时必须带一个现代浏览器 UA：不带的话它返回的是
# 兼容老浏览器的 TTF，体积大好几倍，而且拿不到 woff2 的分片。
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 单文件资源：(相对 static/ 的落点, 来源 URL, 版本)
STANDALONE: tuple[tuple[str, str, str], ...] = (
    (
        "vendor/vue-2.6.14.js",
        "https://cdn.jsdelivr.net/npm/vue@2.6.14/dist/vue.js",
        "2.6.14",
    ),
    (
        "vendor/axios-1.20.0.min.js",
        "https://cdn.jsdelivr.net/npm/axios@1.20.0/dist/axios.min.js",
        "1.20.0",
    ),
    (
        "vendor/echarts-5.4.0.min.js",
        "https://cdn.jsdelivr.net/npm/echarts@5.4.0/dist/echarts.min.js",
        "5.4.0",
    ),
    (
        "vendor/marked-15.0.12.min.js",
        "https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js",
        "15.0.12",
    ),
    (
        "vendor/tailwind-2.2.19.min.css",
        "https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css",
        "2.2.19",
    ),
    (
        "vendor/agora/AgoraRTC_N-4.22.0.js",
        "https://download.agora.io/sdk/release/AgoraRTC_N-4.22.0.js",
        "4.22.0",
    ),
)

# 需要连带抓 `url()` 所指文件的样式表。落点刻意保持与原站相同的目录层级，
# 这样 `../webfonts/...` 这类相对引用不必改写。
STYLESHEETS: tuple[tuple[str, str, str], ...] = (
    (
        "vendor/fontawesome/6.0.0/css/all.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css",
        "6.0.0",
    ),
    # 用 `.cn`：**实测本机到 `fonts.googleapis.com` 稳定不可达**（curl 返回 000），
    # 而 `fonts.googleapis.cn` 可达且返回的是**同一份 CSS**（同样的 unicode-range
    # 分片、同样的字体名，只是 url() 指向 `fonts.gstatic.cn`）——同一套字体对象，
    # 换了一条能走通的路。
    (
        "vendor/inter/inter.css",
        "https://fonts.googleapis.cn/css2?family=Inter:wght@400;500;600;700;800&display=swap",
        "Inter v20（Google Fonts，2026-10-01 实测）",
    ),
)

# 落地页配图。这些是 `index.html` 里 <img src> 的原样 URL；
# 去重后 15 条对应 13 张照片。
IMAGES: tuple[str, ...] = (
    "https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=800&h=420&fit=crop",
    "https://images.unsplash.com/photo-1497633762265-9d179a990aa6?w=720&h=1080&fit=crop",
    "https://images.unsplash.com/photo-1509062522246-3755977927d7?w=720&h=900&fit=crop",
    "https://images.unsplash.com/photo-1511452885600-a3d2c9148a31?w=720&h=980&fit=crop",
    "https://images.unsplash.com/photo-1513258496099-48168024aec0?w=720&h=980&fit=crop",
    "https://images.unsplash.com/photo-1516321497487-e288fb19713f?w=900&h=560&fit=crop",
    "https://images.unsplash.com/photo-1517048676732-d65bc937f952?w=1600&h=900&fit=crop",
    "https://images.unsplash.com/photo-1518186285589-2f7649de83e0?w=800&h=420&fit=crop",
    "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=800&h=1000&fit=crop",
    "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=1200&h=760&fit=crop",
    "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=800&h=420&fit=crop",
    "https://images.unsplash.com/photo-1523240795612-9a054b0db644?w=800&h=1000&fit=crop",
    "https://images.unsplash.com/photo-1523240795612-9a054b0db644?w=900&h=560&fit=crop",
    "https://images.unsplash.com/photo-1524995997946-a1c2e315a42f?w=720&h=1080&fit=crop",
    "https://images.unsplash.com/photo-1588072432836-e10032774350?w=720&h=900&fit=crop",
)

_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")
_PHOTO_ID_RE = re.compile(r"/photo-([0-9a-z-]+)\?")
_SIZE_RE = re.compile(r"[?&]w=(\d+)[^&]*&h=(\d+)")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

# jsdelivr 的 npm 路径 → npmmirror 的 `/files/` 路径。取正则而不是逐条列表：
# 这个改写对**任何** jsdelivr 资源都成立，往 STANDALONE 加包时不必同步维护第二张表。
_JSDELIVR_RE = re.compile(
    r"^https://cdn\.jsdelivr\.net/npm/(?P<pkg>[^@/]+)@(?P<version>[^/]+)/(?P<path>.+)$"
)


def _mirror_url(url: str) -> str | None:
    """返回一个 URL 的镜像地址；没有镜像则返回 None。

    没有镜像的资源（cdnjs、`fonts.googleapis.cn`、agora、unsplash）**不做任何
    猜测性改写**——猜错会静默换成另一个文件，比失败糟糕得多。
    """
    match = _JSDELIVR_RE.match(url)
    if not match:
        return None
    return (
        f"https://registry.npmmirror.com/{match['pkg']}/{match['version']}"
        f"/files/{match['path']}"
    )


def _fetch(url: str, *, timeout: int = 60, attempts: int = 6) -> tuple[bytes, str]:
    """GET 一个 URL，返回 `(内容, 实际取到的地址)`。

    地址可能与入参不同：jsdelivr 会 RST 掉 Python 的 TLS 握手，此时自动改走
    npmmirror（见 `_mirror_url`）。所以必须把**实际地址**交回调用方，
    由它写进清单的 `fetched_from`——换源留痕，不留在日志里就等于没留。

    候选按**轮次交替**试，而不是先试完权威源再试镜像：jsdelivr 的拒绝是即时的
    （握手期 RST，不是超时），串行重试会让本机每次都先白等完整轮退避才落到镜像上。

    重试是必需的：同一 URL 会时通时断，没有重试的话一次抖动就会让脚本半路死掉，
    而**已经写下去的文件看起来是完整的**。真正的完整性由 SHA256 兜底。
    """
    candidates = [url]
    mirror = _mirror_url(url)
    if mirror:
        candidates.append(mirror)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        for candidate in candidates:
            request = urllib.request.Request(candidate, headers={"User-Agent": _UA})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read(), candidate
            except Exception as exc:  # noqa: BLE001 — 网络异常种类多，一律重试
                last_error = exc
        if attempt < attempts:
            time.sleep(2.0 * attempt)

    tried = "\n  ".join(candidates)
    hint = "" if mirror else "\n该资源没有登记镜像，只能等它恢复。"
    raise RuntimeError(
        f"抓取失败（每条各试了 {attempts} 次）：\n  {tried}{hint}"
    ) from last_error


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# 按「相对 static/ 的路径」去重。这不是优化，是**正确性**：
# Google 把 Inter 当作**可变字体**发布，5 个字重共用同一批 woff2，
# 所以那份 CSS 里 35 个 url() 只指向 7 个不同的文件。不去重的话清单里会有
# 35 条、其中 28 条是重复路径——`test_frontend_assets.py` 会直接判红。
_CACHE: dict[str, dict] = {}


def _entry(relpath: str, url: str, actual_url: str, version: str, raw: bytes) -> dict:
    """组装一条清单条目。

    `url` 是**权威地址**（这个文件是什么）；`fetched_from` 只在两条路不一致时
    才写，记这一份实际从哪来。两个字段都用全路径而不是"镜像名"，
    是为了让清单在没有本脚本的地方也能单独读懂。
    """
    entry = {
        "path": relpath, "url": url, "version": version,
        "sha256": _sha256(raw), "bytes": len(raw),
    }
    if actual_url != url:
        entry["fetched_from"] = actual_url
    return entry


def _describe(entry: dict) -> str:
    """一行运行日志。走了镜像会显式标出来——静默换源等于没记。"""
    line = f"  {entry['path']}  ({entry['bytes']:,} B)"
    if "fetched_from" in entry:
        line += "  ← 镜像"
    return line


def _stage(relpath: str, url: str, version: str) -> dict:
    """抓下来 → 落盘 → 记一条清单条目。同一路径只做一次。"""
    # 归一化：Font Awesome 的 CSS 用 `../webfonts/x` 这种相对引用，
    # 直接拼出来是 `.../css/../webfonts/x`——文件系统认，但字符串比对不认，
    # 会让"清单里的路径"和"从 CSS 解析出的路径"永远对不上。
    relpath = posixpath.normpath(relpath)
    if relpath in _CACHE:
        return _CACHE[relpath]

    raw, actual_url = _fetch(url)
    target = STATIC_DIR / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)

    entry = _entry(relpath, url, actual_url, version, raw)
    _CACHE[relpath] = entry
    print(_describe(entry))
    return entry


def _image_relpath(url: str) -> str:
    """给一张 unsplash 图取一个**能看出是哪张、哪种裁剪**的文件名。

    不用 URL 原样的 query 串做名字：Windows 文件名里不能有 `?`、`&`、`=`，
    且那样的名字在目录列表里完全看不出内容。
    """
    photo = _PHOTO_ID_RE.search(url)
    size = _SIZE_RE.search(url)
    if not photo or not size:
        raise ValueError(f"看不懂的 unsplash URL：{url}")
    return f"img/{photo.group(1)}__{size.group(1)}x{size.group(2)}.jpg"


def _local_name_for_absolute(url: str) -> str:
    """把绝对 URL 映射成本地文件名（只取末段，去掉可能有的 query）。"""
    tail = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return _SAFE_NAME_RE.sub("_", tail) or "asset"


def _normalize_url(url: str) -> str:
    """收掉 URL 路径里多余的 `../`，让清单里的来源地址是人能读的。

    坑：**不能直接 `posixpath.normpath(整个 URL)`** —— 它会把 `https://`
    里的双斜杠压成单斜杠（`https:/cdn...`），得到一个打不开的地址。
    所以先把 scheme+host 摘出来，只归一化路径部分。
    """
    scheme, _, rest = url.partition("://")
    if not rest:
        return url
    host, _, path = rest.partition("/")
    return f"{scheme}://{host}/{posixpath.normpath(path)}"


def fetch_stylesheet(local_relpath: str, url: str, version: str) -> list[dict]:
    """抓一张样式表，连同它 `url()` 指的字体文件，返回清单条目。

    两种引用分别处理：

      * **相对路径**（Font Awesome 的 `../webfonts/fa-solid-900.woff2`）：
        按原层级落到本地，CSS 正文**一字不改**。
      * **绝对路径**（Google Fonts 指向 `fonts.gstatic.com`）：
        抓到与本 CSS 同级的目录，并把正文里的绝对 URL 改写成本地文件名。

    后半条是必需的：不改写的话，本地这份 CSS 依然会去公网拉字体，
    本地化就只做了一半——而这一半在开发机上完全看不出来。
    """
    css_bytes, actual_url = _fetch(url)
    text = css_bytes.decode("utf-8")

    base_dir = local_relpath.rsplit("/", 1)[0]  # 例：vendor/fontawesome/6.0.0/css

    def replace(match: re.Match[str]) -> str:
        quote, ref = match.group(1), match.group(2)
        if ref.startswith("data:"):
            return match.group(0)

        if ref.startswith(("http://", "https://")):
            name = _local_name_for_absolute(ref)
            _stage(f"{base_dir}/{name}", ref, version)
            return f"url({quote}{name}{quote})"

        # 相对引用：按 CSS 自己所在的远程目录解析，落到对应的本地目录
        remote = _normalize_url(f"{url.rsplit('/', 1)[0]}/{ref}")
        _stage(f"{base_dir}/{ref}", remote, version)
        return match.group(0)

    rewritten = _CSS_URL_RE.sub(replace, text)

    # CSS 正文本身也要落盘。它的 sha256 算的是**改写后**的本地版本——
    # 那才是仓库里实际躺着的那份。
    final = rewritten.encode("utf-8")
    target = STATIC_DIR / local_relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(final)
    entry = _entry(local_relpath, url, actual_url, version, final)
    _CACHE[local_relpath] = entry
    print(_describe(entry))


def build_manifest() -> list[dict]:
    _CACHE.clear()

    for local_relpath, url, version in STANDALONE:
        _stage(local_relpath, url, version)

    for local_relpath, url, version in STYLESHEETS:
        fetch_stylesheet(local_relpath, url, version)

    for url in IMAGES:
        photo = _PHOTO_ID_RE.search(url)
        _stage(_image_relpath(url), url, photo.group(1) if photo else "unsplash")

    return sorted(_CACHE.values(), key=lambda entry: entry["path"])


def write_manifest(entries: list[dict]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    # `newline="\n"` 是必需的：`Path.write_text` 默认做**平台换行转换**，会与
    # .gitattributes 的 `* text=auto eol=lf` 冲突，使 Windows 上重跑必然产生一条
    # **纯换行的假 diff**，让本脚本"重跑一次看仓库有没有变"的自证失效。
    MANIFEST.write_text(
        json.dumps(
            {
                "note": (
                    "本文件由 tools/vendor_frontend.py 生成，请勿手改。"
                    "它记录 static/ 下每个本地资源的三件事：从哪来、什么版本、"
                    "内容对不对（SHA256）。改动资源请改脚本里的清单后重跑。"
                ),
                "files": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def check() -> int:
    """核对现有文件与清单是否一致（不下载）。"""
    if not MANIFEST.is_file():
        print(f"清单不存在：{MANIFEST}（先跑一次不带 --check 的）", file=sys.stderr)
        return 1

    problems = []
    for entry in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]:
        path = STATIC_DIR / entry["path"]
        if not path.is_file():
            problems.append(f"{entry['path']}：文件不存在")
            continue
        raw = path.read_bytes()
        actual = _sha256(raw)
        if actual != entry["sha256"]:
            problems.append(f"{entry['path']}：SHA256 不符（实际 {actual}）")
        if len(raw) != entry["bytes"]:
            problems.append(f"{entry['path']}：字节数不符（实际 {len(raw)}）")

    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{'不一致' if problems else '一致'}：{len(problems)} 处问题")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="只校验，不下载")
    args = parser.parse_args()

    if args.check:
        return check()

    print(f"抓取到 {STATIC_DIR} …")
    entries = build_manifest()
    write_manifest(entries)
    total = sum(entry["bytes"] for entry in entries)
    print(f"\n共 {len(entries)} 个文件，{total / 1_048_576:.1f} MiB → {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
