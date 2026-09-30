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


# ---- 「用 `__file__` 推导项目内路径」的模块 -----------------------------------
#
# 上面那条 `test_runtime_modules_do_not_derive_root_from_own_location` 只盯
# `BASE_DIR` / `ROOT_DIR` 这两个赋值。但同样的错误还有别的写法——实测在
# `research_runtime.py` 与 `video_processor.py` 里各有一处：
#
#     repo_root = Path(__file__).resolve().parent      # 用来拼脚本路径
#     here      = Path(__file__).resolve().parent      # 用来找内置的 haarcascade
#
# 它们**今天是对的**，只因为这两个文件恰好住在仓库根。阶段 3.3 要么把它们搬进
# `app/services/`，那一刻两处都会静默指错：`research_runtime` 报出的脚本路径会
# 指向 `app/services/`，`video_processor` 更糟——它的候选列表包在
# `except Exception: pass` 里，找不到就**悄悄退到 OpenCV 自带的模型**，
# 人脸识别照常"能用"，只是用的不是仓库内置的那一份。**没有任何一步会报错。**
#
# 所以这里把「不许用 `Path(__file__)` 推导项目内路径」也变成断言。
# 只匹配 `Path(__file__)` 这一串字面 token——`Path(cv2.__file__)` 是另一串，
# 不会误伤：那种用法指向的是第三方包自己的数据目录，本来就该跟着包走。
FILE_PATH_ANCHORED_MODULES = ("research_runtime.py", "video_processor.py")

# 项目内的路径必须由这里推导（阶段 0 建立的唯一锚点）
def _path_file_uses(source: str) -> list[tuple[int, str]]:
    """返回源码里**实际代码中**出现 `Path(__file__)` 的位置 [(行号, 该行原文)]。

    为什么必须是 token 级判断，而不是 `re.search` 文本匹配
    ------------------------------------------------------
    文本匹配会把**注释里的讲解**当成违规。实测就是这样：锚点修好之后这条断言
    仍然失败，因为源文件的注释与本测试自己的说明文字里都写着"不要用
    `Path(__file__)`"这几个字。**讲解不等于违规。**

    这个区别很实际：一个会对正确代码报错的守卫，很快就会被 `# noqa` 或直接
    删掉；那比没有守卫更糟，因为它看起来还在保护什么。

    token 级判断不受影响：注释是 COMMENT token，说明文字是 STRING token，
    而这里要匹配的是 `Path` `(` `__file__` `)` 四个**代码 token** 的连续序列。
    `Path(cv2.__file__)` 因多了一个 `cv2` `.` 而不匹配——那是第三方包自己的
    数据目录，本来就该跟着包走。
    """
    import io
    import tokenize

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # 语法有问题的文件不在这里报错（另有测试负责整体可导入性），
        # 让本函数的失败原因保持单一。
        return []

    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING}
    code = [t for t in tokens if t.type not in skip]

    hits = []
    for i in range(len(code) - 3):
        a, b, c, d = code[i:i + 4]
        if (a.type == tokenize.NAME and a.string == "Path"
                and b.string == "("
                and c.type == tokenize.NAME and c.string == "__file__"
                and d.string == ")"):
            lineno = a.start[0]
            hits.append((lineno, source.splitlines()[lineno - 1].strip()))
    return hits


def _import_runtime_module(bare: str):
    """按两种布局导入运行期模块：搬迁后（`app.services.X`）优先，退回根级 `X`。

    本文件里的行为断言要在**搬迁前后都能跑**——那正是它们的价值：
    搬迁前通过证明"改锚点是等值替换"，搬迁后通过证明"文件挪了值没变"。
    写死任一种布局都会让另一边失败，而"失败"很容易被误读成"搬迁出问题了"。
    """
    import importlib

    for module_name, rel in (
        (f"app.services.{bare}", f"app/services/{bare}.py"),
        (bare, f"{bare}.py"),
    ):
        if (REPO_ROOT / rel).is_file():
            return importlib.import_module(module_name)
    raise AssertionError(f"两种布局下都找不到 {bare}（仓库根 {REPO_ROOT}）")


@pytest.mark.parametrize("module_path", FILE_PATH_ANCHORED_MODULES)
def test_no_project_paths_derived_from_own_file(module_path):
    """不得用 `Path(__file__)` 推导项目内路径——文件一挪就静默指错。"""
    source = (REPO_ROOT / module_path).read_text(encoding="utf-8", errors="replace")
    offenders = [f"{module_path}:{lineno}: {line}" for lineno, line in _path_file_uses(source)]

    assert not offenders, (
        "以下行用模块自身位置推导项目内路径——文件一旦搬进 app/ 就会静默指错：\n  "
        + "\n  ".join(offenders)
        + "\n改为 `from app.core.paths import PROJECT_ROOT`。"
    )


def test_research_runtime_anchors_scripts_to_project_root():
    """`research_runtime` 报出的脚本路径必须落在仓库根下。

    这是上面那条静态检查的**行为证据**：静态只证明"没写 `Path(__file__)`"，
    这条证明"算出来的值确实指向仓库根"。
    """
    from app.core.paths import PROJECT_ROOT

    module = _import_runtime_module("research_runtime")
    summary = module.research_runtime._setup_scripts_summary()

    assert summary, "脚本摘要不应为空"
    for key, value in summary.items():
        assert Path(value).parent == PROJECT_ROOT, (
            f"{key} 指向 {value}，其父目录是 {Path(value).parent}，"
            f"并非仓库根 {PROJECT_ROOT}——脚本路径的锚点漂了。"
        )


def test_video_processor_looks_for_cascade_in_project_root(monkeypatch):
    """`video_processor` 必须仍在**仓库根**找它内置的 haarcascade。

    为什么这条值得单独立一个测试：这段查找包在 `except Exception: pass` 里，
    锚点错了不会抛错，只会**安静地换用 OpenCV 自带的模型**——功能表面正常，
    用的却是另一份文件。所以这里不检查"有没有加载成功"（那会误判为通过），
    而是拦住 `cv2.CascadeClassifier` 的构造调用，看它**实际尝试了哪个路径**。
    """
    import cv2

    from app.core.paths import PROJECT_ROOT

    module = _import_runtime_module("video_processor")

    attempted = []
    real_cascade = cv2.CascadeClassifier

    def recording_cascade(*args, **kwargs):
        # cv2.CascadeClassifier() 无参构造也是合法用法，只记录带路径的那些
        if args:
            attempted.append(str(args[0]))
        return real_cascade(*args, **kwargs)

    monkeypatch.setattr(module.cv2, "CascadeClassifier", recording_cascade)
    module.VideoEmotionAnalyzer()

    expected = str(PROJECT_ROOT / "haarcascade_frontalface_default.xml")
    assert expected in attempted, (
        f"未尝试加载仓库内置的 haarcascade。\n"
        f"  期望其中有：{expected}\n  实际尝试了：{attempted}\n"
        f"锚点若漂到 app/services/，这里会退到 OpenCV 自带模型而不报任何错。"
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
