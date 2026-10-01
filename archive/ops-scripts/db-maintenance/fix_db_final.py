# fix_db_final.py
import os
import config  # 先加载 .env，确保 os.getenv 能读到 DATABASE_URL
from sqlalchemy import create_engine, text

# --- 归档防护：见 archive/ops-scripts/README.md ---
import pathlib as _pathlib
import sys as _sys
for _p in _pathlib.Path(__file__).resolve().parents:
    if (_p / "_prod_guard.py").exists():
        _sys.path.insert(0, str(_p))
        break
from _prod_guard import guard

guard("对 emotion_logs / transcripts 执行 ALTER TABLE 改列类型（写操作）")

# [EMOJI] MySQL [EMOJI]
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "")
engine = create_engine(SQLALCHEMY_DATABASE_URL)

print("[CONFIG] [EMOJI]...")
with engine.connect() as conn:
    try:
        # 1. [EMOJI] emotion_logs [EMOJI]
        conn.execute(text("ALTER TABLE emotion_logs MODIFY COLUMN emotion_type VARCHAR(100);"))
        # 2. [EMOJI] transcripts [EMOJI] ([EMOJI])
        conn.execute(text("ALTER TABLE transcripts MODIFY COLUMN emotion_tag VARCHAR(100);"))
        conn.execute(text("ALTER TABLE transcripts MODIFY COLUMN body_action VARCHAR(100);"))
        conn.execute(text("ALTER TABLE transcripts MODIFY COLUMN audio_tone VARCHAR(100);"))
        print("[OK] [EMOJI](20 -> 100)")
    except Exception as e:
        print(f"[WARN] [EMOJI] ([EMOJI]): {e}")