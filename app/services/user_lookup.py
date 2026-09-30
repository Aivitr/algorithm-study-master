"""用户查找（阶段 5 从 server.py 迁出）。

`resolve_user_by_identifier` 让调用方用**学号或用户名**任一种标识定位用户：
先按 `User.student_id` 查，查不到再按 `User.username` 查。

为什么给它一个独立的家
----------------------
全仓库有 5 处调用它，横跨三块互不相干的业务：实时链路（WebSocket 建转写记录）、
情绪统计（实时统计 / 情绪明细）、快照与视频上下文。阶段 5 把路由按业务域拆开后，
任何一块都不能再 `from server import ...`（在 `python server.py` 下那会让
server.py 二次执行，见 `app/routers/__init__.py`），而跟着其中一块走会让另外
两块缺依赖——所以放在这里，由各方直接导入。

`server.py` 目前仍以再导出的方式持有同一个对象，因此 server.py 内未迁走的
调用点一行未改。
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
