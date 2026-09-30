"""[EMOJI]"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_register():
    """[EMOJI]"""
    print("=" * 50)
    print("[EMOJI]")
    print("=" * 50)
    
    data = {
        'student_id': 'test001',
        'username': '[EMOJI]',
        'password': '123456',
        'role': 'student'
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/register", data=data)
        print(f"[EMOJI]: {response.status_code}")
        print(f"[EMOJI]: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
        return response.json()
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return None

def test_login():
    """[EMOJI]"""
    print("\n" + "=" * 50)
    print("[EMOJI]")
    print("=" * 50)
    
    data = {
        'student_id': 'test001',
        'password': '123456'
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/login", data=data)
        print(f"[EMOJI]: {response.status_code}")
        print(f"[EMOJI]: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
        return response.json()
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return None

def test_db_connection():
    """[EMOJI]"""
    print("\n" + "=" * 50)
    print("[EMOJI]")
    print("=" * 50)
    
    try:
        from database import SessionLocal, User
        db = SessionLocal()
        users = db.query(User).all()
        print(f"[OK] [EMOJI]")
        print(f"[EMOJI]: {len(users)}")
        if users:
            print("\n[EMOJI]:")
            for user in users[:5]:  # [EMOJI]5[EMOJI]
                print(f"  - {user.student_id} | {user.username} | {user.role}")
        db.close()
        return True
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return False

if __name__ == "__main__":
    print("[ZOOM] [EMOJI]...\n")
    
    # 1. [EMOJI]
    db_ok = test_db_connection()
    
    if db_ok:
        # 2. [EMOJI]
        register_result = test_register()
        
        # 3. [EMOJI]
        login_result = test_login()
        
        print("\n" + "=" * 50)
        print("[EMOJI]")
        print("=" * 50)
        if login_result and login_result.get('status') == 'success':
            print("[OK] [EMOJI]")
        else:
            print("[ERROR] [EMOJI]")
            print("[EMOJI]:")
            print("  1. [EMOJI]")
            print("  2. [EMOJI]")
            print("  3. [EMOJI]")
    else:
        print("\n[ERROR] [EMOJI] database.py [EMOJI]")
