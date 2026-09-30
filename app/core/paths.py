"""唯一的路径解析来源（设计文档 §4.1）。

为什么需要它
------------
在这个仓库里，「项目根目录在哪」曾经有四份各自独立的答案：

| 位置 | 写法 | 根目录当前恰好是 |
|---|---|---|
| `server.py:21` | `os.path.dirname(os.path.abspath(__file__))` | 仓库根（因为文件在根下） |
| `config.py:7` | `Path(__file__).resolve().parent` | 仓库根（同上） |
| `research_runtime.py:940` | `Path(__file__).resolve().parent` | 仓库根（同上） |
| `3/c_realtime_integration.py:18` | `dirname(dirname(abspath(__file__)))` | 仓库根（同上） |

四种写法**当前都得出了正确的值**——但这只是因为它们恰好都住在仓库根下。
这恰恰是设计文档 §3.1 记录的那类故障的成因：**值对，是因为位置对；一旦位置
变了，值就静默地跟着变错，而没有任何东西会报错。**

阶段 3 要做的事就是移动文件。`config.py` 一旦迁到 `app/core/`，它的
`Path(__file__).resolve().parent` 会立刻变成 `<root>/app/core`，`.env` 随即
找不到——而 `config.py:12-13` 是**静默 return**（§3.10），于是配置无声退化成
默认值，应用照常启动、照常跑，只有连库时才暴露。这正是本模块存在的理由：
**把「根目录」从「文件在哪」解耦成「仓库在哪」。**

解析策略
--------
不靠 `__file__` 的层级数（那只是把同一个耦合换个写法），而是**从本文件所在
位置向上搜索哨兵文件**。哨兵要求三件同时存在，误判到子目录的概率极低；
找不到则抛错——宁可启动失败，也不要静默指错目录。

依此得到的根目录与本文件将来被搬到何处无关：`paths.py` 可以在 `app/` 下任意
深度，只要仓库根的三件哨兵还在，解析结果就不变。
"""

from pathlib import Path

# 哨兵：三者需同时存在于仓库根。用三个而不是一个，是为了让「误匹配到某个恰好
# 含有相同文件名的子目录」几乎不可能发生。
_ROOT_SENTINELS = ("requirements.txt", "index.html", "server.py")

_THIS_FILE = Path(__file__).resolve()


def _find_project_root(start: Path) -> Path:
    """从 `start` 起逐级向上，返回第一个同时含全部哨兵的目录。"""
    for candidate in (start, *start.parents):
        if all((candidate / name).exists() for name in _ROOT_SENTINELS):
            return candidate
    raise RuntimeError(
        f"无法定位项目根目录：从 {start} 向上直到文件系统根，"
        f"都没有找到同时包含 {_ROOT_SENTINELS} 的目录。\n"
        f"这通常意味着仓库结构已变动，或 paths.py 被复制到了仓库之外。\n"
        f"宁可在此失败，也不要静默解析成错误的目录——错的数据目录不会报错，"
        f"只会把文件写到别处、或读到空配置。"
    )


PROJECT_ROOT: Path = _find_project_root(_THIS_FILE.parent)

# ---------------------------------------------------------------- 固定目录
STORAGE_DIR: Path = PROJECT_ROOT / "storage"
UPLOADS_DIR: Path = PROJECT_ROOT / "uploads"
ARCHIVE_DIR: Path = PROJECT_ROOT / "archive"

# 以下子目录由应用在启动时确保存在（见 server.py 的 makedirs）。
# 此处只声明**路径**，不做任何文件系统副作用——本模块应可被无副作用地导入，
# 否则「导入即建目录」会让测试和只读工具难以使用它。
STORAGE_SUBDIRS = (
    "storage/video_chunks",
    "storage/audio_chunks",
    "storage/snapshots",
)


def project_path(*parts: str) -> str:
    """返回 `PROJECT_ROOT` 下的路径（字符串形式）。

    保留字符串形式，是为了与仓库中大量既有的 `os.path.join(ROOT_DIR, ...)`
    调用点直接互换，让迁移可以逐处进行，而不必一次性重写所有调用。
    """
    return str(PROJECT_ROOT.joinpath(*parts))
