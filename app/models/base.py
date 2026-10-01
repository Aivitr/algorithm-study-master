"""`declarative_base()` 的唯一实例。

`Base.metadata` 是**进程内唯一**的：重新导入 `app.core.database` 只是重新绑定到
同一个 `Base`，不会新造一个 metadata。
"""

from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
