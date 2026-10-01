"""搬迁守卫：模块搬进 `app/` 之后，**全仓库都不得再用裸名导入它**。

本文件防的是什么
----------------
阶段 3 的核心动作就是把根级模块搬进 `app/` 的子目录。搬迁会留下一种**只在
生产上才发作**的错误：调用点还写着旧名字。

    from ai_core import RealtimeTranscriber      # 搬家后应写 app.services.ai_core

改错的后果不是"悄悄用错"，而是 `ModuleNotFoundError`——只不过发作的时机很坏：
**延迟导入**（写在函数体里、为了省启动开销的那种）只在那一行真正执行时才报错。
`server.py:3410` 的 `from ai_core import RealtimeTranscriber` 就在一个处理器函数
内部。测试若从不走那条路由，**全套测试仍然全绿**，而线上第一个用到该功能的用户
会拿到 500。

这正是本仓库反复出现的失效模式："错误发生了，但没有任何一步会出声"。
因此这里的断言不是"搬迁后能不能跑"（能跑不算数），而是
**"还有没有哪一行在写旧名字"**——由 AST 逐文件查，不靠人记得。

为什么用注册表而不是一次性检查
------------------------------
每个搬迁步骤往 `MOVED_MODULES` 里加一条，守卫就自动覆盖它。
同时 `test_registry_is_honest` 要求注册表里**每一对路径都必须真实**
（旧的不存在、新的存在）——否则注册表会悄悄失效成"什么都没在检查"，
那是本仓库另一条反复出现的失效模式（对照 `test_paths_anchor.py` 里
`RUNTIME_MODULES` 旁边写的那段）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 裸名 → 它现在住的模块（点号路径）。每完成一步搬迁就加一条。
#
# 阶段 3.2 的两条是**回归登记**：它们已经搬完，登记在此是为了让守卫从第一天起
# 就带着真实数据运行——一个从未捕获过任何东西的守卫，没人知道它到底有没有用。
MOVED_MODULES: dict[str, str] = {
    "config": "app.core.config",
    "database": "app.core.database",
    # 阶段 3.3：服务层搬入 app/services/
    "llm_service": "app.services.llm_service",
    "knowledge_graph_service": "app.services.knowledge_graph_service",
    "ai_core": "app.services.ai_core",
    "research_runtime": "app.services.research_runtime",
    "research_registry": "app.services.research_registry",
    "research_enhanced_adapters": "app.services.research_enhanced_adapters",
    "research_algorithm_fusion": "app.services.research_algorithm_fusion",
    "voiceprint_manager": "app.services.voiceprint_manager",
    "video_processor": "app.services.video_processor",
    "gemma_emotion_client": "app.services.gemma_emotion_client",
    "oss_config": "app.services.oss_config",
    "oss_utils": "app.services.oss_utils",
}

# 扫描时跳过的目录，每一个都有明确理由：
#   venv                     第三方代码，不是本仓库的
#   archive                  冻结的历史记录——里面本来就写着搬迁前的旧名字，
#                            改它反而失真（归档策略见 archive/README.md）
#   _tmp_agora_token_builder 独立小工具，由 server.py 单独加进 sys.path，
#                            与 app/ 的导入体系无关
#   __pycache__              字节码，不是源码
_SKIP_DIRS = {"venv", "archive", "_tmp_agora_token_builder", "__pycache__"}


def _iter_python_files() -> list[Path]:
    """返回所有需要检查的 .py 文件。"""
    files = []
    for path in REPO_ROOT.rglob("*.py"):
        if _SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def bare_imports(source: str) -> list[tuple[int, str]]:
    """找出源码里所有「以 `MOVED_MODULES` 中的裸名为顶层包」的导入。

    返回 [(行号, 被导入的名字)]。`import a.b` 只看 `a`——`app.core.config`
    的顶层是 `app`，不在注册表里，因此不会误报。

    语法错误的文件不在这里报错（另有测试负责整体可导入性），直接跳过：
    本函数的职责单一，混进别的检查会让它自己的失败变得难以归因。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in MOVED_MODULES:
                    found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            # 相对导入（module is None，或 level>0）按定义就是包内引用，不涉及裸名
            if node.module is None or node.level:
                continue
            top = node.module.split(".")[0]
            if top in MOVED_MODULES:
                found.append((node.lineno, node.module))
    return found


def test_registry_is_honest():
    """注册表里每一对路径都必须真实——旧的已搬走、新的确实在。

    这一条是整份守卫的地基。若某次搬迁改了文件名而没更新注册表，
    扫描会"找不到违规"而通过——**通过的原因是没在检查**，不是真的干净。
    """
    for bare, module_path in MOVED_MODULES.items():
        new_file = REPO_ROOT / (module_path.replace(".", "/") + ".py")
        assert new_file.is_file(), (
            f"注册表说 {bare} 现在住在 {module_path}，但 {new_file} 不存在。"
            f"请修正注册表——否则本文件的所有检查都在空转。"
        )

        old_file = REPO_ROOT / f"{bare}.py"
        assert not old_file.is_file(), (
            f"{bare} 已登记为「搬走」，但 {old_file} 仍然存在——"
            f"旧位置与注册表冲突，说明搬迁只做了一半。"
        )


def test_detector_actually_detects():
    """阳性对照：给检测器一段**确定含违规**的源码，它必须报出来。

    没有这一条，`bare_imports` 里任何一个写坏的条件（比如干脆 `return []`）
    都会让下面那条测试显示"全仓库干净"——**通过的原因是没在检查**。
    守卫自身也需要被守卫。

    正例用注册表里真实存在的名字（`config`/`database`），不另造虚构模块：
    否则这段测试可能与注册表脱节，下次加条目时它照样"通过"却已无意义。
    """
    positives = [
        ("import config", "config"),
        ("from config import settings", "config"),
        ("from database import SessionLocal", "database"),
        # 延迟导入（缩进在函数体内）同样必须被看见——这正是最危险的一类
        ("def handler():\n    from database import get_db\n", "database"),
    ]
    for source, expected_top in positives:
        got = bare_imports(source)
        assert [name.split(".")[0] for _, name in got] == [expected_top], (
            f"检测器没能识别 {source!r}（得到 {got}）"
        )

    # 反向对照：这些**不该**被报出来。写错方向同样致命——满屏误报会让守卫
    # 很快被 `# noqa` 或删除处理掉，等于没有。
    clean = "\n".join([
        "import os",
        "from app.core import config",
        "from app.core.config import settings",
        "import app.models",
        "from . import sibling",
        "from .config import local",
    ])
    assert bare_imports(clean) == [], f"检测器误报了合法导入：{bare_imports(clean)}"


@pytest.mark.parametrize("path", _iter_python_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_bare_imports_of_moved_modules(path: Path):
    """本仓库任何一处都不得再用旧名字导入已搬迁的模块。"""
    violations = bare_imports(path.read_text(encoding="utf-8", errors="replace"))
    assert not violations, (
        f"{path.relative_to(REPO_ROOT)} 仍在使用已搬迁模块的旧名字：\n  "
        + "\n  ".join(
            f"{path.relative_to(REPO_ROOT)}:{lineno}: {name} → 应为 "
            f"{MOVED_MODULES[name.split('.')[0]]}"
            for lineno, name in violations
        )
        + "\n注意：延迟导入（写在函数体内）在测试里往往走不到，"
        "改错了也不会变红——所以这里才要静态查。"
    )
