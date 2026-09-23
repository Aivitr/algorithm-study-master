"""
[EMOJI]
[EMOJI]10-50[EMOJI]
"""
import asyncio
import aiohttp
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

class VirtualStudent:
    """[EMOJI]"""
    
    def __init__(self, username, class_code, student_id):
        self.username = username
        self.class_code = class_code
        self.student_id = student_id
        self.meeting_id = None
        self.ws = None
        self.session = None
        self.message_count = 0
        self.start_time = None
        
    async def login(self):
        """[EMOJI]"""
        try:
            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                data.add_field('username', self.username)
                data.add_field('class_code', self.class_code)
                data.add_field('role', 'student')
                
                async with session.post(f"{BASE_URL}/login", data=data) as resp:
                    result = await resp.json()
                    if result.get('status') == 'success':
                        self.meeting_id = result.get('meeting_id')
                        print(f"[OK] [{self.username}] [EMOJI], meeting_id={self.meeting_id}")
                        return True
                    else:
                        print(f"[ERROR] [{self.username}] [EMOJI]: {result.get('message')}")
                        return False
        except Exception as e:
            print(f"[ERROR] [{self.username}] [EMOJI]: {e}")
            return False
    
    async def connect_websocket(self):
        """[EMOJI]WebSocket"""
        try:
            self.session = aiohttp.ClientSession()
            self.ws = await self.session.ws_connect(
                f"{WS_URL}/ws/{self.username}/{self.meeting_id}"
            )
            self.start_time = time.time()
            print(f"[DB] [{self.username}] WebSocket[EMOJI]")
            return True
        except Exception as e:
            print(f"[ERROR] [{self.username}] WebSocket[EMOJI]: {e}")
            return False
    
    async def receive_messages(self, duration=30):
        """[EMOJI]"""
        try:
            timeout = time.time() + duration
            while time.time() < timeout:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=5.0)
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    self.message_count += 1
                    
                    if data.get('type') == 'new_speech_fast':
                        print(f"[EMOJI] [{self.username}] [EMOJI]: {data.get('username')} - {data.get('text')[:30]}...")
                    elif data.get('type') == 'knowledge_graph_update':
                        print(f"[WEB] [{self.username}] [EMOJI]")
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print(f"[REC] [{self.username}] WebSocket[EMOJI]")
                    break
                    
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"[WARN] [{self.username}] [EMOJI]: {e}")
        finally:
            elapsed = time.time() - self.start_time
            print(f"[STATS] [{self.username}] [EMOJI] - [EMOJI]{self.message_count}[EMOJI], [EMOJI]{elapsed:.2f}[EMOJI]")
    
    async def close(self):
        """[EMOJI]"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

async def test_concurrent_users(num_users=10, duration=30):
    """
    [EMOJI]
    
    Args:
        num_users: [EMOJI]
        duration: [EMOJI]([EMOJI])
    """
    class_code = f"TEST_{int(time.time())}"
    
    print(f"\n{'='*60}")
    print(f"[EMOJI] [EMOJI]")
    print(f"   [EMOJI]: {num_users}")
    print(f"   [EMOJI]: {class_code}")
    print(f"   [EMOJI]: {duration}[EMOJI]")
    print(f"{'='*60}\n")
    
    # [EMOJI]
    print("[NOTE] [EMOJI]...")
    teacher_created = False
    try:
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field('username', 'Teacher_Test')
            data.add_field('class_code', class_code)
            data.add_field('role', 'teacher')
            data.add_field('topic', '[EMOJI] - [EMOJI]')
            
            async with session.post(f"{BASE_URL}/login", data=data) as resp:
                result = await resp.json()
                if result.get('status') == 'success':
                    print(f"[OK] [EMOJI]: meeting_id={result.get('meeting_id')}")
                    teacher_created = True
                else:
                    print(f"[ERROR] [EMOJI]: {result}")
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
    
    if not teacher_created:
        print("[ERROR] [EMOJI],[EMOJI]")
        return
    
    await asyncio.sleep(2)
    
    # [EMOJI]
    students = [
        VirtualStudent(f"Student_{i:03d}", class_code, i)
        for i in range(1, num_users + 1)
    ]
    
    # [EMOJI]
    print(f"\n[FAST] [EMOJI] {num_users} [EMOJI]...")
    login_start = time.time()
    login_tasks = [student.login() for student in students]
    login_results = await asyncio.gather(*login_tasks)
    login_duration = time.time() - login_start
    
    success_count = sum(login_results)
    print(f"\n[STATS] [EMOJI]:")
    print(f"   [EMOJI]: {success_count}/{num_users}")
    print(f"   [EMOJI]: {login_duration:.2f}[EMOJI]")
    print(f"   [EMOJI]: {login_duration/num_users:.3f}[EMOJI]/[EMOJI]\n")
    
    if success_count == 0:
        print("[ERROR] [EMOJI],[EMOJI]")
        return
    
    # [EMOJI]WebSocket
    print(f"[DB] [EMOJI]WebSocket[EMOJI]...")
    ws_start = time.time()
    ws_tasks = [student.connect_websocket() for student in students if student.meeting_id]
    ws_results = await asyncio.gather(*ws_tasks)
    ws_duration = time.time() - ws_start
    
    ws_success = sum(ws_results)
    print(f"\n[STATS] WebSocket[EMOJI]:")
    print(f"   [EMOJI]: {ws_success}/{success_count}")
    print(f"   [EMOJI]: {ws_duration:.2f}[EMOJI]\n")
    
    if ws_success == 0:
        print("[ERROR] [EMOJI]WebSocket[EMOJI],[EMOJI]")
        return
    
    # [EMOJI]
    print(f"[EMOJI] [EMOJI] ([EMOJI]{duration}[EMOJI])...\n")
    receive_tasks = [
        student.receive_messages(duration) 
        for student in students 
        if student.ws
    ]
    
    await asyncio.gather(*receive_tasks)
    
    # [EMOJI]
    total_messages = sum(s.message_count for s in students)
    active_students = [s for s in students if s.message_count > 0]
    
    print(f"\n{'='*60}")
    print(f"[STATS] [EMOJI]")
    print(f"{'='*60}")
    print(f"[OK] [EMOJI]: {success_count}/{num_users}")
    print(f"[OK] [EMOJI]WebSocket: {ws_success}/{success_count}")
    print(f"[OK] [EMOJI]: {len(active_students)}/{ws_success}")
    print(f"[EMOJI] [EMOJI]: {total_messages}")
    if active_students:
        print(f"[STATS] [EMOJI]: {total_messages/len(active_students):.1f}[EMOJI]")
    print(f"[TIME]  [EMOJI]: {time.time() - login_start:.2f}[EMOJI]")
    print(f"{'='*60}\n")
    
    # [EMOJI]
    print("[EMOJI] [EMOJI]...")
    close_tasks = [student.close() for student in students]
    await asyncio.gather(*close_tasks)
    
    print("[OK] [EMOJI]!\n")

async def main():
    """[EMOJI]"""
    # [EMOJI]
    test_cases = [
        (5, 20),   # 5[EMOJI], 20[EMOJI]
        (10, 30),  # 10[EMOJI], 30[EMOJI]
        (20, 30),  # 20[EMOJI], 30[EMOJI]
    ]
    
    for num_users, duration in test_cases:
        await test_concurrent_users(num_users, duration)
        print("\n" + "="*60 + "\n")
        await asyncio.sleep(5)  # [EMOJI]

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"[TARGET] [EMOJI] - [EMOJI]")
    print(f"   [EMOJI]: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n[WARN] [EMOJI]")
    except Exception as e:
        print(f"\n\n[ERROR] [EMOJI]: {e}")
"""
[EMOJI]
[EMOJI]10-50[EMOJI]
"""
import asyncio
import aiohttp
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

class VirtualStudent:
    """[EMOJI]"""
    
    def __init__(self, username, class_code, student_id):
        self.username = username
        self.class_code = class_code
        self.student_id = student_id
        self.meeting_id = None
        self.ws = None
        self.session = None
        self.message_count = 0
        self.start_time = None
        
    async def login(self):
        """[EMOJI]"""
        try:
            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                data.add_field('username', self.username)
                data.add_field('class_code', self.class_code)
                data.add_field('role', 'student')
                
                async with session.post(f"{BASE_URL}/login", data=data) as resp:
                    result = await resp.json()
                    if result.get('status') == 'success':
                        self.meeting_id = result.get('meeting_id')
                        print(f"[OK] [{self.username}] [EMOJI], meeting_id={self.meeting_id}")
                        return True
                    else:
                        print(f"[ERROR] [{self.username}] [EMOJI]: {result.get('message')}")
                        return False
        except Exception as e:
            print(f"[ERROR] [{self.username}] [EMOJI]: {e}")
            return False
    
    async def connect_websocket(self):
        """[EMOJI]WebSocket"""
        try:
            self.session = aiohttp.ClientSession()
            self.ws = await self.session.ws_connect(
                f"{WS_URL}/ws/{self.username}/{self.meeting_id}"
            )
            self.start_time = time.time()
            print(f"[DB] [{self.username}] WebSocket[EMOJI]")
            return True
        except Exception as e:
            print(f"[ERROR] [{self.username}] WebSocket[EMOJI]: {e}")
            return False
    
    async def receive_messages(self, duration=30):
        """[EMOJI]"""
        try:
            timeout = time.time() + duration
            while time.time() < timeout:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=5.0)
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    self.message_count += 1
                    
                    if data.get('type') == 'new_speech_fast':
                        print(f"[EMOJI] [{self.username}] [EMOJI]: {data.get('username')} - {data.get('text')[:30]}...")
                    elif data.get('type') == 'knowledge_graph_update':
                        print(f"[WEB] [{self.username}] [EMOJI]")
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print(f"[REC] [{self.username}] WebSocket[EMOJI]")
                    break
                    
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"[WARN] [{self.username}] [EMOJI]: {e}")
        finally:
            elapsed = time.time() - self.start_time
            print(f"[STATS] [{self.username}] [EMOJI] - [EMOJI]{self.message_count}[EMOJI], [EMOJI]{elapsed:.2f}[EMOJI]")
    
    async def close(self):
        """[EMOJI]"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

async def test_concurrent_users(num_users=10, duration=30):
    """
    [EMOJI]
    
    Args:
        num_users: [EMOJI]
        duration: [EMOJI]([EMOJI])
    """
    class_code = f"TEST_{int(time.time())}"
    
    print(f"\n{'='*60}")
    print(f"[EMOJI] [EMOJI]")
    print(f"   [EMOJI]: {num_users}")
    print(f"   [EMOJI]: {class_code}")
    print(f"   [EMOJI]: {duration}[EMOJI]")
    print(f"{'='*60}\n")
    
    # [EMOJI]
    print("[NOTE] [EMOJI]...")
    teacher_created = False
    try:
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field('username', 'Teacher_Test')
            data.add_field('class_code', class_code)
            data.add_field('role', 'teacher')
            data.add_field('topic', '[EMOJI] - [EMOJI]')
            
            async with session.post(f"{BASE_URL}/login", data=data) as resp:
                result = await resp.json()
                if result.get('status') == 'success':
                    print(f"[OK] [EMOJI]: meeting_id={result.get('meeting_id')}")
                    teacher_created = True
                else:
                    print(f"[ERROR] [EMOJI]: {result}")
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
    
    if not teacher_created:
        print("[ERROR] [EMOJI],[EMOJI]")
        return
    
    await asyncio.sleep(2)
    
    # [EMOJI]
    students = [
        VirtualStudent(f"Student_{i:03d}", class_code, i)
        for i in range(1, num_users + 1)
    ]
    
    # [EMOJI]
    print(f"\n[FAST] [EMOJI] {num_users} [EMOJI]...")
    login_start = time.time()
    login_tasks = [student.login() for student in students]
    login_results = await asyncio.gather(*login_tasks)
    login_duration = time.time() - login_start
    
    success_count = sum(login_results)
    print(f"\n[STATS] [EMOJI]:")
    print(f"   [EMOJI]: {success_count}/{num_users}")
    print(f"   [EMOJI]: {login_duration:.2f}[EMOJI]")
    print(f"   [EMOJI]: {login_duration/num_users:.3f}[EMOJI]/[EMOJI]\n")
    
    if success_count == 0:
        print("[ERROR] [EMOJI],[EMOJI]")
        return
    
    # [EMOJI]WebSocket
    print(f"[DB] [EMOJI]WebSocket[EMOJI]...")
    ws_start = time.time()
    ws_tasks = [student.connect_websocket() for student in students if student.meeting_id]
    ws_results = await asyncio.gather(*ws_tasks)
    ws_duration = time.time() - ws_start
    
    ws_success = sum(ws_results)
    print(f"\n[STATS] WebSocket[EMOJI]:")
    print(f"   [EMOJI]: {ws_success}/{success_count}")
    print(f"   [EMOJI]: {ws_duration:.2f}[EMOJI]\n")
    
    if ws_success == 0:
        print("[ERROR] [EMOJI]WebSocket[EMOJI],[EMOJI]")
        return
    
    # [EMOJI]
    print(f"[EMOJI] [EMOJI] ([EMOJI]{duration}[EMOJI])...\n")
    receive_tasks = [
        student.receive_messages(duration) 
        for student in students 
        if student.ws
    ]
    
    await asyncio.gather(*receive_tasks)
    
    # [EMOJI]
    total_messages = sum(s.message_count for s in students)
    active_students = [s for s in students if s.message_count > 0]
    
    print(f"\n{'='*60}")
    print(f"[STATS] [EMOJI]")
    print(f"{'='*60}")
    print(f"[OK] [EMOJI]: {success_count}/{num_users}")
    print(f"[OK] [EMOJI]WebSocket: {ws_success}/{success_count}")
    print(f"[OK] [EMOJI]: {len(active_students)}/{ws_success}")
    print(f"[EMOJI] [EMOJI]: {total_messages}")
    if active_students:
        print(f"[STATS] [EMOJI]: {total_messages/len(active_students):.1f}[EMOJI]")
    print(f"[TIME]  [EMOJI]: {time.time() - login_start:.2f}[EMOJI]")
    print(f"{'='*60}\n")
    
    # [EMOJI]
    print("[EMOJI] [EMOJI]...")
    close_tasks = [student.close() for student in students]
    await asyncio.gather(*close_tasks)
    
    print("[OK] [EMOJI]!\n")

async def main():
    """[EMOJI]"""
    # [EMOJI]
    test_cases = [
        (5, 20),   # 5[EMOJI], 20[EMOJI]
        (10, 30),  # 10[EMOJI], 30[EMOJI]
        (20, 30),  # 20[EMOJI], 30[EMOJI]
    ]
    
    for num_users, duration in test_cases:
        await test_concurrent_users(num_users, duration)
        print("\n" + "="*60 + "\n")
        await asyncio.sleep(5)  # [EMOJI]

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"[TARGET] [EMOJI] - [EMOJI]")
    print(f"   [EMOJI]: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n[WARN] [EMOJI]")
    except Exception as e:
        print(f"\n\n[ERROR] [EMOJI]: {e}")
