# -*- coding: utf-8 -*-
"""检查 users 表"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # 先加载 .env，确保 os.getenv 能读到数据库配置
import pymssql

conn = pymssql.connect(
    server=os.getenv("DB_HOST", ""),
    port=int(os.getenv("DB_PORT", "3433")),
    user=os.getenv("DB_USER", ""),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", ""),
    charset='utf8'
)
cursor = conn.cursor(as_dict=True)
cursor.execute('SELECT * FROM users')
users = cursor.fetchall()

print(f'共 {len(users)} 个用户:')
for u in users:
    print(f'  ID:{u["id"]} 学号:{u["student_id"]} 姓名:{u["username"]} 角色:{u["role"]}')

conn.close()
