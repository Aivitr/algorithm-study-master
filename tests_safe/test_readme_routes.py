"""路由清单只许有一份，且必须是机器枚举的那一份（2026-10-01 起）。

README 曾经手抄过一整份按域分组的路由表，和机器枚举的 `docs/route-inventory.md`
并存——两份真相，迟早漂移，而 README 恰恰是**外人最先读到的那一份**：它一旦落后，
读到的人按它去调接口，拿到的是 404。

2026-10-02 起 README 不再自持任何路由数据——清单、数量、分项，一概不留，只指向
`docs/route-inventory.md`。本文件随之换成新的契约，三条一起守：

  1. README 里**不许再出现路由表行**（`_README_ROUTE_ROW`）——手抄清单回流就报红；
  2. README 必须真的指向 `docs/route-inventory.md`（指路断了，读者就无处可去）；
  3. `docs/route-inventory.md` 与源码逐条一致。

README 侧不再有任何路由内容需要"比对"，所以这里没有相等断言可言——守的是
**它不再复述**（第 1 条）与**它把读者送去哪**（第 2 条）：前者是反向断言，
后者是正向断言，两头都不靠"解析出来的东西恰好为空"来通过。

"文档悄悄腐化"在本仓库不是假想敌：
  * README 的项目结构树整棵是错的（列的七个文件全都早已不在根目录）；
  * `.env` 的说明与 `.env.example` 对不上（`test_env_docs.py` 就是为此而生）；
  * `.dockerignore` 的裸文件名模式在文件搬家后悄然失效。

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

# README 里**不该再有**的路由表行：`| `GET` | `/api/x` | 说明 |`。
# 用它做反向断言——手抄清单一旦回流，这里先红。
_README_ROUTE_ROW = re.compile(
    r"^\|\s*`?(GET|POST|PUT|DELETE|PATCH|WS)`?\s*\|\s*`([^`]+)`\s*\|",
    re.MULTILINE,
)

# 源码侧下限。当前实测正好 59（GET 28 / POST 26 / DELETE 2 / WS 3），与
# test_route_contract.py 冻死的"59 个接口"吻合。留出余量是为了让**新增路由**不必改这里，但抽取一旦
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


def test_the_source_side_actually_found_routes():
    """`test_the_other_inventory_document_agrees_with_the_source` 的保底。

    抽取逻辑一旦整体失效（装饰器换了写法、`_ROUTE_OWNERS` / `_ROUTE_DECORATORS`
    没跟上），那份清单会抽成空集，而"空集 == 空集"**平凡通过**。所以先在这里
    拦一道——本仓库在"空输入 == 通过"上栽过不止一次。
    """
    found = _routes_in_source()
    assert len(found) >= _MIN_EXPECTED_ROUTES, (
        f"只从源码里抽出 {len(found)} 条路由（预期 ≥ {_MIN_EXPECTED_ROUTES}）。"
        f"多半是装饰器的写法变了（`_ROUTE_OWNERS` / `_ROUTE_DECORATORS` 没跟上）——"
        f"此时下游的数量断言会**平凡通过**，所以在这里先拦一道。"
    )


def test_readme_does_not_hand_copy_the_route_list():
    """README 里不许再出现路由表行——清单只在 `docs/route-inventory.md` 一份。

    这是一条**反向**断言：它把"README 不再自持清单"这个决定钉住，防止哪天有人
    "顺手把表补回来"。真要补，得先删掉这条断言——而那正是这个决定该被重新
    审视的时刻，不该悄悄地发生。
    """
    text = README.read_text(encoding="utf-8") if README.is_file() else ""
    rows = _README_ROUTE_ROW.findall(text)
    assert not rows, (
        f"README 里又出现了 {len(rows)} 行手抄的路由表（例：{rows[:3]}）。\n"
        f"路由清单只留 docs/route-inventory.md 一份——那是从运行中的 app 枚举"
        f"出来的，不会腐化；README 里再抄一份就是第二个真相。"
    )


def test_readme_points_at_the_machine_enumerated_inventory():
    """README 必须真的指向那份唯一的清单，否则读者无处可去。"""
    if not README.is_file():
        pytest.skip("README.md 不存在")
    assert "docs/route-inventory.md" in README.read_text(encoding="utf-8"), (
        "README 没提到 docs/route-inventory.md。清单搬到那边之后，这句指路就是"
        "读者找到它的唯一入口。"
    )
    assert (REPO_ROOT / "docs" / "route-inventory.md").is_file(), (
        "README 指向了 docs/route-inventory.md，但那个文件不在。"
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
