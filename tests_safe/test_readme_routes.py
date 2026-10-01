"""README 的接口清单不许和代码漂移（2026-10-01 加）。

README 里那张按域分组的接口表是**人手写的第二份路由清单**——本仓库已经有一份
机器枚举的 `docs/route-inventory.md`（从运行中的 app 枚举 `app.routes`，不是读源码
手抄）。两份同时存在就有漂移风险，而 README 恰恰是**外人最先读到的那一份**：
它一旦落后，读到的人按它去调接口，拿到的是 404。

"文档悄悄腐化"在本仓库不是假想敌：
  * README 的项目结构树整棵是错的（列的七个文件全都早已不在根目录）；
  * `.env` 的说明与 `.env.example` 对不上（`test_env_docs.py` 就是为此而生）；
  * 本文件左侧那条链——`.dockerignore` 的裸文件名模式在文件搬家后悄然失效。

所以这次不靠自觉：README 与源码之间的相等关系由本文件钉住。

判据两头都不能空
----------------
源侧抽不到路由（正则被改坏、装饰器换了写法如 `@router.api_route`）与 README 侧
抽不到表（表格被删或格式改了）都会让"集合相等"**平凡成立**——空集等于空集。
本仓库在"空输入 == 通过"上栽过不止一次（`tools/schema_snapshot.py` 的文件头
专门写着"务必先确认两份都非空"），故两侧各有一条下限断言。

源码侧为什么用 AST 而不是正则
------------------------------
本文件的第一版源码侧就是正则，它**当场红了**——但红错了对象：`unrouted.py:20`
那两行注释里写着

    而全仓库没有任何 `@app.post("/api/upload-report-template")`

正则把**这句解释**原样读了进来，于是断言去要求 README 补一条**根本不存在**的
接口。这是本仓库的已知陷阱：`test_paths_anchor.py::_path_file_uses` 的注释里
写着同一条教训，两小时前刚被抄进那份守卫——然后在这里又踩了一次。
文本匹配分不清"说明"与"声明"；AST 分得清。故源码侧一律走 AST。
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

# 路由可能出现在这三处。`server.py` 与 `app/realtime/` 目前**一条也不贡献**
# （实测 59 条全在 `app/routers/`），但仍然扫它们：将来有人图省事在入口文件里
# 挂一条 `@app.get`，那条就会绕过本断言。
_ROUTE_SOURCES = (
    *sorted((REPO_ROOT / "app" / "routers").glob("*.py")),
    *sorted((REPO_ROOT / "app" / "realtime").glob("*.py")),
    REPO_ROOT / "server.py",
)

# 认这些接收者：`@router.get(...)` / `@app.websocket(...)`
_ROUTE_OWNERS = frozenset({"router", "app"})
_ROUTE_DECORATORS = frozenset(
    {"get", "post", "put", "delete", "patch", "websocket", "api_route"}
)

# README 表格行：`| `GET` | `/api/x` | 说明 |`（方法列的反引号可有可无）
_README_ROW = re.compile(
    r"^\|\s*`?(GET|POST|PUT|DELETE|PATCH|WS)`?\s*\|\s*`([^`]+)`\s*\|",
    re.MULTILINE,
)

# 源码侧下限。当前实测正好 59（GET 28 / POST 26 / DELETE 2 / WS 3），与设计文档
# 冻结的"59 个接口"吻合。留出余量是为了让**新增路由**不必改这里，但抽取一旦
# 整体失效，它会立刻跌到 0 而报红。
_MIN_EXPECTED_ROUTES = 50


def _normalize(method: str, path: str) -> tuple[str, str]:
    method = method.upper()
    if method == "WEBSOCKET":
        method = "WS"
    return method, path


def _routes_in_one_file(path: Path) -> set[tuple[str, str]]:
    """从单个模块的 AST 里取路由。注释与字符串里的同形文本一概不算。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()

    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not isinstance(func, ast.Attribute) or func.attr not in _ROUTE_DECORATORS:
                continue
            if not isinstance(func.value, ast.Name) or func.value.id not in _ROUTE_OWNERS:
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            route = dec.args[0].value
            if isinstance(route, str):
                found.add(_normalize(func.attr, route))
    return found


def _routes_in_source() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in _ROUTE_SOURCES:
        if path.is_file():
            found |= _routes_in_one_file(path)
    return found


def _routes_in_readme() -> set[tuple[str, str]]:
    if not README.is_file():
        return set()
    return {_normalize(m, p) for m, p in _README_ROW.findall(
        README.read_text(encoding="utf-8"))}


def test_the_source_side_actually_found_routes():
    """`test_the_readme_lists_every_route` 的反向断言（见模块 docstring 末段）。"""
    found = _routes_in_source()
    assert len(found) >= _MIN_EXPECTED_ROUTES, (
        f"只从源码里抽出 {len(found)} 条路由（预期 ≥ {_MIN_EXPECTED_ROUTES}）。"
        f"多半是装饰器的写法变了（`_ROUTE_OWNERS` / `_ROUTE_DECORATORS` 没跟上）——"
        f"此时那条相等断言会**平凡通过**，所以在这里先拦一道。"
    )


def test_the_readme_side_actually_found_routes():
    """同上，另一头：表格被删掉也会让相等断言平凡通过。"""
    found = _routes_in_readme()
    assert len(found) >= _MIN_EXPECTED_ROUTES, (
        f"README 里只解析出 {len(found)} 条接口。表格是不是被删了，"
        f"或格式不再是 `| `方法` | `/路径` |` ？"
    )


def test_the_readme_lists_every_route():
    """README 的接口表与源码逐条一致——一个不多、一个不少。

    多一个同样报红：README 里写着一条实际不存在的接口，读到的人会拿到 404，
    而那比"少写一条"更伤人。
    """
    source = _routes_in_source()
    readme = _routes_in_readme()

    missing = sorted(source - readme)
    extra = sorted(readme - source)

    assert not missing and not extra, (
        f"README 的接口表和源码对不上。\n"
        f"  源码里有、README 没写（{len(missing)} 条）：{missing}\n"
        f"  README 写了、源码里没有（{len(extra)} 条）：{extra}\n"
        f"  共 源码 {len(source)} 条 / README {len(readme)} 条。\n"
        f"改完接口记得同步 README 那张按域分组的表；"
        f"分类与基线覆盖见 docs/route-inventory.md。"
    )


@pytest.mark.parametrize("doc", ["docs/route-inventory.md"])
def test_the_other_inventory_document_agrees_with_the_source(doc):
    """机器枚举的那一份也不许漂——它和 README 是同一个真相的两个投影。

    与上面分开断言，是为了让报错落在**该改的那一份**上：如果只有它红了，
    说明源码动过而这棵树没跟上；如果只有 README 红了，说明读者最先看到的那份
    落后了。两者同时红，才说明源码本身变了。
    """
    path = REPO_ROOT / doc
    if not path.is_file():
        pytest.skip(f"{doc} 不存在")

    rows = re.findall(
        r"^\|\s*(GET|POST|PUT|DELETE|PATCH|WS)\s*\|\s*`([^`]+)`",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    documented = {_normalize(m, p) for m, p in rows}
    assert documented, f"{doc} 里一条路由都没解析出来——格式变了？"

    source = _routes_in_source()
    assert documented == source, (
        f"{doc} 与源码对不上。\n"
        f"  只在源码：{sorted(source - documented)}\n"
        f"  只在文档：{sorted(documented - source)}"
    )
