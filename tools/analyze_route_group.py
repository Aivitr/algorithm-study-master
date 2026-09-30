"""给一组路由，报出它们的处理器、行跨度、以及需要的外部名字。

用途：从 server.py 拆路由时，先看清"这组要带走什么、依赖什么"。
只做静态分析，不导入 server（导入会触发导入期副作用）。
"""
import ast
import sys
from pathlib import Path

SERVER = Path("server.py")


def main(patterns: list[str]) -> None:
    src = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()

    routes = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in ("get", "post", "put", "delete", "patch", "websocket")):
                path = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else "?"
                if any(p in path for p in patterns):
                    routes.append((path, d.func.attr, node))

    if not routes:
        print("没匹配到路由"); return

    routes.sort(key=lambda r: r[2].lineno)
    print(f"匹配 {len(routes)} 条路由：")
    for path, m, n in routes:
        print(f"  {m.upper():9} {path:45} {n.name:35} 行 {n.lineno}-{n.end_lineno} ({n.end_lineno-n.lineno+1})")

    lo, hi = routes[0][2].lineno, routes[-1][2].end_lineno
    print(f"\n跨度：{lo}-{hi}（{hi-lo+1} 行）")
    print(f"跨度内是否连续无夹杂：", all(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.Expr))
        for n in tree.body if lo <= n.lineno <= hi))

    # 全局依赖
    import builtins
    lib = set(dir(builtins))
    used, local = set(), set()
    for _, _, n in routes:
        for a in ast.walk(n):
            if isinstance(a, ast.Name):
                (used if isinstance(a.ctx, ast.Load) else local).add(a.id)
            if isinstance(a, ast.arg): local.add(a.arg)
            if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)): local.add(a.name); local |= {x.arg for x in a.args.args}
            if isinstance(a, ast.ExceptHandler) and a.name: local.add(a.name)
            if isinstance(a, (ast.Import, ast.ImportFrom)):
                for al in a.names: local.add(al.asname or al.name.split(".")[0])
    need = sorted(used - local - lib)
    print("\n需要的外部名字（模块级）：")
    for name in need:
        # 在 server.py 顶层找定义
        kind = "?"
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name: kind = f"server.py:{node.lineno} def"
            elif isinstance(node, ast.ClassDef) and node.name == name: kind = f"server.py:{node.lineno} class"
            elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets): kind = f"server.py:{node.lineno} assign"
            elif isinstance(node, (ast.Import, ast.ImportFrom)) and any((al.asname or al.name.split('.')[0]) == name for al in node.names): kind = f"server.py:{node.lineno} import"
        # 私有辅助函数的引用次数
        refs = src.count(name) if kind == "?" else None
        print(f"  {name:35} {kind}")

    print("\n跨度内出现的所有顶层定义（会被一并带走）：")
    for node in tree.body:
        if lo <= node.lineno <= hi and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.Import, ast.ImportFrom)):
            tail = f" -> {ast.unparse(node)[:60]}" if isinstance(node, ast.Assign) else ""
            print(f"  :{node.lineno} {type(node).__name__} {getattr(node,'name', ast.unparse(node)[:50] if isinstance(node,ast.Assign) else '')}{tail}")


if __name__ == "__main__":
    main(sys.argv[1:])
