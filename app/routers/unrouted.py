"""**没有接线**的处理器：两个函数都没有 `@router.*` 装饰器，不在任何路由表里。

本模块被 server.py 正常装配（末尾有一段 `include_router`），但它**故意不贡献
任何路由**——里面的报头 `router` 是空的。这样做的原因见下。

## 这两个函数为什么在这里

它们是阶段 5 从 server.py 拆出来的，拆的时候**一个字都没改**——包括"没有装饰器"
这件事。这不是拆分造成的：翻最初的提交 `44876f3`（Initial commit）可以看到，
两个 `async def` 都紧贴着上一个处理器的 `return` 语句，上方既没有空行也没有
装饰器。也就是说，**自项目第一天起它们就不是路由**。

按本项目的既有约定，它们不能删（未完成的功能要全量保留），也不能补上装饰器
——补上就等于新增接口，而设计文档 C5 冻结了 59 个接口的地址与输入输出。
所以只能原样留着，并把"它们没接线"这件事写成文字放在这里。

## 两个函数的现状（**待你决定**，已登记在 docs/待验收事项.md）

1. `upload_report_template` —— **前端正在调它，但后端没有这条路由。**
   `index.html:11207` 有 `axios.post('/api/upload-report-template', formData)`，
   而全仓库没有任何 `@app.post("/api/upload-report-template")`。也就是说这个按钮
   点下去拿到的是 404。实测方法：把 index.html 里所有 axios/fetch 的路径与
   `tests_safe/test_route_contract.py` 的契约表逐条对照，**只有这一条对不上**。

2. `select_viewpoint`（"老师直接选择观点（不投票）"）—— 前端**完全没有**调用点，
   后端也没有路由，是两侧都没接的半成品。

## 为什么落在 app/routers/ 而不是别处

它们是 HTTP 处理器的形状（`Form` / `Depends` / `UploadFile`），编辑路由的人会来
这里找；将来要把功能做完时，就地补一个装饰器再挪进对应的业务域模块（第 1 个
属于教师域 `teacher.py`，第 2 个属于观点/投票域 `votes.py`）即可。

`app/routers/` 下若有模块存在却没被装配，`tests_safe/test_routers_layout.py`
会报红——所以这里必须保留一个（空的）`router` 并在 server.py 里 include。
空 router 的 include 是空操作：展开后的路由表与拆分前逐条一致（59 条）。
"""

import os
import time

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.paths import PROJECT_ROOT
from app.models import Meeting
from app.services.llm_service import llm

# server.py 里 `BASE_DIR = str(PROJECT_ROOT)`。这里同源重算，不复制字面量路径，
# 免得锚点随文件位置漂移（见 tests_safe/test_paths_anchor.py）。
BASE_DIR = str(PROJECT_ROOT)

# 故意为空：本模块不注册任何路由，见文件头的说明。
router = APIRouter()

async def select_viewpoint(
    meeting_id: int = Form(...),
    viewpoint_id: int = Form(...),
    viewpoint_title: str = Form(...),
    viewpoint_desc: str = Form(...),
    db: Session = Depends(get_db)
):
    """老师直接选择观点（不投票）"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        selected_viewpoint = {
            "id": viewpoint_id,
            "title": viewpoint_title,
            "description": viewpoint_desc
        }

        # 生成子目标
        result = llm.generate_sub_goals(
            selected_viewpoint,
            meeting.topic,
            meeting.knowledge_points
        )

        # 更新教学目标
        if result.get("sub_goals"):
            new_goals = meeting.knowledge_points or []
            for sg in result["sub_goals"]:
                new_goals.append({
                    "id": len(new_goals) + 1,
                    "desc": f"[深入探讨] {sg['desc']}",
                    "status": "pending",
                    "parent_viewpoint": viewpoint_title
                })
            meeting.knowledge_points = new_goals
            db.commit()

        return {
            "status": "success",
            "sub_goals": result.get("sub_goals", []),
            "guidance": result.get("guidance", ""),
            "updated_goals": meeting.knowledge_points
        }
    except Exception as e:
        print(f"[ERROR] 选择观点失败: {e}")
        return {"status": "error", "message": str(e)}






# 新增接口: 获取快照




async def upload_report_template(
    template_file: UploadFile = File(...),
    teacher_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """??"""
    try:
        from app.models import ReportTemplate
        
        template_dir = os.path.join(BASE_DIR, "storage", "templates")
        os.makedirs(template_dir, exist_ok=True)
        
        original_filename = template_file.filename
        filename = f"template_{teacher_id}_{int(time.time())}_{original_filename}"
        filepath = os.path.join(template_dir, filename)
        
        with open(filepath, "wb") as f:
            content = await template_file.read()
            f.write(content)
        
        # ??
        template = ReportTemplate(
            teacher_id=teacher_id,
            filename=original_filename,
            filepath=filepath,
            is_default=1  # ??
        )
        
        # ??
        db.query(ReportTemplate).filter(
            ReportTemplate.teacher_id == teacher_id,
            ReportTemplate.is_default == 1
        ).update({"is_default": 0})
        
        db.add(template)
        db.commit()
        db.refresh(template)
        
        return {
            "status": "success",
            "template_id": template.id,
            "template_path": filepath,
            "filename": original_filename
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}
