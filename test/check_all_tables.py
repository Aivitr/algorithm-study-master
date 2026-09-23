# -*- coding: utf-8 -*-
"""检查数据库表结构"""
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

print("正在连接数据库...")
try:
    conn = pymssql.connect(**DB_CONFIG)
    cursor = conn.cursor(as_dict=True)

    # 获取所有表
    print("\n=== 数据库表列表 ===")
    cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME")
    tables = cursor.fetchall()
    for table in tables:
        print(f"  - {table['TABLE_NAME']}")

    # 检查 transcripts 表结构
    print("\n=== transcripts 表结构 ===")
    cursor.execute("SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='transcripts' ORDER BY ORDINAL_POSITION")
    columns = cursor.fetchall()
    for col in columns:
        nullable = 'NULL' if col['IS_NULLABLE'] == 'YES' else 'NOT NULL'
        print(f"  {col['COLUMN_NAME']} ({col['DATA_TYPE']}) {nullable}")

    # 检查 emotion_logs 表结构
    print("\n=== emotion_logs 表结构 ===")
    cursor.execute("SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='emotion_logs' ORDER BY ORDINAL_POSITION")
    columns = cursor.fetchall()
    for col in columns:
        nullable = 'NULL' if col['IS_NULLABLE'] == 'YES' else 'NOT NULL'
        print(f"  {col['COLUMN_NAME']} ({col['DATA_TYPE']}) {nullable}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"错误：{e}")
