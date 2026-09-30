"""全局隔离：在导入任何项目模块之前，把 DATABASE_URL 指向本地临时库。

为什么必须放在 conftest 而不是各个测试里
----------------------------------------
`database.py` 在**模块导入时**就执行 `_ensure_transcripts_columns()`
（`database.py:243`），该函数会对 `DATABASE_URL` 指向的库执行 inspect，
必要时执行 `ALTER TABLE transcripts ADD ...`。

也就是说：**`import database` 这一个动作本身，就可能在生产库上执行 DDL。**
任何"先跑起来看看"的测试，只要在导入时还连着生产库，就已经越界了。

因此隔离必须发生在**测试模块导入之前**——conftest.py 由 pytest 在收集阶段
最先加载，正是唯一可靠的插入点。

为什么不需要改动 .env
---------------------
`config._load_dotenv()` 使用 `os.environ.setdefault`，预先存在的环境变量优先。
所以此处预设 DATABASE_URL 即可切换数据库，`.env` 文件保持原样、不被触碰。
"""

import os
import tempfile
from pathlib import Path

_SESSION_TMP = Path(tempfile.mkdtemp(prefix="smartclass-tests-"))

# 必须在任何项目模块被导入之前设置
os.environ["DATABASE_URL"] = f"sqlite:///{(_SESSION_TMP / 'app.db').as_posix()}"
