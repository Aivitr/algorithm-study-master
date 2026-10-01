"""把 server.py 里**一段连续的顶层代码**搬到指定模块，并在原处留下再导出。

与 `extract_route_group.py` 的分工：
  * `extract_route_group.py` 搬**路由**（改 `@app.`→`@router.`，末尾自动插装配段）；
  * 本工具搬**非路由**的代码块（辅助函数、常量、类、状态），不动一个字符。

搬走后会在**原位置**留一行 `from <新模块> import (...)` 再导出，使 server.py 里
其余代码（以及 WebSocket 路由）仍能拿到它——语义与身份都不变。

安全阀（缺一个就拒绝执行，绝不半落地）：
  * 区间内的顶层定义必须与 `--expect-defs` 完全吻合（防切错边界）；
  * 新模块落地前必须 `ast.parse` 通过，且 `free_globals`（symtable 判据，见
    `tools/static_checks.py`）为空——即不存在"被全局查找却无模块级绑定"的名字；
  * 被搬的正文必须**逐字节**出现在新文件里；
  * server.py 落地后仍必须 `ast.parse` 通过。

用法：
    python tools/move_block.py --start 370 --end 665 \
        --dest app/realtime/state.py \
        --header _header_state.py \
        --expect-defs kg_counter recent_speech_cache ... \
        --reexport kg_counter recent_speech_cache ...
"""

import argparse
import ast
import sys
from pathlib import Path

try:
    from tools.static_checks import free_globals
except ImportError:  # pragma: no cover
    from static_checks import free_globals

SERVER = Path("server.py")


def die(msg: str) -> None:
    print(f"拒绝执行：{msg}", file=sys.stderr)
    raise SystemExit(1)


def node_name(n) -> str:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return n.name
    if isinstance(n, ast.Assign):
        return ",".join(t.id for t in n.targets if isinstance(t, ast.Name))
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        return "import"
    return type(n).__name__


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--dest", required=True, help="目标文件路径，如 app/realtime/state.py")
    ap.add_argument("--header", help="目标文件**首次创建**时写在最前面的头（import/文档）")
    ap.add_argument("--expect-defs", nargs="*", default=[],
                    help="区间内允许出现的顶层定义名（逐一对上才算切对了边界）")
    ap.add_argument("--reexport", nargs="*", default=[],
                    help="在 server.py 原位置再导出的名字（留空则不插入）")
    args = ap.parse_args()

    src = SERVER.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    if not (1 <= args.start <= args.end <= len(lines)):
        die(f"行号越界：{args.start}-{args.end}（文件 {len(lines)} 行）")

    # 区间必须以**顶层语句**为界：起点不能落在某个语句中间，否则切出来半截。
    starts = {n.decorator_list[0].lineno if getattr(n, "decorator_list", None) else n.lineno
              for n in tree.body}
    ends = {n.end_lineno for n in tree.body}
    if args.start not in starts:
        die(f"{args.start} 不是任何一个顶层语句的起始行（会切在半截上）。")
    if args.end not in ends:
        die(f"{args.end} 不是任何一个顶层语句的结束行（会切在半截上）。")

    inner = [n for n in tree.body
             if (n.decorator_list[0].lineno if getattr(n, "decorator_list", None) else n.lineno) >= args.start
             and n.end_lineno <= args.end]
    got = [node_name(n) for n in inner]
    # 区间内的 import 语句会跟着一起搬（它们要么是这块自己在用的，要么得由
    # 调用方补进 --reexport）。它们不是"边界切错"的信号，所以不参与比对。
    defs = [n for n in got if n != "import"]
    if sorted(defs) != sorted(args.expect_defs):
        die(f"区间内的顶层定义与 --expect-defs 不吻合。\n"
            f"  区间内实际：{defs}\n"
            f"  你声明的：  {args.expect_defs}\n"
            f"多半是 --start/--end 少切或多切了一个语句。")
    imports_in_region = got.count("import")
    if imports_in_region:
        print(f"注意：区间内含 {imports_in_region} 条 import，将随本块一起搬走"
              f"（若 server.py 别处仍需要它们，请加进 --reexport）。")

    block = "".join(lines[args.start - 1:args.end])

    dest = Path(args.dest)
    if dest.exists():
        dest_text = dest.read_text(encoding="utf-8").rstrip("\n") + "\n\n\n" + block
    else:
        if not args.header:
            die(f"{dest} 尚不存在，需要 --header 提供文件头。")
        header = Path(args.header).read_text(encoding="utf-8")
        if not header.endswith("\n\n"):
            header = header.rstrip("\n") + "\n\n"
        dest_text = header + block

    try:
        ast.parse(dest_text)
    except SyntaxError as exc:
        die(f"{dest} 无法解析（第 {exc.lineno} 行）：{exc.msg}")

    missing = free_globals(dest_text, args.dest)
    if missing:
        die(f"{args.dest} 里这些名字没有定义也没有导入：{sorted(missing)}。\n"
            f"它们原本是 server.py 的模块级全局，请补进 --header。\n"
            f"（这类缺失不会在导入时报错：执行到那条分支才 NameError，"
            f"而路由处理器会把它吞成 200 的错误响应。）")

    # 原位置换成再导出
    module_path = args.dest.replace("\\", "/")
    assert module_path.endswith(".py")
    module_path = module_path[:-3].replace("/", ".")
    if args.reexport:
        if len(args.reexport) == 1:
            repl = (f"# 阶段 5 迁至 {args.dest}，此处**再导出**（调用点保持不变）。\n"
                    f"from {module_path} import {args.reexport[0]}\n")
        else:
            names = "".join(f"    {n},\n" for n in args.reexport)
            repl = (f"# 阶段 5 迁至 {args.dest}，此处**再导出**（调用点保持不变）。\n"
                    f"from {module_path} import (\n{names})\n")
    else:
        repl = ""

    rest = "".join(lines[:args.start - 1]) + repl + "".join(lines[args.end:])
    try:
        ast.parse(rest)
    except SyntaxError as exc:
        die(f"搬走后 server.py 无法解析（第 {exc.lineno} 行）：{exc.msg}")

    # 落地前最后一道：正文必须逐字节出现在新文件里
    if block not in dest_text:
        die("被搬的正文没有逐字节出现在新文件里（有东西被改写过了）。")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(dest_text, encoding="utf-8")
    SERVER.write_text(rest, encoding="utf-8")

    print(f"已搬 {args.start}-{args.end}（{args.end - args.start + 1} 行）→ {args.dest}")
    print(f"  顶层定义：{got}")
    print(f"  server.py: {len(lines)} → {len(rest.splitlines())} 行")
    if args.reexport:
        print(f"  原位置再导出：{args.reexport}")


if __name__ == "__main__":
    main()
