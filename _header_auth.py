"""认证与注册域的路由（阶段 5 从 server.py 拆出）。

本组共 3 条：

    /api/register   学生/教师注册
    /api/login      登录（JSON）
    /login          登录（表单，返回 HTML 或 JSON）

**注意这里混着两条访问数据库的路径**
------------------------------------
`/api/register` 与 `/api/login` **不走 ORM**：它们直接用
`pymssql.connect(server=os.getenv("DB_HOST"), ...)` 连库，**不读 `DATABASE_URL`**，
因此配置里 `DB_*` 与 `DATABASE_URL` 必须两套都给（见 .env.example 的说明）。
`/login` 则走 ORM（`get_db` / `Session`）。

拆出本组时**没有**改动这两条路径中的任何一行——它们逐字节保持原样。
把两者放在同一个模块里是为了让这个差异**看得见**：它们是同一件事的两种实现，
分开摆放反而容易让人以为只有一条路径。
"""

import json
import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Meeting, User
from app.services.llm_service import llm

router = APIRouter()
