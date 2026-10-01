"""把 server.py 中**一段连续**的路由块抽到 `app/routers/<module>.py`。

只做机械动作，判断留给人：
    切片 → `@app.` 改 `@router.` → 拼上调用者给的头 → 写模块
    → 从 server.py 删除该段 → 在末尾的「路由装配」段插入 include

头的部分（import、router 定义、模块文档）由调用者提供——那正是需要人看的地方。

用法：
    python tools/extract_route_group.py \
        --module research_runtime --start 2333 --end 2414 \
        --header _header_research_runtime.py \
        --expect-defs _as_bool _reset_research_runtime_state

若某个私有辅助只被这组路由使用、却写在 server.py 的别处，用 `--also` 一并搬：
    python tools/extract_route_group.py --module reports --start 1895 --end 2191 \
        --header _header_reports.py --expect-defs ... \
        --also "1167-1178:_select_latest_reports" \
        --also "1229-1271:_build_report_metric_maps"

安全阀：
  * 区间内只允许出现给定名字的顶层定义（多一个就报错退出，不会静默搬错东西）；
  * 区间内不得出现 `Path(__file__)`（锚点会随文件位置漂移）；
  * 区间内不得出现 `from server` / `import server`（会造成二次执行）；
  * 区间内不得含 `if __name__`；
  * 落地前新模块必须**没有任何"被全局查找却无模块级绑定"的名字**
    （用 symtable 判定，见 tools/static_checks.py）——否则要到执行那条路由才
    NameError，而外层 `try/except` 又会把它吞成 200 的 `{"status":"error"}`。
"""

import argparse
import ast
import sys
from pathlib import Path

# `tools/static_checks.py` 用的是 symtable（编译器自己的作用域分析），
# 与 AST 收集名字相比，它能正确区分"函数体内的局部导入"和"模块级绑定"。
# 作为脚本运行时 sys.path[0] 是 tools/，作为包导入时用包路径——两种都支持。
try:
    from tools.static_checks import free_globals
except ImportError:  # pragma: no cover
    from static_checks import free_globals

SERVER = Path("server.py")
ROUTERS = Path("app/routers")
DECORATORS = ("get", "post", "put", "delete", "patch", "websocket")


def die(msg: str) -> None:
    print(f"拒绝执行：{msg}", file=sys.stderr)
    raise SystemExit(1)


def top_level_nodes(tree: ast.Module, lo: int, hi: int):
    return [n for n in tree.body if lo <= n.lineno <= hi]


def node_name(n) -> str:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return n.name
    if isinstance(n, ast.Assign):
        return ",".join(t.id for t in n.targets if isinstance(t, ast.Name))
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        return "import"
    return type(n).__name__


def _server_import_table(tree: ast.Module) -> dict[str, tuple[str, str, str]]:
    """server.py 顶层 import 的 `本地名 -> (来源模块, 原名, 导入种类)` 表。

    导入种类是 `from` / `import`，用来决定新模块里怎么写回同一行。
    """
    table: dict[str, tuple[str, str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                table[alias.asname or alias.name] = (node.module, alias.name, "from")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                table[local] = (alias.name, "", "import")
    return table


def _needed_names(body_text: str) -> set[str]:
    """模块体里"被全局查找、却没有任何模块级绑定"的名字（= 必须由头提供）。

    这里**不能**用 AST 收集名字。AST 版会把函数体内的局部导入算作"本区间
    已经提供了这个名字"，于是 `def a(): from datetime import datetime` 会被
    当成全区可用，而 `def b(): datetime.now()` 照样在运行时 NameError。
    symtable 的判据与运行时一致，见 `tools/static_checks.py`。

    头的产物 `router` / `APIRouter` 由头自己提供，先扣掉。
    """
    return free_globals(body_text, "<抽取候选体>") - {"router", "APIRouter"}


def _auto_header(tree: ast.Module, body_text: str, module: str, doc: str) -> tuple[str, list[str]]:
    """按 server.py 的 import 表推出新模块的头。返回 (头文本, 需人工处理的名字)。"""
    table = _server_import_table(tree)
    try:
        needed = _needed_names(body_text)
    except SyntaxError as exc:
        die(f"抽取区间的代码无法单独解析（第 {exc.lineno} 行）：{exc.msg}。"
            f"多半是区间起点切在了一个语句中间。")

    from_imports: dict[str, list[str]] = {}
    plain_imports: set[str] = set()
    manual: list[str] = []

    for name in sorted(needed):
        entry = table.get(name)
        if entry is None:
            manual.append(name)          # server.py 内部定义（函数/类/变量）
            continue
        module_name, original, kind = entry
        if kind == "import":
            plain_imports.add(module_name)
        else:
            from_imports.setdefault(module_name, []).append(original)

    if manual:
        raise SystemExit(
            f"这些名字是 server.py **内部定义**的，工具无法自动决定怎么处理："
            f"{manual}\n"
            f"请改用 --header 手写头，并决定它们是随本组搬走、由 registry 提供，"
            f"还是需要注入。"
        )

    lines = [f'"""{doc}"""', "", "from fastapi import APIRouter"]
    for mod in sorted(plain_imports):
        lines.append(f"import {mod}")
    for mod in sorted(from_imports):
        names = ", ".join(sorted(from_imports[mod]))
        lines.append(f"from {mod} import {names}")
    lines.append("")
    lines.append("router = APIRouter()")
    return "\n".join(lines) + "\n", manual


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True, help="目标模块名（不含 .py）")
    ap.add_argument("--start", type=int, required=True, help="起始行（1-indexed，含）")
    ap.add_argument("--end", type=int, required=True, help="结束行（1-indexed，含）")
    ap.add_argument("--header", help="手写的头文件路径（与 --auto-header 二选一）")
    ap.add_argument("--auto-header", action="store_true",
                    help="按 server.py 的 import 表自动生成头")
    ap.add_argument("--doc", default="（阶段 5 从 server.py 拆出）", help="自动头的文档字符串")
    ap.add_argument("--expect-defs", nargs="*", default=[],
                    help="区间内允许带走的顶层定义名（路由函数与私有辅助）")
    ap.add_argument("--also", action="append", default=[], metavar="起-止:名字,名字",
                    help="额外一并搬走的**不连续**区间，可重复。格式 `起-止:期望的顶层定义名`"
                         "（名字用逗号分隔）。用于「某个私有辅助只被本组路由使用」的情形——"
                         "它常写在 server.py 的别处，只能单独切。")
    args = ap.parse_args()
    if not args.header and not args.auto_header:
        die("需要 --header 或 --auto-header")

    text = SERVER.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)

    if not (1 <= args.start <= args.end <= len(lines)):
        die(f"行号越界：{args.start}-{args.end}（文件 {len(lines)} 行）")

    # AST 的 `lineno` 指向 `def` 行，**不含装饰器**——而路由的地址字符串
    # 就在 `@app.post("...")` 那一行里。若从 def 行开始切，装饰器会被留在
    # server.py 里成为孤立的一行（语法上仍合法，因为紧跟后面的 def 会"接住"它，
    # 那条路由**地址变了却不报错**）。这里自动把装饰器一起带上。
    adjusted = args.start
    while adjusted > 1 and lines[adjusted - 2].lstrip().startswith("@"):
        adjusted -= 1
    if adjusted != args.start:
        print(f"（起始行由 {args.start} 前移到 {adjusted}，以带上装饰器）")
    args.start = adjusted

    block_text = "".join(lines[args.start - 1:args.end])

    def check_region(lo: int, hi: int, text: str, expect: list[str], label: str) -> list:
        """区间必须自洽：只含预期定义、无锚点漂移、无对 server 的导入。"""
        inner = top_level_nodes(tree, lo, hi)
        got = {node_name(n) for n in inner}
        unexpected = got - set(expect) - {"import"}
        if unexpected:
            die(f"{label} 区间内有未预期的顶层定义：{sorted(unexpected)}。"
                f"请确认这段是否真的该一起走，或把它加进 --expect-defs / --also 的名字里。")
        if "Path(__file__)" in text:
            die(f"{label} 区间内出现 `Path(__file__)`：搬到 app/routers/ 后它会指向 "
                f"app/routers，路径解析会静默错位。请改用 app.core.paths.PROJECT_ROOT。")
        if "from server" in text or "import server" in text:
            die(f"{label} 区间内出现对 server 的导入：在 `python server.py` 下会二次执行整个文件。")
        if "if __name__" in text:
            die(f"{label} 区间内出现 `__main__` 块，不该被搬走。")
        return inner

    # ---- 安全阀 -----------------------------------------------------------
    inner = check_region(args.start, args.end, block_text, args.expect_defs, "主")

    # 路由装饰器必须全部是 @app.*（否则可能已经搬过）
    for n in inner:
        for d in getattr(n, "decorator_list", []):
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                if d.func.attr in DECORATORS and not (
                    isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                ):
                    die(f":{n.lineno} 的路由装饰器不是 @app.*，可能已搬过。")

    # ---- 额外区间（只被本组使用的私有辅助，写在 server.py 别处）-----------
    # 这些辅助**不能**由新模块 `from server import ...` 取得（二次执行），
    # 也不能留在 server.py 里被"再导出"给新模块——因此只能随本组一起搬走。
    extra_blocks: list[str] = []
    regions: list[tuple[int, int]] = [(args.start, args.end)]
    for spec in args.also:
        region, _, names = spec.partition(":")
        lo_s, _, hi_s = region.partition("-")
        expect = [n for n in names.split(",") if n]
        try:
            lo, hi = int(lo_s), int(hi_s)
        except ValueError:
            die(f"--also 的区间无法解析：{spec!r}，应为 `起-止:名字,名字`。")
        if not (1 <= lo <= hi <= len(lines)):
            die(f"--also 区间越界：{lo}-{hi}（文件 {len(lines)} 行）。")
        if not expect:
            die(f"--also 必须写明期望的顶层定义名（防切错）：{spec!r}。")
        for r_lo, r_hi in regions:
            if not (hi < r_lo or lo > r_hi):
                die(f"--also 区间 {lo}-{hi} 与另一个待搬区间重叠。")
        text_ = "".join(lines[lo - 1:hi])
        check_region(lo, hi, text_, expect, f"--also {lo}-{hi}")
        # 与主区间一样，把紧贴其上的装饰器带上（辅助函数通常没有，但保持一致）
        while lo > 1 and lines[lo - 2].lstrip().startswith("@"):
            lo -= 1
        extra_blocks.append("".join(lines[lo - 1:hi]))
        regions.append((lo, hi))

    if extra_blocks:
        print(f"另搬 {len(extra_blocks)} 个额外区间：" +
              "、".join(f"{lo}-{hi}" for lo, hi in regions[1:]))

    # ---- 写模块 -----------------------------------------------------------
    # 先做 `@app.` → `@router.` 的改写：自动头需要据此判断依赖（改完之后
    # 装饰器里的 `app` 已不是外部名字，`router` 则记为由头提供）。
    body = block_text.replace("@app.", "@router.")
    for block in extra_blocks:
        # 额外区间接在正文之后。它们都是模块级 def/class，Python 在**调用时**
        # 才解析名字，因此"定义在使用之后"不影响行为。
        body = body.rstrip("\n") + "\n\n\n" + block
    before_text = block_text + "".join(extra_blocks)
    if args.auto_header:
        header, _ = _auto_header(tree, body, args.module, args.doc)
    else:
        header = Path(args.header).read_text(encoding="utf-8")
    if not header.endswith("\n\n"):
        header = header.rstrip("\n") + "\n\n"

    # ---- 从 server.py 删除并装配 ------------------------------------------
    # 多个区间时要**从后往前**删，否则先删前面的会让后面区间的行号整体前移。
    out = list(lines)
    for lo, hi in sorted(regions, reverse=True):
        del out[lo - 1:hi]
    rest = "".join(out)
    marker = 'if __name__ == "__main__":'
    if rest.count(marker) != 1:
        die("找不到唯一的 `__main__` 块，装配段无从插入。")
    assembly = (
        f"from app.routers.{args.module} import router as {args.module}_router\n"
        f"\napp.include_router({args.module}_router)\n\n\n"
    )
    rest = rest.replace(marker, assembly + marker)

    # ---- 落地前自检：两边都必须仍是合法 Python --------------------------
    # 装饰器被留成孤儿行时语法上仍然合法（它会"接住"紧随其后的 def），
    # 因此不报错，只是那条路由的地址变了；落地前用 ast.parse 必须过一遍。
    try:
        ast.parse(rest)
    except SyntaxError as exc:
        die(f"抽走后 server.py 无法解析（第 {exc.lineno} 行）：{exc.msg}")
    module_text = header + body
    try:
        ast.parse(module_text)
    except SyntaxError as exc:
        die(f"新模块 app/routers/{args.module}.py 无法解析（第 {exc.lineno} 行）：{exc.msg}")

    # 装饰器一条都不能少：切走的 `@app.*` 条数必须等于搬来的 `@router.*` 条数。
    # 少了就说明有装饰器被留在了 server.py 里（孤儿行，见上方注释）。
    n_before = before_text.count("@app.")
    n_after = body.count("@router.")
    if n_before != n_after or n_after == 0:
        die(f"装饰器数量对不上：切走 {n_before} 个 @app.*，搬来 {n_after} 个 @router.*。"
            f"多半是装饰器没被一起带走。")

    # ---- 头是否把所有需要的名字都提供了 ----------------------------------
    # 少一个 import 的后果是**运行到那条路由时才 NameError**，且会被处理器吞成
    # 200 的 {"status":"error"}，测试看不见（路由契约测试只查路由表，不执行
    # 处理器）。因此静态核对整个新模块：任何"被全局查找、却无模块级绑定"的名字
    # 都必须为零。
    missing = free_globals(module_text, f"app/routers/{args.module}.py")
    if missing:
        die(f"新模块里这些名字没有定义也没有导入：{sorted(missing)}。\n"
            f"它们多半原本是 server.py 的模块级全局（如 `import re`、"
            f"`from datetime import datetime`）。\n"
            f"补进 --header 的头里，或改用 --auto-header。\n"
            f"（这类缺失不会在测试里暴露：契约测试只检查路由表，不执行处理器；"
            f"而处理器会把 NameError 吞成 200 的错误响应。）")

    ROUTERS.mkdir(exist_ok=True)
    (ROUTERS / f"{args.module}.py").write_text(module_text, encoding="utf-8")
    SERVER.write_text(rest, encoding="utf-8")

    print(f"已抽出 {args.start}-{args.end}（{args.end - args.start + 1} 行）"
          f"→ app/routers/{args.module}.py")
    print(f"server.py: {len(lines)} → {len(rest.splitlines())} 行")


if __name__ == "__main__":
    main()
