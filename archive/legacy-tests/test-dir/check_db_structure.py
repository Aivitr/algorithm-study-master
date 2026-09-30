"""
[EMOJI]
"""
import sqlite3
import os

db_path = 'storage/classroom.db'

try:
    if not os.path.exists(db_path):
        print(f"[ERROR] [EMOJI]: {db_path}")
        exit(1)
    
    print(f"[OK] [EMOJI]: {db_path}")
    print(f"   [EMOJI]: {os.path.getsize(db_path)} [EMOJI]\n")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # [EMOJI]
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    
    print("=" * 80)
    print("[STATS] [EMOJI]:")
    print("=" * 80)
    
    if not tables:
        print("[ERROR] [EMOJI]")
    else:
        for table in tables:
            table_name = table[0]
            print(f"\n[OK] [EMOJI]: {table_name}")
            
            # [EMOJI]
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            print("   [EMOJI]:")
            for col in columns:
                print(f"     - {col[1]} ({col[2]})")
            
            # [EMOJI]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"   [EMOJI]: {count}")
    
    conn.close()
    print("\n" + "=" * 80)
    print("[OK] [EMOJI]")
    
except Exception as e:
    print(f"[ERROR] [EMOJI]: {e}")
    import traceback
    traceback.print_exc()
