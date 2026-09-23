"""
[EMOJI]emotion_logs[EMOJI]
"""
import sqlite3
from datetime import datetime

db_path = 'storage/classroom.db'

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=" * 80)
    print("[STATS] [EMOJI] emotion_logs [EMOJI]")
    print("=" * 80)
    
    # [EMOJI]
    cursor.execute("""
        SELECT 
            e.id, 
            e.meeting_id,
            e.user_id,
            u.username,
            e.emotion_type,
            e.video_url,
            e.video_start_time,
            e.created_at
        FROM emotion_logs e
        LEFT JOIN users u ON e.user_id = u.id
        ORDER BY e.created_at DESC
        LIMIT 10
    """)
    
    rows = cursor.fetchall()
    
    if not rows:
        print("[ERROR] [EMOJI]")
    else:
        print(f"[OK] [EMOJI] {len(rows)} [EMOJI]:\n")
        for row in rows:
            id, meeting_id, user_id, username, emotion_type, video_url, video_start_time, created_at = row
            print(f"ID: {id}")
            print(f"  Meeting ID: {meeting_id}")
            print(f"  User: {username} (ID: {user_id})")
            print(f"  [EMOJI]: {emotion_type}")
            print(f"  [EMOJI]URL: {video_url}")
            print(f"  [EMOJI]: {video_start_time}")
            print(f"  [EMOJI]: {created_at}")
            
            # [EMOJI]
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    timestamp_ms = int(dt.timestamp() * 1000)
                    print(f"  [EMOJI]([EMOJI]): {timestamp_ms}")
                except Exception as e:
                    print(f"  [EMOJI]: {e}")
            
            print("-" * 80)
    
    # [EMOJI]video_url[EMOJI]
    cursor.execute("""
        SELECT COUNT(*) FROM emotion_logs WHERE video_url IS NOT NULL
    """)
    count = cursor.fetchone()[0]
    print(f"\n[CAMERA] [EMOJI]URL[EMOJI]: {count}")
    
    # [EMOJI]
    cursor.execute("""
        SELECT username FROM users ORDER BY id DESC LIMIT 5
    """)
    users = cursor.fetchall()
    print(f"\n[USERS] [EMOJI]:")
    for user in users:
        print(f"  - {user[0]}")
    
    conn.close()
    print("\n[OK] [EMOJI]")
    
except Exception as e:
    print(f"[ERROR] [EMOJI]: {e}")
    import traceback
    traceback.print_exc()
