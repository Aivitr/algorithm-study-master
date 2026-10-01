
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

import os
from database import SessionLocal, EmotionLog  # 上面已把仓库根挂上 sys.path

guard("经 ORM 读取 emotion_logs 表中带 video_url 的记录（只读）")


def check_emotion_logs():
    db = SessionLocal()
    try:
        logs = db.query(EmotionLog).filter(EmotionLog.video_url.isnot(None)).order_by(EmotionLog.id.desc()).limit(10).all()
        print(f"Found {len(logs)} logs with video_url")
        for log in logs:
            print(f"ID: {log.id}, User ID: {log.user_id}, Video URL: {log.video_url}")
            # Check if local file exists
            if log.video_url and not log.video_url.startswith('http'):
                full_path = os.path.join(os.getcwd(), log.video_url.replace('/', os.sep))
                exists = os.path.exists(full_path)
                print(f"  Local file exists: {exists} ({full_path})")
    finally:
        db.close()

if __name__ == "__main__":
    check_emotion_logs()
