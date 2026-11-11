"""服务端登录会话与课堂占用校验。

设计边界：
- 同一账号全局只保留一个有效会话；新登录会撤销旧会话。
- 同一浏览器 profile（device_id）只保留一个账号会话；新账号登录会撤销该 profile 的旧会话。
- 同一账号、同一 device_id 都只能占用同一个课堂一次；由数据库唯一约束兜底。
- 只存 token 的 SHA-256；不存明文 token。

无法可靠判断“两个不同浏览器是否在同一台物理设备”，所以 device_id 是客户端
生成并存储的 profile 标识，不是硬件指纹；跨浏览器相同物理设备仍无法强校验。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ActiveClassroomSession, Meeting, User, UserSession

SESSION_TTL_HOURS = max(1, int(os.getenv("SESSION_TTL_HOURS", "12")))
_RUNNING = "running"


class ClassroomError(Exception):
    """课堂占用/授权失败；router 会转成 4xx。"""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class SessionContext:
    session: UserSession
    user: User


def _now() -> datetime:
    return datetime.now()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _revoke_sessions(db: Session, sessions: list[UserSession], now: datetime) -> list[int]:
    ids = [item.id for item in sessions if item.id]
    for item in sessions:
        item.revoked_at = now
    if ids:
        db.query(ActiveClassroomSession).filter(
            ActiveClassroomSession.session_id.in_(ids)
        ).delete(synchronize_session=False)
    return ids


def create_session(
    db: Session,
    user_id: int,
    device_id: str = "",
    user_agent: str = "",
) -> tuple[str, UserSession]:
    """撤销同账号/同 device 的旧会话，签发新 token。"""
    now = _now()
    device_id = (device_id or "").strip() or f"legacy-{uuid.uuid4().hex}"
    user_agent = (user_agent or "")[:512]

    active = (
        db.query(UserSession)
        .filter(
            UserSession.revoked_at.is_(None),
            or_(
                UserSession.user_id == user_id,
                UserSession.device_id == device_id,
            ),
        )
        .all()
    )
    _revoke_sessions(db, active, now)

    token = new_token()
    row = UserSession(
        token_hash=hash_token(token),
        user_id=user_id,
        device_id=device_id,
        user_agent=user_agent,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return token, row


def get_valid_session(db: Session, token: Optional[str], touch: bool = True) -> Optional[UserSession]:
    token = (token or "").strip()
    if not token:
        return None
    now = _now()
    row = (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_token(token))
        .first()
    )
    if row is None:
        return None
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= now:
        row.revoked_at = now
        db.commit()
        return None
    if touch:
        row.last_seen_at = now
        db.commit()
    return row


def session_context(db: Session, token: Optional[str], touch: bool = True) -> Optional[SessionContext]:
    row = get_valid_session(db, token, touch=touch)
    if row is None:
        return None
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        return None
    return SessionContext(session=row, user=user)


def require_session(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> SessionContext:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    ctx = session_context(db, token)
    if ctx is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return ctx


def revoke_session(db: Session, session: UserSession) -> None:
    now = _now()
    _revoke_sessions(db, [session], now)
    db.commit()


def _cleanup_stale_classroom_locks(db: Session, now: datetime) -> None:
    stale = (
        db.query(ActiveClassroomSession)
        .join(UserSession, UserSession.id == ActiveClassroomSession.session_id)
        .filter(
            or_(
                UserSession.revoked_at.isnot(None),
                UserSession.expires_at <= now,
            )
        )
        .all()
    )
    for row in stale:
        db.delete(row)
    if stale:
        db.flush()


def claim_classroom(db: Session, ctx: SessionContext, meeting_id: int) -> ActiveClassroomSession:
    now = _now()
    _cleanup_stale_classroom_locks(db, now)

    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise ClassroomError("课堂不存在", status_code=404)
    if meeting.status != _RUNNING:
        raise ClassroomError("课堂尚未开始或已经结束", status_code=409)
    if ctx.user.role == "teacher" and meeting.teacher_id != ctx.user.id:
        raise ClassroomError("只能进入自己创建的课堂", status_code=403)

    existing_user = (
        db.query(ActiveClassroomSession)
        .filter(
            ActiveClassroomSession.user_id == ctx.user.id,
            ActiveClassroomSession.meeting_id == meeting_id,
        )
        .first()
    )
    if existing_user is not None:
        if existing_user.session_id == ctx.session.id:
            return existing_user
        raise ClassroomError("该课堂已在其他窗口或设备打开", status_code=409)

    existing_device = (
        db.query(ActiveClassroomSession)
        .filter(
            ActiveClassroomSession.device_id == ctx.session.device_id,
            ActiveClassroomSession.meeting_id == meeting_id,
        )
        .first()
    )
    if existing_device is not None:
        if existing_device.session_id == ctx.session.id:
            return existing_device
        raise ClassroomError("该课堂已在本设备的其他窗口打开", status_code=409)

    row = ActiveClassroomSession(
        session_id=ctx.session.id,
        user_id=ctx.user.id,
        device_id=ctx.session.device_id,
        meeting_id=meeting_id,
        claimed_at=now,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        raise ClassroomError("该课堂已在其他窗口或设备打开", status_code=409)
    return row


def release_classroom(db: Session, session_id: int, meeting_id: int) -> int:
    deleted = (
        db.query(ActiveClassroomSession)
        .filter(
            ActiveClassroomSession.session_id == session_id,
            ActiveClassroomSession.meeting_id == meeting_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def release_all_for_meeting(db: Session, meeting_id: int) -> int:
    deleted = (
        db.query(ActiveClassroomSession)
        .filter(ActiveClassroomSession.meeting_id == meeting_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def websocket_context(db: Session, token: Optional[str], meeting_id: int) -> Optional[SessionContext]:
    ctx = session_context(db, token)
    if ctx is None:
        return None
    active = (
        db.query(ActiveClassroomSession)
        .filter(
            ActiveClassroomSession.session_id == ctx.session.id,
            ActiveClassroomSession.meeting_id == meeting_id,
        )
        .first()
    )
    if active is None:
        return None
    return ctx
