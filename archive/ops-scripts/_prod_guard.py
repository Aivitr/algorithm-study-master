"""归档运维脚本的「生产目标警示」——兑现「非阻塞警示」那一条约定。

为什么这些脚本需要它
--------------------
本目录的脚本都是**手动执行**的运维/维护脚本，它们绕开应用直接连数据库。
而本仓库工作区的 `.env` 指向**生产阿里云 RDS**。于是在工作区里敲一句：

    python init_db.py

就会对生产库执行 `CREATE TABLE` / `CREATE INDEX`。没有确认、没有提示、
没有 dry-run——`init_db.py` 原本就是这样写的。

这不是假设。同一类路径已有记录：`import database` 本身会在模块导入期执行
`_ensure_transcripts_columns()`（`database.py:243`），必要时对 `DATABASE_URL`
指向的库执行 `ALTER TABLE`。**导入动作即 DDL。**

为什么是「非阻塞」而不是一律拦下
--------------------------------
约定的是**非阻塞警示**。但纯打印的警示在这里几乎无用：脚本打印完下一行就
开始执行 DDL，操作者看到时事情已经发生。因此本模块取一个折中：

    - 目标是**本机/本地**（loopback 或 sqlite 文件）→ 只警示，照常继续
    - 目标是**远程**（如 *.rds.aliyuncs.com）→ **要求显式确认**

即：对本地开发零摩擦，对生产库必须有意识地放行。这比"一律放行"安全，
也比"一律拦下"更符合那条约定。

一个必须守住的细节：不能把凭据打进终端
--------------------------------------
`DATABASE_URL` 形如 `mssql+pymssql://user:password@host:port/db`，
**整串里含明文口令**。本模块打印前一律脱敏。这与另一处已暴露的问题同源——
那次是"响应里夹带 `.env` 凭据"，这里是"日志里夹带"，都属同一类泄露路径。
"""

import os
import sys
from pathlib import Path

_CONFIRM_ENV = "OPS_SCRIPT_CONFIRM"
_CONFIRM_FLAG = "--yes"


def _ensure_repo_root_on_path() -> None:
    """把仓库根挂上 sys.path。

    归档后这些脚本不再住在仓库根，直接运行会连 `import config` 都失败
    （`sys.path[0]` 变成了脚本自己所在的归档目录）。挂上仓库根，它们才仍然可用；
    这是有意的——这些是数据库维护工具，将来仍可能被需要。

    这也是为什么本模块**在导入时**就有副作用：调用方按下面三行的固定写法先
    定位并导入本模块，之后文件里原本的 `import config` / `import database`
    才得以成立。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "requirements.txt").exists() and (parent / "index.html").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return


_ensure_repo_root_on_path()

# 与 tests_safe/conftest.py 的网络兜底使用同一套回环判定，保持一致语义
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "", None}


def _redact(dsn: str) -> str:
    """抹掉 DSN 中的口令部分：`scheme://user:pass@host` -> `scheme://user:***@host`。"""
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, _, rest = dsn.partition("://")
    creds, _, host = rest.rpartition("@")
    if ":" in creds:
        user, _, _pwd = creds.partition(":")
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{host}"


def _remote_targets():
    """列出**实际会连的远程目标**。两条路径都要查——这正是那条约定的要点。"""
    found = []

    host = os.getenv("DB_HOST")
    if host and host not in _LOOPBACK:
        found.append(("DB_HOST", f"{host} (库名 {os.getenv('DB_NAME', '?')})"))

    dsn = os.getenv("DATABASE_URL", "") or ""
    if dsn and not dsn.lower().startswith("sqlite"):
        if not any(h in dsn.lower() for h in ("127.0.0.1", "localhost", "::1")):
            found.append(("DATABASE_URL", _redact(dsn)))

    return found


def guard(action: str) -> None:
    """在执行数据库操作**之前**调用。`action` 形如 "建表（CREATE TABLE / CREATE INDEX）"。"""
    remote = _remote_targets()

    line = "=" * 74
    print(line)
    print(f"[归档脚本] 即将执行：{action}")
    print("本脚本位于 archive/ops-scripts/，属已停止维护的历史运维脚本，")
    print("它绕开应用直连数据库——不经 ORM 的权限与校验，也没有事务保护。")

    if not remote:
        print("实际目标：本机或 sqlite 文件（未检出远程目标）——继续执行。")
        print(line)
        return

    print("实际目标：**远程数据库**")
    for key, desc in remote:
        print(f"    {key} = {desc}")
    print("注意：本仓库工作区的 .env 指向生产库。若上方的库不是你要操作的对象，")
    print("      现在按 Ctrl-C 中断，并改用 DEVELOPMENT 环境的配置。")

    confirmed = os.getenv(_CONFIRM_ENV) == "1" or _CONFIRM_FLAG in sys.argv
    if not confirmed:
        print()
        print(f"对远程库执行此操作需要显式确认。请二选一：")
        print(f"    python {os.path.basename(sys.argv[0] or 'script.py')} {_CONFIRM_FLAG}")
        print(f"    或设置环境变量 {_CONFIRM_ENV}=1")
        print(f"（此项为「非阻塞警示」那条约定的强化版：仅对**远程**目标要求确认，"
              f"本地目标不受影响。）")
        print(line)
        sys.exit(2)

    print("已确认，继续执行。")
    print(line)
