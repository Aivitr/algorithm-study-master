"""**没有接线**的处理器：两个函数都没有 `@router.*` 装饰器，不在任何路由表里。

本模块被 server.py 正常装配（末尾有一段 `include_router`），但**故意不贡献
任何路由**——里面的报头 `router` 是空的。

## 不要补装饰器，也不要删

补上装饰器等于新增接口，而 59 个接口的地址与输入输出是冻结的；删掉则违反
"未完成的功能全量保留"这条约定。两个 `async def` 自第一天起就没有装饰器，
原样留着即可。

## 两个函数的现状（**待决定**）

1. `upload_report_template` —— **前端正在调它，但后端没有这条路由。**
   前端有一处 `axios.post('/api/upload-report-template', formData)`
   （`static/js/app.js`），而全仓库没有任何 `@app.post("/api/upload-report-template")`。
   这个按钮点下去拿到的是 404。判据是那个**路径字符串**本身，不是行号。

2. `select_viewpoint`（"老师直接选择观点（不投票）"）—— 前端**完全没有**调用点，
   后端也没有路由，是两侧都没接的半成品。

## 为什么落在 app/routers/ 而不是别处

它们是 HTTP 处理器的形状（`Form` / `Depends` / `UploadFile`），编辑路由的人会来
这里找；将来要把功能做完时，就地补一个装饰器再挪进对应的业务域模块（第 1 个属于
教师域 `teacher.py`，第 2 个属于观点/投票域 `votes.py`）。

`app/routers/` 下若有模块存在却没被装配，`tests_safe/test_routers_layout.py`
会报红——所以这里必须保留一个（空的）`router` 并在 server.py 里 include。
空 router 的 include 是空操作：展开后的路由表仍逐条一致（59 条）。
"""

import os
import time

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.paths import PROJECT_ROOT
from app.models import Meeting
from app.services.llm_service import llm

# 与 server.py 同源重算，不复制字面量路径（见 tests_safe/test_paths_anchor.py）。
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






# 获取快照




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
