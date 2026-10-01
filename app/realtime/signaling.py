"""WebRTC 信令转发。

仅转发 JSON（offer / answer / ICE），不解析 SDP——服务端在这一链路上是纯粹的
中转，因此本类与 `connection.py` 一样是纯内存的。
"""

from fastapi import WebSocket


# === WebRTC 信令（仅转发 JSON，不处理 SDP）===
class SignalConnectionManager:
    """按课堂隔离，将 offer/answer/ICE 点对点转发给目标用户。"""

    def __init__(self):
        self.meeting_connections = {}  # {meeting_id: {username: WebSocket}}

    async def register(self, websocket: WebSocket, meeting_id: int, username: str):
        await websocket.accept()
        if meeting_id not in self.meeting_connections:
            self.meeting_connections[meeting_id] = {}
        self.meeting_connections[meeting_id][username] = websocket

    def unregister(self, meeting_id: int, username: str):
        if meeting_id in self.meeting_connections and username in self.meeting_connections[meeting_id]:
            del self.meeting_connections[meeting_id][username]

    async def forward_to(self, meeting_id: int, target_username: str, msg: dict) -> bool:
        ws = self.meeting_connections.get(meeting_id, {}).get(target_username)
        if not ws:
            return False
        try:
            await ws.send_json(msg)
            return True
        except Exception:
            return False
