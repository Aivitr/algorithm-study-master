"""用户查找。

`resolve_user_by_identifier` 让调用方用**学号或用户名**任一种标识定位用户：
先按 `User.student_id` 查，查不到再按 `User.username` 查。

全仓库有 5 处调用它，横跨三块互不相干的业务：实时链路（WebSocket 建转写记录）、
情绪统计（实时统计 / 情绪明细）、快照与视频上下文。因此它不能跟着其中一块走，
由各方直接导入（不能 `from server import ...`，见 `app/routers/__init__.py`）。
"""

from sqlalchemy.orm import Session

from app.models import User


def resolve_user_by_identifier(db: Session, identifier: str):
    if not identifier:
        return None
    user = db.query(User).filter(User.student_id == identifier).first()
    if user:
        return user
    return db.query(User).filter(User.username == identifier).first()
