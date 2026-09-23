# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # 先加载 .env，确保 os.getenv 能读到数据库配置
import pymssql

DB_CONFIG = {
    'server': os.getenv("DB_HOST", ""),
    'port': int(os.getenv("DB_PORT", "3433")),
    'user': os.getenv("DB_USER", ""),
    'password': os.getenv("DB_PASSWORD", ""),
    'database': os.getenv("DB_NAME", ""),
    'charset': 'utf8'
}

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
