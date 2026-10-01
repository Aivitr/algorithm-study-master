"""守卫：活文件里的注释与文档字符串不许再出现「开发过程的来历」。

来历指这些东西：重构的阶段编号（`阶段 5`）、设计文档的小节号（`设计文档 §4.1`）、
搬迁时的行号锚（`原 server.py:3019`）、外部账目编号（`A37` 这类）、以及
`迁至 …` 这类搬迁叙述。它们在重构当时有用，现在只剩误导——文件早就移位了。

**判据是「形状」而不是「关键词」。** 这个仓库里有几类词是正当的，必须在
匹配上放过，否则守卫会一直误报：

* `conftest.py` 自编的 `§1` / `§2` / `§3` 小节号——指向本文件内部，不是设计文档；
  真正的设计文档小节号是 `§N.M` 这种带小数点的形状；
* `本轮`（`app/routers/reports.py` 的「本轮课堂发言窗口」、
  `app/realtime/stream.py` 的「本轮音频/视频证据」）是业务词，不是「本轮重构」；
* `tools/` 下 `move_block.py`、`compare_module.py`、`split_models_3_1.py` 通篇
  讲「搬移」「逐字/逐字节比对」，那是这些工具的职责描述，不是来历。

扫描范围：`app/**`、`tools/**`、`server.py`、`conftest.py`、`static/js/app.js`、
`pcm-processor.js`。不含 `tests_safe/`（本文件在其中）、`archive/`（刻意留档的旧物）、
`static/vendor/`（第三方压缩产物）。
"""
import ast
import io
import re
import tokenize
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_WALK_DIRS = ("app", "tools")
_EXPLICIT_FILES = ("server.py", "conftest.py", "static/js/app.js", "pcm-processor.js")
_EXCLUDED_DIRS = frozenset({
    ".git", ".github", "archive", "node_modules", "venv", ".venv", "env",
    "static", "storage", "__pycache__", ".pytest_cache", ".codegraph",
    "tests_safe", "docs",
})

# 只保留在本仓库中**只可能属于开发过程叙述**的形状。
_PROVENANCE = (
    ("阶段 N（重构阶段编号）", re.compile(r"阶段\s*[0-9]")),
    ("设计文档", re.compile(r"设计文档")),
    ("设计文档式小节号 §N.M", re.compile(r"§\s*[0-9]+\.[0-9]+")),
    ("server.py 的行号锚", re.compile(r"server\.py\s*:\s*[0-9]+")),
    ("迁至（搬迁叙述）", re.compile(r"迁至")),
    ("外部账目编号 A NN（如 A37）", re.compile(r"(?<![A-Za-z0-9])A[0-9]{2}(?![0-9])")),
)


def _iter_source_files():
    seen = set()
    for rel in _WALK_DIRS:
        base = _ROOT / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in (".py", ".js"):
                continue
            if any(part in _EXCLUDED_DIRS for part in path.relative_to(_ROOT).parts):
                continue
            seen.add(path)
    for rel in _EXPLICIT_FILES:
        path = _ROOT / rel
        if path.is_file():
            seen.add(path)
    return sorted(seen)


def _blocks_of(path):
    """返回 [(行号, 文本)]，只含注释与文档字符串。"""
    src = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        blocks = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                blocks.append((tok.start[0], tok.string))
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    blocks.append((getattr(node, "lineno", 1), doc))
        return blocks
    # JS：只认「整行即注释」的行，免得把字符串里的 // 当成注释（如 https://…）。
    return [(i, line.strip()) for i, line in enumerate(src.splitlines(), 1)
            if line.strip().startswith(("//", "/*", "*", "*/"))]


def _provenance_in(text):
    return [label for label, rx in _PROVENANCE if rx.search(text)]


def test_no_live_source_keeps_the_refactor_notes():
    offenders = []
    for path in _iter_source_files():
        for lineno, text in _blocks_of(path):
            for label in _provenance_in(text):
                offenders.append(
                    f"{path.relative_to(_ROOT).as_posix()}:{lineno} [{label}] "
                    f"{text.strip().splitlines()[0][:100]}"
                )
    assert offenders == [], (
        "活文件的注释里又出现了开发过程的来历。注释只留操作须知，"
        "来历就地在注释里写清楚，别引用外部编号：\n  " + "\n  ".join(offenders)
    )


def test_the_scanner_reaches_the_files_it_is_supposed_to_guard():
    files = _iter_source_files()
    rels = {p.relative_to(_ROOT).as_posix() for p in files}
    for required in ("server.py", "conftest.py", "app/routers/auth.py",
                     "app/services/llm_service.py", "app/realtime/state.py",
                     "tools/move_block.py", "static/js/app.js"):
        assert required in rels, f"扫描范围漏了 {required}"
    assert len(files) >= 40, f"只扫到 {len(files)} 个文件，范围明显不对"

    total = sum(len(_blocks_of(p)) for p in files)
    assert total >= 500, f"只取到 {total} 块注释/文档字符串，提取逻辑可能坏了"

    # 反向：第三方产物与刻意留档的旧物不该进来。
    assert not any(r.startswith("static/vendor/") for r in rels), \
        "static/vendor 不该在扫描范围内"
    assert not any(r.startswith(("archive/", "tests_safe/")) for r in rels)


def test_the_guard_catches_an_offender_and_spares_a_lookalike():
    should_flag = {
        "课堂投票域的路由（阶段 5 从 server.py 拆出）。": "阶段 N（重构阶段编号）",
        "见设计文档 §4.1 的说明。": "设计文档",
        "§3.1 的失效模式正是静默。": "设计文档式小节号 §N.M",
        "常量原在 server.py:3019-3049。": "server.py 的行号锚",
        "阶段 5 迁至 app/core/oss.py。": "迁至（搬迁叙述）",
        "账目见 A37。": "外部账目编号 A NN（如 A37）",
    }
    for text, label in should_flag.items():
        assert label in _provenance_in(text), f"漏报了 {label}：{text!r}"

    # 每条规则都得有用例覆盖，免得某条正则写错、从此永远不匹配。
    assert set(should_flag.values()) == {label for label, _ in _PROVENANCE}

    should_spare = [
        "# 本轮无学生发言，不生成新报告。",
        "# 最近一次报告（用于截断“本轮课堂发言窗口”）",
        "先把本轮音频/视频证据暂存起来。",
        "# ---------------- §1 ORM 路径",
        "# ------------------------------------------------------- §2 直连 pymssql 路径",
        "# ------------------------------------------------------------ §3 socket 兜底",
        "把每个模型文件的正文与源文件的对应行逐字比对。",
        "被搬的正文必须逐字节出现在新文件里。",
        "搬走后会在原位置留一行 from <新模块> import ...。",
        "catch(e) { /* 静默失败 */ }",
        "# 该时间点暂无视频记录",
        # 「落地前自检」是工具自己的措辞（脚本跑的那一步检查），不是来历；
        # 一度被列进规则里，逼得 tools/extract_route_group.py 改了标题，
        # 那是守卫在管措辞而不是在抓来历，已撤掉。
        "# ---- 落地前自检：两边都必须仍是合法 Python ----",
    ]
    for text in should_spare:
        assert _provenance_in(text) == [], f"误报了：{text!r} -> {_provenance_in(text)}"
