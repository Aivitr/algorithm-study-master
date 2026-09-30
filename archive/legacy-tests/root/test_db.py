"""[EMOJI]"""
import time
from database import SessionLocal, User

def test_db_connection():
    print("=" * 60)
    print("[EMOJI]")
    print("=" * 60)
    
    try:
        print("\n1[EMOJI]⃣ [EMOJI]...")
        start = time.time()
        db = SessionLocal()
        print(f"[OK] [EMOJI] ({time.time() - start:.2f}[EMOJI])")
        
        print("\n2[EMOJI]⃣ [EMOJI] (COUNT)...")
        start = time.time()
        count = db.query(User).count()
        print(f"[OK] [EMOJI]: {count} ({time.time() - start:.2f}[EMOJI])")
        
        print("\n3[EMOJI]⃣ [EMOJI]5[EMOJI]...")
        start = time.time()
        users = db.query(User).limit(5).all()
        print(f"[OK] [EMOJI] ({time.time() - start:.2f}[EMOJI])")
        
        if users:
            print("\n[EMOJI]:")
            for u in users:
                print(f"  - {u.student_id} | {u.username} | {u.role}")
        else:
            print("\n[WARN] [EMOJI]")
        
        print("\n4[EMOJI]⃣ [EMOJI]...")
        start = time.time()
        test_user = User(
            student_id=f"test_{int(time.time())}",
            username="[EMOJI]",
            password="123456",
            role="student"
        )
        db.add(test_user)
        db.commit()
        print(f"[OK] [EMOJI] ({time.time() - start:.2f}[EMOJI])")
        
        # [EMOJI]
        db.delete(test_user)
        db.commit()
        print("[OK] [EMOJI]")
        
        db.close()
        
        print("\n" + "=" * 60)
        print("[OK] [EMOJI]")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n[ERROR] [EMOJI]: {e}")
        import traceback
        traceback.print_exc()
        print("\n[EMOJI]:")
        print("  1. [EMOJI]")
        print("  2. [EMOJI]")
        print("  3. [EMOJI]")
        print("  4. [EMOJI]")
        print("\n" + "=" * 60)
        return False

if __name__ == "__main__":
    test_db_connection()
