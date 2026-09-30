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

安全阀：
  * 区间内只允许出现给定名字的顶层定义（多一个就报错退出，不会静默搬错东西）；
  * 区间内不得出现 `Path(__file__)`（锚点会随文件位置漂移）；
  * 区间内不得出现 `from server` / `import server`（会造成二次执行）；
  * 区间内不得含 `if __name__`。
"""

import argparse
import ast
import sys
from pathlib import Path

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


def _needed_names(tree: ast.Module, inner: list) -> set[str]:
    """区间内用到的、不在本区间定义的名字（= 得由新模块自己提供）。"""
    import builtins

    lib = set(dir(builtins))
    defined, used = set(), set()
    for n in inner:
        # 装饰器 `@app.get(...)` 里的 `app` 是路由挂载点，改写成 @router. 后
        # 就不再需要了，因此**不把装饰器算作函数体的依赖**。
        deco_nodes = {id(d) for deco in getattr(n, "decorator_list", []) for d in ast.walk(deco)}
        for a in ast.walk(n):
            if id(a) in deco_nodes:
                continue
            if isinstance(a, ast.Name):
                (used if isinstance(a.ctx, ast.Load) else defined).add(a.id)
            if isinstance(a, ast.arg):
                defined.add(a.arg)
            if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(a.name)
                defined |= {x.arg for x in a.args.args}
            if isinstance(a, ast.ExceptHandler) and a.name:
                defined.add(a.name)
            if isinstance(a, (ast.Import, ast.ImportFrom)):
                for al in a.names:
                    defined.add(al.asname or al.name.split(".")[0])
    return (used - defined - lib)


def _auto_header(tree: ast.Module, inner: list, module: str, doc: str) -> tuple[str, list[str]]:
    """按 server.py 的 import 表推出新模块的头。返回 (头文本, 需人工处理的名字)。"""
    table = _server_import_table(tree)
    needed = _needed_names(tree, inner)

    # 本区间内自己定义的名字（含被一并带走的私有辅助）不需要导入
    local_defs = set()
    for n in inner:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_defs.add(n.name)

    from_imports: dict[str, list[str]] = {}
    plain_imports: set[str] = set()
    manual: list[str] = []

    for name in sorted(needed - local_defs):
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
    # 于是那条路由**地址变了却不报错**）。这里自动把装饰器一起带上。
    adjusted = args.start
    while adjusted > 1 and lines[adjusted - 2].lstrip().startswith("@"):
        adjusted -= 1
    if adjusted != args.start:
        print(f"（起始行由 {args.start} 前移到 {adjusted}，以带上装饰器）")
    args.start = adjusted

    block_text = "".join(lines[args.start - 1:args.end])

    # ---- 安全阀 -----------------------------------------------------------
    inner = top_level_nodes(tree, args.start, args.end)
    got = {node_name(n) for n in inner}
    unexpected = got - set(args.expect_defs) - {"import"}
    if unexpected:
        die(f"区间内有未预期的顶层定义：{sorted(unexpected)}。"
            f"请确认这段是否真的是自洽的一组，或把它加进 --expect-defs。")

    if "Path(__file__)" in block_text:
        die("区间内出现 `Path(__file__)`：搬到 app/routers/ 后它会指向 app/routers，"
            "路径解析会静默错位。请改用 app.core.paths.PROJECT_ROOT。")
    if "from server" in block_text or "import server" in block_text:
        die("区间内出现对 server 的导入：在 `python server.py` 下会二次执行整个文件。")
    if "if __name__" in block_text:
        die("区间内出现 `__main__` 块，不该被搬走。")

    # 路由装饰器必须全部是 @app.*（否则可能已经搬过）
    for n in inner:
        for d in getattr(n, "decorator_list", []):
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                if d.func.attr in DECORATORS and not (
                    isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                ):
                    die(f":{n.lineno} 的路由装饰器不是 @app.*，可能已搬过。")

    # ---- 写模块 -----------------------------------------------------------
    if args.auto_header:
        header, _ = _auto_header(tree, inner, args.module, args.doc)
    else:
        header = Path(args.header).read_text(encoding="utf-8")
    if not header.endswith("\n\n"):
        header = header.rstrip("\n") + "\n\n"
    body = block_text.replace("@app.", "@router.")

    # ---- 从 server.py 删除并装配 ------------------------------------------
    rest = "".join(lines[:args.start - 1] + lines[args.end:])
    marker = 'if __name__ == "__main__":'
    if rest.count(marker) != 1:
        die("找不到唯一的 `__main__` 块，装配段无从插入。")
    assembly = (
        f"from app.routers.{args.module} import router as {args.module}_router\n"
        f"\napp.include_router({args.module}_router)\n\n\n"
    )
    rest = rest.replace(marker, assembly + marker)

    # ---- 落地前自检：两边都必须仍是合法 Python --------------------------
    # 这一条是补的：本脚本初版从 AST 的 def 行（不含装饰器）开始切，把
    # `@app.post("/api/cast-vote")` 留在了 server.py 里当孤儿——语法上仍然
    # 合法（它会"接住"紧随其后的 def），因此**不报错**，只是那条路由的地址
    # 变了。静态解析立即能发现这类残骸，所以落地前必须过一遍。
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
    n_before = block_text.count("@app.")
    n_after = body.count("@router.")
    if n_before != n_after or n_after == 0:
        die(f"装饰器数量对不上：切走 {n_before} 个 @app.*，搬来 {n_after} 个 @router.*。"
            f"多半是装饰器没被一起带走。")

    # ---- 头是否把所有需要的名字都提供了 ----------------------------------
    # 少一个 import 的后果是**运行到那条路由时才 NameError**，而路由契约测试
    # 只看路由表、根本不执行处理器——静态解析也发现不了。所以在这里静态核对：
    # 新模块顶层绑定的名字（import/def/assign）必须覆盖区间内用到的全部名字。
    module_tree = ast.parse(module_text)
    bound: set[str] = set()
    for node in module_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound |= {(a.asname or a.name.split(".")[0]) for a in node.names}
    missing = _needed_names(tree, inner) - bound
    if missing:
        die(f"新模块缺少这些名字的导入：{sorted(missing)}。\n"
            f"补进 --header 的头里，或改用 --auto-header。\n"
            f"（缺 import 不会在测试里暴露：契约测试只检查路由表，不执行处理器。）")

    ROUTERS.mkdir(exist_ok=True)
    (ROUTERS / f"{args.module}.py").write_text(module_text, encoding="utf-8")
    SERVER.write_text(rest, encoding="utf-8")

    print(f"已抽出 {args.start}-{args.end}（{args.end - args.start + 1} 行）"
          f"→ app/routers/{args.module}.py")
    print(f"server.py: {len(lines)} → {len(rest.splitlines())} 行")


if __name__ == "__main__":
    main()
