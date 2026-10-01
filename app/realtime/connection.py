"""课堂 WebSocket 连接管理器。

纯内存结构：不碰数据库、不碰网络、不读配置，模块级依赖只有 `time`。
"""

import time

# === WebSocket 连接管理器 (房间隔离) ===
class ConnectionManager:
    def __init__(self):
        self.active = []  # 所有连接
        self.meeting_connections = {}  # {meeting_id: {username: websocket}}
        self.last_speech_time = {}  # {meeting_id: timestamp} 最后发言时间
        self.speech_counts = {}  # {meeting_id: {username: count}} 发言计数
        self.silence_notified = {}  # {meeting_id: bool} 是否已通知沉默
        self.vote_confirmations = {}  # {vote_id: set(username)} 投票确认追踪

    async def connect(self, ws, meeting_id, username):
        await ws.accept()
        self.active.append(ws)
        if meeting_id not in self.meeting_connections:
            self.meeting_connections[meeting_id] = {}
        self.meeting_connections[meeting_id][username] = ws

    def disconnect(self, ws, meeting_id, username):
        if ws in self.active:
            self.active.remove(ws)
        if meeting_id in self.meeting_connections:
            if username in self.meeting_connections[meeting_id]:
                del self.meeting_connections[meeting_id][username]

    async def broadcast(self, msg):
        for cx in self.active:
            try:
                await cx.send_json(msg)
            except:
                pass

    async def broadcast_to_meeting(self, meeting_id, msg):
        """向指定课堂的所有成员广播消息"""
        if meeting_id not in self.meeting_connections:
            print(f"[WARN] 课堂{meeting_id}无连接")
            return

        print(f"[SEND] 广播到课堂{meeting_id}: {msg.get('type', 'unknown')}")
        success_count = 0
        fail_count = 0

        for username, ws in self.meeting_connections[meeting_id].items():
            try:
                await ws.send_json(msg)
                success_count += 1
                print(f"  [OK] 发送成功: {username}")
            except Exception as e:
                fail_count += 1
                print(f"  [ERROR] 发送失败: {username} - {type(e).__name__}: {e}")

        print(f"[STATS] 广播完成: 成功{success_count}, 失败{fail_count}")

    def get_online_members(self, meeting_id):
        """获取课堂在线成员列表"""
        if meeting_id in self.meeting_connections:
            return list(self.meeting_connections[meeting_id].keys())
        return []

    async def send_to_user(self, meeting_id, username, msg):
        """向指定课堂的指定用户发送消息"""
        if meeting_id in self.meeting_connections:
            ws = self.meeting_connections[meeting_id].get(username)
            if ws:
                try:
                    await ws.send_json(msg)
                except Exception as e:
                    print(f"[ERROR] 发送给{username}失败: {e}")

    def record_speech(self, meeting_id, username):
        """记录发言，更新计数和时间"""
        self.last_speech_time[meeting_id] = time.time()
        self.silence_notified[meeting_id] = False
        if meeting_id not in self.speech_counts:
            self.speech_counts[meeting_id] = {}
        self.speech_counts[meeting_id][username] = self.speech_counts[meeting_id].get(username, 0) + 1

    def get_quiet_members(self, meeting_id, threshold=2):
        """获取发言明显偏少的在线成员（相对比较）
        触发条件：
        1. 所有其他成员都已发言，该成员却0发言
        2. 该成员发言次数 < 其他成员平均发言次数的 30%
        3. 兜底：发言次数 < threshold（绝对阈值）且其他人都已超过
        """
        online = self.get_online_members(meeting_id)
        if len(online) < 2:
            return []
        counts = self.speech_counts.get(meeting_id, {})
        quiet = []
        all_counts = [counts.get(m, 0) for m in online]
        total_speeches = sum(all_counts)
        if total_speeches == 0:
            return []  # 没人发言过，不触发

        for m in online:
            my_count = counts.get(m, 0)
            others = [counts.get(o, 0) for o in online if o != m]
            others_avg = sum(others) / len(others) if others else 0
            all_others_spoken = all(c > 0 for c in others)

            # 条件1：其他人都发言了，自己0发言
            if my_count == 0 and all_others_spoken:
                quiet.append(m)
            # 条件2：自己发言次数 < 其他人平均的30%（且其他人平均>=3）
            elif others_avg >= 3 and my_count < others_avg * 0.3:
                quiet.append(m)
        return quiet

    def is_group_silent(self, meeting_id, silence_seconds=120):
        """检查课堂是否沉默超过指定秒数"""
        last = self.last_speech_time.get(meeting_id)
        if last is None:
            return False
        return (time.time() - last) >= silence_seconds
