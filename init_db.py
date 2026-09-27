# -*- coding: utf-8 -*-
"""初始化数据库表结构。

建表语句的唯一来源是 database.py 里的 ORM 模型：本脚本只调用
Base.metadata.create_all()，所以建出来的表名/列名/类型/索引与程序实际
使用的 ORM 定义必然一致，不会再出现"脚本建的表程序认不出来"。

（旧版这里是手写的 4 条 T-SQL CREATE TABLE，已经和模型严重脱节：
 meetings.topic 写成 VARCHAR(200) 而模型是 UnicodeText、transcripts.text
 而模型是 content、emotion_logs.emotion 而模型是 emotion_type、
 ai_insights.user_id 而模型是 target_user …… 用旧脚本建出来的库，
 server.py 一跑就是"列名无效"。而且它只建 4 张表，模型里有 15 张。
 另外那些手写 DDL 里的 VARCHAR 中文列也踩了 FreeTDS 代码页问题，
 详见 database.py 顶部的说明。）

连接信息只读 DATABASE_URL，与 server.py 完全一致：
    mssql+pymssql://<user>:<password>@<host>:3433/<db>?charset=utf8
留空则建到本地 SQLite（storage/app.db）。

create_all 是幂等的：已存在的表不会被修改，可以反复执行。

用法:
    python init_db.py
"""
import config  # 先加载 .env，确保 os.getenv 能读到 DATABASE_URL
from database import Base, engine, SQLALCHEMY_DATABASE_URL


def _mask_password(url: str) -> str:
    """打印连接串时抹掉密码。"""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    cred, host = rest.rsplit("@", 1)
    user = cred.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


if __name__ == "__main__":
    print("正在初始化数据库...")
    print(f"  目标: {_mask_password(SQLALCHEMY_DATABASE_URL)}  (方言: {engine.dialect.name})")

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        raise SystemExit(f"错误：{e}")

    tables = sorted(Base.metadata.tables.keys())
    print(f"\n数据库初始化完成，共 {len(tables)} 张表：")
    for name in tables:
        print(f"  - {name}")
    print("\n提示：运行 python server.py 启动服务")
