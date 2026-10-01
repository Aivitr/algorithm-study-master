# -*- coding: utf-8 -*-
import os
# --- 归档防护：见 archive/ops-scripts/README.md ---
# 三个动作合一：定位 _prod_guard、挂上仓库根（使下方 import config 仍可用）、
# 在执行任何数据库操作前先打印实际目标并（仅对远程库）要求确认。
import pathlib as _pathlib
import sys as _sys
for _p in _pathlib.Path(__file__).resolve().parents:
    if (_p / "_prod_guard.py").exists():
        _sys.path.insert(0, str(_p))
        break
from _prod_guard import guard
import config  # noqa: F401  ——挂 sys.path 后此导入才成立

import pymssql

DB_CONFIG = {
    'server': os.getenv("DB_HOST", ""),
    'port': int(os.getenv("DB_PORT", "3433")),
    'user': os.getenv("DB_USER", ""),
    'password': os.getenv("DB_PASSWORD", ""),
    'database': os.getenv("DB_NAME", ""),
    'charset': 'utf8'
}

guard("读取 users 表内容（只读）")
print("Checking users in database...")
try:
    conn = pymssql.connect(**DB_CONFIG)
    cursor = conn.cursor(as_dict=True)

    cursor.execute("SELECT id, student_id, username, role FROM users")
    users = cursor.fetchall()

    print(f"\nFound {len(users)} users:")
    for user in users:
        print(f"  ID: {user['id']}, Student ID: {user['student_id']}, Name: {user['username']}, Role: {user['role']}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"Error: {e}")
