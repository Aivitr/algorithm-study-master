"""唯一的路径解析来源。

解析策略
--------
不靠 `__file__` 的层级数（那只是把同一个耦合换个写法），而是**从本文件所在
位置向上搜索哨兵文件**。哨兵要求三件同时存在；找不到则抛错——宁可启动失败，
也不要静默指错目录。

`PROJECT_ROOT` 因此与本文件被放在何处无关：它可以在 `app/` 下任意深度，
只要仓库根的三件哨兵还在，解析结果就不变。
"""

from pathlib import Path

# 哨兵：三者需同时存在于仓库根。
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
# 此处只声明**路径**，不做任何文件系统副作用——本模块应可被无副作用地导入。
STORAGE_SUBDIRS = (
    "storage/video_chunks",
    "storage/audio_chunks",
    "storage/snapshots",
)


def project_path(*parts: str) -> str:
    """返回 `PROJECT_ROOT` 下的路径（字符串形式）。

    字符串形式与仓库中既有的 `os.path.join(ROOT_DIR, ...)` 调用点可直接互换。
    """
    return str(PROJECT_ROOT.joinpath(*parts))
