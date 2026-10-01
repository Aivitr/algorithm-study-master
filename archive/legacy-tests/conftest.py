"""拒绝收集本目录下的任何测试——包括**显式指定路径**的那种收集。

为什么这个目录危险
------------------
本目录下的 `tests-dir/test_api_endpoints.py:2` 等文件顶部写着：

    from server import app

而 `server.py` → `database.py` 的**模块导入期**会执行
`_ensure_transcripts_columns()`（`database.py:243`），必要时对 `DATABASE_URL`
指向的库发出 `ALTER TABLE transcripts ADD ...`。

也就是说：**收集并导入这些文件 = 对生产库执行 DDL 的尝试。**

归档把这些文件从仓库根移到了一个**看起来更适合运行**的位置（名字里带 tests），
因此必须在此处补一道闸门。

三道闸门，以及各自实测过的边界
------------------------------
1. **仓库根 `conftest.py`（真正的安全网）**
   任何调用方式下都会加载，把 `DATABASE_URL` 换成 sqlite、`DB_*` 换成不可达值。
   即便下面两道全部失效、文件真被导入了，导入期的 DDL 也只落在临时目录。
   已实测：`pytest archive/... --collect-only` 的头部会打印
   `生产隔离：已生效 [DATABASE_URL -> sqlite:///.../smartclass-tests-*/app.db]`。

2. **本文件的 `pytest_configure` 参数检查（本目录专用硬闸门）**
   见下方实现。它不依赖 pytest 的收集语义，直接在会话开始时检查"你点的路径
   是不是本目录"，是就 `UsageError` 中止。**这一道会中止整个会话**——故意的。

3. **`collect_ignore` / `collect_ignore_glob`（兜底，边界最窄）**

### 实测否定的两种做法（记下来，免得以后有人再试）

- **`collect_ignore` 对显式文件路径无效。**
  它只在收集<目录>时被查询；显式给出文件路径时 pytest 绕过目录遍历。
  实测：修复前 `pytest archive/legacy-tests/tests-dir/test_api_endpoints.py
  --collect-only` → `3 tests collected in 3.59s`。

- **`pytest_ignore_collect` 同样无效**（这条更反直觉，故特别记下）。
  它不仅服务于目录遍历，看起来对所有路径都会被调用——但对**显式给出的参数**
  无效。原因是 pytest 把这些参数登记为 *init path*，并在收集时**有意**
  豁免它们的 ignore 检查（`Directory.collect()` 里对 `isinitpath` 的分支）：
  "用户明确点名要跑的东西，不要偷偷跳过"。
  实测：在 `pytest_ignore_collect` 里无条件 `return True` 之后，
  同一条命令仍然 `collected 3 items`。

结论：**凡是"显式点名"的路径，任何基于收集钩子的闸门都不成立。**
所以第 2 道闸门改在 `pytest_configure` 里直接看参数——那才是"点名"发生的地方。

修复前的那次事故
----------------
`pytest archive/legacy-tests/tests-dir/test_api_endpoints.py --collect-only` 确实
收集了 3 个测试（3.59s，一次真实的 `import server` → `import database`）。
当时输出被 `tail -4` 截断，**因此无法确认 `ALTER TABLE` 是否真的执行过**。
此事在本目录 `README.md` 的「事故记录」一节里如实记着。
"""

from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent


# 第 3 道：兜底。路径明确、语义清楚，但只管"按目录收集"。
collect_ignore = ["root", "tests-dir", "test-dir"]
collect_ignore_glob = ["*"]


# 第 2 道：真正拦得住"显式点名"的那一道。
def pytest_configure(config):
    """若本次调用的参数落在本目录内，立即中止整个会话。

    为什么不放在收集钩子里：见文件头"实测否定的两种做法"。显式参数是
    *init path*，pytest 有意对它们豁免一切 ignore 检查，因此只能在这里从
    参数本身判断。

    这里**故意用中止而不是"跳过"**：本目录没有任何测试应当运行，
    静默跳过会让下一个人以为"跑过了、没问题"。中止则留下明确记录。
    """
    offenders = []
    for arg in config.invocation_params.args:
        if arg.startswith("-"):
            continue
        candidate = Path(arg)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate == _HERE or _HERE in candidate.parents:
            offenders.append(arg)

    if not offenders:
        return

    raise pytest.UsageError(
        "\n".join(
            [
                "",
                "=" * 72,
                "拒绝收集：本次参数指向 archive/legacy-tests/（历史归档测试）。",
                "=" * 72,
                f"  参数：{', '.join(offenders)}",
                f"  目录：{_HERE}",
                "",
                "这些文件顶部 `from server import app`，而 `server` → `database`",
                "的模块导入期会执行 `_ensure_transcripts_columns()`",
                "（database.py:243），必要时对 DATABASE_URL 指向的库执行",
                "`ALTER TABLE transcripts ADD ...`。**收集它们 = 尝试对生产库做 DDL。**",
                "",
                "它们已归档、不再维护，不会通过。若你确实要阅读它们的行为，",
                "请直接读源码；若要运行，请先把 .env 指向开发库。",
                "=" * 72,
                "",
            ]
        )
    )
