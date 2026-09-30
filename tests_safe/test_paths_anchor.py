"""路径锚点契约：所有模块对「项目根在哪」必须给出同一个答案。

这条契约防的是设计文档 §3.1 的失效模式
--------------------------------------
在本仓库里，「项目根目录」曾经有四份各自独立的推导（server.py、config.py、
research_runtime.py、3/c_realtime_integration.py），四种写法**当前都得出了
正确的值——只因为它们恰好都住在仓库根下**。

这类耦合的危险不在"现在错了"，而在**"将来错了却不出声"**：

    config.py 迁到 app/core/ 之后
    BASE_DIR = Path(__file__).resolve().parent   # → <root>/app/core  ✗
    env_path = BASE_DIR / ".env"                 # → 不存在
    if not env_path.exists(): return             # → 静默 return（§3.10）

结果是配置无声退化成默认值：应用照常启动、照常跑，只在连库那一刻才暴露。
**没有任何一步会报错。** 阶段 3 的全部工作就是移动文件，所以这条路径会被
反复走到——必须有断言挡着，不能靠人记得。

因此本文件的断言不是「BASE_DIR 现在对不对」（今天必然对），而是
「它是否仍然由出现位置推导」与「各处是否已统一到 feedpaths」。

依赖关系：`app/core/paths.py` 是无副作用的纯模块，可安全导入。
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 运行期模块：这些是应用启动链上真正会被导入的模块。清单需随 app/ 的
# 建立而增长——每迁入一个模块，就把它加进来，锚点契约才覆盖得到它。
#
# 阶段 3.2：`config.py` 已迁入 `app/core/`，此处随之改为新路径。这正是上面那句
# 「清单需随 app/ 的建立而增长」的意思：**搬迁如果没同步改这里，契约就悄悄缩水**
# ——旧路径读不到文件会得到空字符串，而空字符串里当然找不到 `__file__`，
# 断言会"通过"。所以列表里每一项都必须指向真实存在的文件（见下方
# test_runtime_module_paths_exist）。
RUNTIME_MODULES = ("server.py", "app/core/config.py", "app/core/database.py")


def test_runtime_module_paths_exist():
    """清单里的每个路径都必须真实存在。

    这一条是上面那条断言的地基：文件不存在时读取会得到空字符串，
    而空字符串里找不到 `__file__` —— 「没有违规」于是变成了「没在检查」。
    路径写错、文件被搬走而清单没跟上，都会在这里立刻暴露。
    """
    for module_path in RUNTIME_MODULES:
        assert (REPO_ROOT / module_path).is_file(), (
            f"RUNTIME_MODULES 里的 {module_path} 不存在——"
            f"锚点契约对它实际处于失效状态，请随搬迁同步更新清单。"
        )


def test_project_root_is_the_repo_root():
    """PROJECT_ROOT 必须就是仓库根。"""
    from app.core.paths import PROJECT_ROOT

    assert PROJECT_ROOT == REPO_ROOT
    for sentinel in ("requirements.txt", "index.html", "server.py"):
        assert (PROJECT_ROOT / sentinel).exists(), f"仓库根缺少哨兵文件 {sentinel}"


def test_root_resolution_is_independent_of_cwd(session_tmp_dir):
    """根目录的解析结果**不得**随当前工作目录变化。

    这是 §3.1 的正题：锚点若与"进程从哪启动"或"文件住在哪"挂钩，
    从别处启动就会静默指错目录。这里换一个完全无关的 cwd 重跑一次解析，
    结果必须逐字节相同。

    用子进程而非改 os.chdir：后者会污染同进程内其他用例的临时目录语义。
    """
    outside = session_tmp_dir / "some-unrelated-cwd"
    outside.mkdir(exist_ok=True)

    code = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from app.core.paths import PROJECT_ROOT;"
        "print(PROJECT_ROOT)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(outside),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"子进程解析失败：{result.stderr}"
    assert Path(result.stdout.strip()) == REPO_ROOT, (
        f"从 {outside} 启动时解析出的根目录与仓库根不一致——"
        f"解析结果仍在依赖 cwd 或文件位置"
    )


def test_root_resolution_fails_loudly_when_no_sentinels(tmp_path):
    """找不到哨兵时必须抛错，**不得**退而返回某个猜测值。

    这条防的是"把静默失败改成另一种静默失败"：给 `_find_project_root` 加一个
    `or Path.cwd()` 之类的兜底，会让解析错目录这件事重新变得无声。

    `tmp_path` 由 pytest 建在系统临时目录下，其上方不含本仓库的哨兵。
    """
    from app.core.paths import _find_project_root

    with pytest.raises(RuntimeError, match="无法定位项目根目录"):
        _find_project_root(tmp_path)


def test_runtime_modules_agree_on_root():
    """运行期模块各自导出的根目录，必须与 paths 的解析结果一致。"""
    from app.core.paths import PROJECT_ROOT

    from app.core import config
    import server

    assert config.BASE_DIR == PROJECT_ROOT, "config.BASE_DIR 与 PROJECT_ROOT 不一致"
    assert Path(server.BASE_DIR) == PROJECT_ROOT, "server.BASE_DIR 与 PROJECT_ROOT 不一致"
    assert Path(server.ROOT_DIR) == PROJECT_ROOT, "server.ROOT_DIR 与 PROJECT_ROOT 不一致"


@pytest.mark.parametrize("module_path", RUNTIME_MODULES)
def test_runtime_modules_do_not_derive_root_from_own_location(module_path):
    """运行期模块**不得**再用 `__file__` 推导根目录。

    这是把「注释里写清楚」升级成「由测试强制」——否则下一个迁移文件的人
    仍会照着旁边的代码抄一份 `Path(__file__).resolve().parent`。

    只检查赋值给 BASE_DIR / ROOT_DIR 的那一行，不做全文件 `__file__` 扫描：
    模块里合法使用 `__file__` 的地方（日志、诊断）不该被误伤。
    """
    source = (REPO_ROOT / module_path).read_text(encoding="utf-8", errors="replace")

    offenders = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith(("BASE_DIR", "ROOT_DIR")):
            continue
        if "__file__" in stripped:
            offenders.append(f"{module_path}:{lineno}: {stripped}")

    assert not offenders, (
        "以下行仍在用模块自身位置推导根目录——文件一移动，值就会静默变错：\n  "
        + "\n  ".join(offenders)
        + "\n改为 `from app.core.paths import PROJECT_ROOT`。"
    )


# server.py 追加进 sys.path 的目录名（相对仓库根）。
#
# 原有三条：`1/`、`2/`、`_tmp_agora_token_builder`。前两条已在阶段 3 移除——
# `1/` 归档到 archive/prototypes/legacy-1/（不含任何被导入的模块），`2/` 则
# **从未存在**过（原代码无条件 append，一直是空操作）。
#
# 这条断言正是促使那次清理的原因：它在本目录被归档时立刻失败，逼那一步显式
# 处理这段 append，而不是留下指向虚空的路径。
_EXPECTED_SYSPATH_DIRS = {"_tmp_agora_token_builder"}
_KNOWN_ABSENT_SYSPATH_DIRS: set[str] = set()


def test_server_syspath_additions_are_known_and_present():
    """server.py 的 sys.path 追加项必须是**已知集合**，且除已知缺失者外都存在。

    两件事合在一起才有效：
      - 集合相等 → 防止有人悄悄加一条指向新目录的 append
      - 存在性   → 让目录被移走/归档的那一步无法悄无声息地过去
    """
    import server

    names = {Path(p).name for p in server._SERVER_SYSPATH_ADDITIONS}

    assert names == _EXPECTED_SYSPATH_DIRS, (
        f"server.py 的 sys.path 追加项发生了变化。\n"
        f"  当前：{sorted(names)}\n  预期：{sorted(_EXPECTED_SYSPATH_DIRS)}"
    )

    missing = {
        Path(p).name
        for p in server._SERVER_SYSPATH_ADDITIONS
        if not Path(p).is_dir()
    } - _KNOWN_ABSENT_SYSPATH_DIRS

    assert not missing, (
        f"以下 sys.path 追加项目录已不存在：{sorted(missing)}\n"
        f"若这是归档 `1/` 造成的，请同步移除 server.py 中对应的 append。"
    )
