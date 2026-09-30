"""课堂投票域的路由（阶段 5 从 server.py 拆出）。

本组共 3 条，按课堂投票的生命周期排列：

    /api/cast-vote      学生投票
    /api/close-vote     教师结束投票，触发统计与 AI 归纳
    /api/confirm-vote   学生确认（vote_confirmations 记在连接管理器上）

`manager` 取自 `app.realtime.registry`——**不能** `from server import manager`：
在 `python server.py` 启动时那会让 server.py 二次执行（见 app/routers/__init__.py）。
registry 里的那个实例与 `server.manager` 是同一个对象，因此
`manager.vote_confirmations` 与 WebSocket 路由看到的是同一份状态。
"""

from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Meeting, ViewpointVote
from app.realtime.registry import manager
from app.services.llm_service import llm

router = APIRouter()
