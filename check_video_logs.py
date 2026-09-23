
from database import SessionLocal, EmotionLog
import os

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
