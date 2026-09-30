"""`declarative_base()` 的唯一实例。

阶段 3.1 之前它住在仓库根的 `database.py`。放在这里，是因为它是**所有**模型的
共同底座，而那个文件还兼着引擎、会话、迁移三件事——那三件已在阶段 3.2 随它
迁到 `app/core/database.py`，与模型彻底分开。

单独成模块还有一个实际好处：`Base.metadata` 是**进程内唯一**的。原先每重新
导入一次 `database`（测试里用 `module_surgery` 干过这事）就会新造一个 metadata，
现在不会了——重新导入 `app.core.database` 只是重新绑定到同一个 `Base`。
"""

from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
