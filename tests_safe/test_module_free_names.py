"""每个模块都不得引用"没有定义的全局名"（阶段 5 的静默杀手）。

## 为什么需要这条守卫

把一个函数从 A 搬到 B，函数体一个字不改也可能坏：它引用的名字原来是 **A 的
模块级全局**，搬到 B 之后 B 没提供。本仓库真实发生过**两次**，且两次都不是
"导入失败"，而是运行到那条分支才 NameError——路由处理器普遍有
`try/except Exception`，于是它被吞成 **200 的 `{"status":"error"}`**：

  1. `normalize_emotion_label` 搬进 `app/core/emotions.py` 时丢了 `import re`，
     打到 `/api/emotion-details`、`/api/realtime-stats` 才炸；
  2. `app/routers/votes.py` 的 `confirm_vote` 用 `datetime.now()`，而唯一的
     `from datetime import datetime` 写在 `close_vote` **函数体内**——函数内的
     局部绑定对别的函数不可见。

两次都不是"路由表"层面的问题：路由一条不少、`ast.parse` 合法、导入也成功。
`tests_safe/test_route_baseline.py` 只覆盖**只读**路由，而 `/api/confirm-vote`
是写路由，天然不在其中。所以必须有一条**静态、全仓覆盖**的守卫，而不是靠
"恰好有测试打到那条分支"。

## 判据

用 `symtable`（编译器自己做作用域分析的同一套）收集模块内所有"全局查找"的名字，
减去模块级绑定、内置名、导入系统隐式提供的名字；空集才算通过。
见 `tools/static_checks.py`。

## 星号导入

`from X import *` 绑定的名字静态不可知，这类模块会被跳过（并单独断言，
免得某天有人加了星号导入把整条守卫悄悄关掉）。
"""

from app.core.paths import PROJECT_ROOT
from tools.static_checks import free_globals, has_star_import

# 覆盖 app/ 全部模块与 server.py（拆分中的两个当事方都在这里）。
TARGETS = sorted(PROJECT_ROOT.glob("app/**/*.py")) + [PROJECT_ROOT / "server.py"]


def _targets():
    return [p for p in TARGETS if p.is_file() and "__pycache__" not in p.parts]


def test_targets_are_actually_found():
    """阳性对照：守卫必须真的扫到了东西，而不是空列表上的真空通过。"""
    paths = {p.relative_to(PROJECT_ROOT).as_posix() for p in _targets()}
    assert len(paths) > 20, f"扫描目标太少（{len(paths)} 个），路径推导可能失效"
    assert "server.py" in paths
    assert "app/core/emotions.py" in paths
    assert "app/routers/votes.py" in paths


def test_no_module_has_undefined_global_names():
    """全仓模块都不得引用未定义的全局名。

    报错信息给出文件名与名字，便于直接定位；名字为空集即通过。
    """
    offenders: dict[str, list[str]] = {}
    skipped: list[str] = []

    for path in _targets():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if has_star_import(source):
            skipped.append(rel)
            continue
        names = free_globals(source, rel)
        if names:
            offenders[rel] = sorted(names)

    assert not offenders, (
        "这些模块引用了没有定义的全局名——运行到对应分支会 NameError。\n"
        "路由处理器通常把它吞成 200 的 {'status':'error'}，因此测试可能全绿。\n"
        + "\n".join(f"  {rel}: {names}" for rel, names in sorted(offenders.items()))
        + "\n请补上模块级导入/定义，或在搬迁时把它一并带到新模块。"
    )


def test_no_star_imports_silently_disable_the_guard():
    """星号导入会让守卫对那个模块失效，出现了就必须被看见。"""
    star_modules = [
        p.relative_to(PROJECT_ROOT).as_posix()
        for p in _targets()
        if has_star_import(p.read_text(encoding="utf-8"))
    ]
    assert not star_modules, (
        f"这些模块使用了 `import *`，静态判据无法覆盖：{star_modules}。\n"
        f"请改成显式导入；否则本守卫（test_module_free_names）对它们形同虚设。"
    )


# ------------------------------------------------------------------ 阳性对照

def test_detector_finds_the_re_incident(tmp_path):
    """复现事故 1：搬走的函数丢了 `import re`。"""
    src = (
        'def normalize(label):\n'
        '    return re.split(r"[/,;]+", label)[0]\n'
    )
    assert free_globals(src) == {"re"}


def test_detector_finds_the_function_local_import_incident(tmp_path):
    """复现事故 2：`datetime` 只在**另一个函数体内**导入，对第三个函数不可见。

    这是最容易骗过 import 清单扫描的一种：文件里搜得到
    `from datetime import datetime`，但它的作用域覆盖不到出错的那处。
    """
    src = (
        "def a():\n"
        "    from datetime import datetime\n"
        "    return datetime.now()\n"
        "\n"
        "def b():\n"
        "    return datetime.now()\n"
    )
    assert free_globals(src) == {"datetime"}


def test_detector_accepts_module_level_bindings():
    """阴性对照：模块级导入/定义/参数/局部变量/内置名都不得误报。"""
    src = (
        "import re\n"
        "from datetime import datetime\n"
        "CONST = 1\n"
        "\n"
        "class C:\n"
        "    attr = CONST\n"
        "\n"
        "def f(x, _unused=None):\n"
        "    y = x + CONST\n"
        "    z = [i for i in range(3)]\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as exc:\n"
        "        return str(exc) + str(y) + str(z) + re.escape('a') + str(datetime.now())\n"
        "    return len(str(sorted([o.attr for o in [C()]])))\n"
        "\n"
        "async def g():\n"
        "    async with open_thing() as h:\n"
        "        return h\n"
        "\n"
        "def open_thing():\n"
        "    return None\n"
    )
    assert free_globals(src) == set()


def test_detector_sees_globals_looked_up_from_class_body_and_comprehension():
    """类体与推导式里的全局查找同样要被抓到（子作用域不止函数）。"""
    assert free_globals("class A:\n    x = MISSING\n") == {"MISSING"}
    assert free_globals("YS = [MISSING_2 for _ in range(2)]\n") == {"MISSING_2"}


def test_star_import_detection(tmp_path):
    assert has_star_import("from os import *\n") is True
    assert has_star_import("import os\nfrom a import b\n") is False
