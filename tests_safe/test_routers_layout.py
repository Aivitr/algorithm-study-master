"""`app/routers/` 的拆分守卫（阶段 5：把 server.py 按业务域拆出去）。

本文件守三件在拆分中最容易**静默**出错的事。

一、路由模块不得导入 `server`
----------------------------
本仓库有两种被文档化的启动方式：

    python server.py          → 该进程里 server.py 的模块名是 `__main__`
    gunicorn server:app       → 模块名是 `server`

第一种情况下，`sys.modules` 里**没有 `server` 这个名字**。此时任何
`from server import X` 都会让 Python 把 server.py 当作一个**新模块再执行一遍**
——重复建 app、重复注册全部 59 条路由、重复跑导入期副作用。**它不报错**，
只是内存里多出一套互不相干的对象，且访问哪一套取决于调用点。

因此依赖方向必须单向：`server` → `app.routers.*`，永不反向。需要共享的东西
（logger、单例、开关）应由路由模块从它的定义处取，或由 `server` 在装配时注入。

二、写好的路由模块必须真的被装配
--------------------------------
`app/routers/foo.py` 存在、但 server.py 里没有对应的 `include_router`，那这个
文件就是**永不生效的**：路由从接口表里整体消失，而"文件明明在"。这类漏装配
必须是一条红色测试，而不是靠人记得。

三、`app/routers/__init__.py` 保持为空
--------------------------------------
理由与 `app/services/__init__.py` 相同：Python 导入 `app.routers.X` 前必先执行
它，任何 re-export 都会把"只装配需要的路由"变成"装配全部路由"，把各模块的
重依赖提前到启动期,并可能让可选依赖变成必需依赖。

本文件只做静态解析，不导入任何业务模块。
"""

import ast
from pathlib import Path

import pytest

from app.core.paths import PROJECT_ROOT

ROUTERS_DIR = PROJECT_ROOT / "app" / "routers"
SERVER_PY = PROJECT_ROOT / "server.py"


def _router_modules() -> list[Path]:
    if not ROUTERS_DIR.is_dir():
        return []
    return sorted(
        p for p in ROUTERS_DIR.glob("*.py") if p.name != "__init__.py"
    )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_top_level_packages(tree: ast.Module) -> set[str]:
    """本文件导入的**顶层包名**（含函数体内的延迟导入，它们同样会触发执行）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


# --------------------------------------------------------------- 一、单向依赖

@pytest.mark.parametrize("module", _router_modules(), ids=lambda p: p.name)
def test_router_module_does_not_import_server(module: Path):
    """路由模块不得（在任何层级）导入 `server`。

    在 `python server.py` 下，这会触发 server.py 的**二次执行**——重复建 app、
    重复注册路由，且不报错。测试端之所以看不见，是因为 pytest 是以
    `import server` 的方式加载的（模块名是 `server`），这条路径恰好不炸。
    所以必须静态挡住，不能靠运行时发现。
    """
    tree = _parse(module)
    packages = _imported_top_level_packages(tree)

    assert "server" not in packages, (
        f"{module.name} 导入了 `server`。\n"
        f"在 `python server.py` 启动时，server.py 的模块名是 `__main__`，"
        f"`from server import ...` 会把它**再执行一遍**（重复建 app、重复注册路由），"
        f"且不报错。\n"
        f"需要共享对象时，请从它的定义处导入（如 app.services.oss_utils），"
        f"或由 server.py 在装配时注入。依赖方向只能是 server → app.routers.*。"
    )


def test_detector_actually_detects_server_import(tmp_path):
    """阴性+阳性对照：上一条不是永远绿的摆设。"""
    bad = tmp_path / "bad.py"
    bad.write_text("from server import manager\n", encoding="utf-8")
    assert "server" in _imported_top_level_packages(_parse(bad))

    # 函数体内的延迟导入同样要被抓到
    lazy = tmp_path / "lazy.py"
    lazy.write_text(
        "def f():\n    import server\n    return server.manager\n", encoding="utf-8"
    )
    assert "server" in _imported_top_level_packages(_parse(lazy))

    ok = tmp_path / "ok.py"
    ok.write_text(
        "from app.services.oss_utils import get_oss_manager\n"
        "from app.services.voiceprint_manager import voiceprint_manager\n",
        encoding="utf-8",
    )
    assert "server" not in _imported_top_level_packages(_parse(ok))


# --------------------------------------------------------------- 二、必须被装配

def _routers_imported_by_server() -> dict[str, str]:
    """server.py 里从 `app.routers.*` 导入的名字 → 来源模块。"""
    tree = _parse(SERVER_PY)
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module == "app.routers":
            for alias in node.names:
                imported[alias.asname or alias.name] = f"app.routers.{alias.name}"
        elif node.module.startswith("app.routers."):
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module
    return imported


def _names_passed_to_include_router() -> set[str]:
    """server.py 里 `app.include_router(<名字>)` 实际传入的变量名。"""
    tree = _parse(SERVER_PY)
    included: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "include_router":
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    included.add(arg.id)
    return included


def test_every_router_module_on_disk_is_imported_by_server():
    """磁盘上的每个路由模块，server.py 都必须导入它。

    防的是"拆到一半"：文件建好了，装配忘了加——那个模块静默失效，
    接口表里少一批路由。
    """
    on_disk = {f"app.routers.{p.stem}" for p in _router_modules()}
    imported = set(_routers_imported_by_server().values())

    not_wired = on_disk - imported
    assert not not_wired, (
        f"这些路由模块存在但 server.py 没有导入：{sorted(not_wired)}。\n"
        f"它们不会生效。请在 server.py 末尾的「路由装配」段加 include。"
    )


def test_every_imported_router_is_included():
    """导入了就必须真的 `include_router`——只 import 不装配是无效的。"""
    imported = _routers_imported_by_server()
    included = _names_passed_to_include_router()

    not_included = {name: mod for name, mod in imported.items() if name not in included}
    assert not not_included, (
        "这些路由模块被导入了，但没有传给 app.include_router()：\n  "
        + "\n  ".join(f"{name}  ({mod})" for name, mod in sorted(not_included.items()))
        + "\n它们不会生效。"
    )


def test_the_wiring_check_actually_bites(tmp_path, monkeypatch):
    """阴性对照：证明上面两条的判定逻辑真的会因为"漏装配"而失败。"""
    fake = tmp_path / "server.py"
    fake.write_text(
        "from app.routers.alpha import router as alpha_router\n"
        "from app.routers.beta import router as beta_router\n"
        "app.include_router(alpha_router)\n",
        encoding="utf-8",
    )
    import sys

    monkeypatch.setattr(sys.modules[__name__], "SERVER_PY", fake, raising=True)
    imported = _routers_imported_by_server()
    included = _names_passed_to_include_router()

    assert set(imported) == {"alpha_router", "beta_router"}
    assert included == {"alpha_router"}
    # beta_router 正是"导入未装配"的那一个
    assert "beta_router" in set(imported) - included


# --------------------------------------------------------------- 三、__init__ 为空

def test_routers_init_stays_empty():
    """`app/routers/__init__.py` 只能有文档字符串，不能有可执行导入。

    它被任何一个 `app.routers.X` 的导入顺带执行；在里面 re-export 会让
    "按需装配"变成"装配全部路由"，并把各模块的依赖提前到启动期。
    """
    init = ROUTERS_DIR / "__init__.py"
    assert init.is_file(), "app/routers/__init__.py 不存在"

    tree = _parse(init)
    statements = [
        node
        for node in tree.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
        and not isinstance(node, ast.Pass)
    ]
    assert not statements, (
        "app/routers/__init__.py 里出现了文档字符串之外的语句：\n  "
        + "\n  ".join(ast.unparse(s) for s in statements)
        + "\n本文件应保持为空——理由见 app/routers/__init__.py 的说明。"
    )
