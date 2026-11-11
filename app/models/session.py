"""登录会话与课堂占用锁。

- `user_sessions`：服务端签发的登录会话；只存 token 的 SHA-256，不存明文。
- `active_classroom_sessions`：当前正在某个课堂中的会话；唯一约束保证
  同一账号、同一浏览器 profile 都不能同时占用同一个课堂。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.models.base import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(128), nullable=False, index=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class ActiveClassroomSession(Base):
    __tablename__ = "active_classroom_sessions"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("user_sessions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(128), nullable=False, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False, index=True)
    claimed_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "meeting_id", name="uq_active_classroom_user_meeting"),
        UniqueConstraint("device_id", "meeting_id", name="uq_active_classroom_device_meeting"),
    )
