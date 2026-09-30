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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True, help="目标模块名（不含 .py）")
    ap.add_argument("--start", type=int, required=True, help="起始行（1-indexed，含）")
    ap.add_argument("--end", type=int, required=True, help="结束行（1-indexed，含）")
    ap.add_argument("--header", required=True, help="头文件路径")
    ap.add_argument("--expect-defs", nargs="*", default=[],
                    help="区间内允许带走的顶层定义名（路由函数与私有辅助）")
    args = ap.parse_args()

    text = SERVER.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)

    if not (1 <= args.start <= args.end <= len(lines)):
        die(f"行号越界：{args.start}-{args.end}（文件 {len(lines)} 行）")

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
    header = Path(args.header).read_text(encoding="utf-8")
    if not header.endswith("\n\n"):
        header = header.rstrip("\n") + "\n\n"
    body = block_text.replace("@app.", "@router.")
    ROUTERS.mkdir(exist_ok=True)
    (ROUTERS / f"{args.module}.py").write_text(header + body, encoding="utf-8")

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
    SERVER.write_text(rest, encoding="utf-8")

    print(f"已抽出 {args.start}-{args.end}（{args.end - args.start + 1} 行）"
          f"→ app/routers/{args.module}.py")
    print(f"server.py: {len(lines)} → {len(rest.splitlines())} 行")


if __name__ == "__main__":
    main()
