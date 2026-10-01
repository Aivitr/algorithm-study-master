# -*- coding: utf-8 -*-
"""初始化数据库表结构"""
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

# SQL Server 建表语句
TABLES = [
    """
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
    CREATE TABLE users (
        id INT PRIMARY KEY IDENTITY(1,1),
        student_id VARCHAR(50) UNIQUE NOT NULL,
        username VARCHAR(50) NOT NULL,
        password VARCHAR(256) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'student',
        face_encoding NVARCHAR(MAX),
        created_at DATETIME DEFAULT GETDATE()
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_student_id' AND object_id = OBJECT_ID('users'))
    CREATE INDEX idx_student_id ON users(student_id)
    """,
    """
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='meetings' AND xtype='U')
    CREATE TABLE meetings (
        id INT PRIMARY KEY IDENTITY(1,1),
        class_code VARCHAR(50) UNIQUE NOT NULL,
        topic VARCHAR(200),
        lesson_plan NVARCHAR(MAX),
        goals NVARCHAR(MAX),
        status VARCHAR(20) DEFAULT 'active',
        created_at DATETIME DEFAULT GETDATE()
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_class_code' AND object_id = OBJECT_ID('meetings'))
    CREATE INDEX idx_class_code ON meetings(class_code)
    """,
    """
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='transcripts' AND xtype='U')
    CREATE TABLE transcripts (
        id INT PRIMARY KEY IDENTITY(1,1),
        meeting_id INT NOT NULL,
        user_id INT NOT NULL,
        text NVARCHAR(MAX),
        relevance_score FLOAT DEFAULT 0,
        quality_score FLOAT DEFAULT 50,
        timestamp DATETIME DEFAULT GETDATE()
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_meeting' AND object_id = OBJECT_ID('transcripts'))
    CREATE INDEX idx_meeting ON transcripts(meeting_id)
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_user' AND object_id = OBJECT_ID('transcripts'))
    CREATE INDEX idx_user ON transcripts(user_id)
    """,
    """
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='emotion_logs' AND xtype='U')
    CREATE TABLE emotion_logs (
        id INT PRIMARY KEY IDENTITY(1,1),
        meeting_id INT NOT NULL,
        user_id INT NOT NULL,
        emotion VARCHAR(50),
        confidence FLOAT,
        snapshot_path VARCHAR(500),
        video_url VARCHAR(500),
        video_start_time FLOAT DEFAULT 0,
        timestamp DATETIME DEFAULT GETDATE()
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_meeting_emotion' AND object_id = OBJECT_ID('emotion_logs'))
    CREATE INDEX idx_meeting_emotion ON emotion_logs(meeting_id)
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_user_emotion' AND object_id = OBJECT_ID('emotion_logs'))
    CREATE INDEX idx_user_emotion ON emotion_logs(user_id)
    """,
    """
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ai_insights' AND xtype='U')
    CREATE TABLE ai_insights (
        id INT PRIMARY KEY IDENTITY(1,1),
        meeting_id INT NOT NULL,
        user_id INT NOT NULL,
        insight_type VARCHAR(50),
        content NVARCHAR(MAX),
        timestamp DATETIME DEFAULT GETDATE()
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_meeting_insights' AND object_id = OBJECT_ID('ai_insights'))
    CREATE INDEX idx_meeting_insights ON ai_insights(meeting_id)
    """
]

guard("对数据库执行建表 DDL：CREATE TABLE / CREATE INDEX（共 11 条）")
print("正在初始化数据库...")
try:
    conn = pymssql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    for i, sql in enumerate(TABLES, 1):
        print(f"执行第 {i}/{len(TABLES)} 个表...")
        cursor.execute(sql)

    conn.commit()
    cursor.close()
    conn.close()

    print("\n数据库初始化完成!")
    print("\n提示：运行 python server.py 启动服务")

except Exception as e:
    print(f"错误：{e}")
