"""认证与注册域的路由。

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
"""

import json
import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Meeting, User
from app.services.llm_service import llm

router = APIRouter()

@router.post("/api/register")
async def register(
    student_id: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("student")
):
    """User registration"""
    try:
        print(f"[NOTE] Register request - ID: {student_id}, Role: {role}")
    except:
        print(f"[NOTE] Register request received")

    import pymssql
    try:
        conn = pymssql.connect(
            server=os.getenv("DB_HOST", ""),
            port=int(os.getenv("DB_PORT", "3433")),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", ""),
            charset='utf8',
            timeout=10,
            login_timeout=10
        )
        cursor = conn.cursor()

        # Insert user
        print("[SAVE] Executing INSERT...")
        cursor.execute(
            "INSERT INTO users (student_id, username, password, role, created_at) VALUES (%s, %s, %s, %s, GETDATE())",
            (student_id, username, password, role)
        )
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[OK] Registration successful")
        return {"status": "success", "message": "注册成功"}
    except pymssql.IntegrityError as e:
        print(f"[ERROR] Student ID already exists: {student_id}")
        return {"status": "error", "message": "学号/用户名已存在"}
    except Exception as e:
        error_msg = str(e)
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            print(f"[ERROR] Database connection timeout")
            return {"status": "error", "message": "数据库连接超时，请重试"}
        print(f"[ERROR] Registration failed: {e}")
        return {"status": "error", "message": f"注册失败: {error_msg}"}


@router.post("/api/login")
async def api_login(
    student_id: str = Form(...),
    password: str = Form(...)
):
    """User login"""
    print(f"[LOGIN] Login request - ID: {student_id}")

    import pymssql
    import time
    try:
        start_time = time.time()
        print(f"[DB] Connecting...")

        conn = pymssql.connect(
            server=os.getenv("DB_HOST", ""),
            port=int(os.getenv("DB_PORT", "3433")),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", ""),
            charset='utf8',
            timeout=10,
            login_timeout=10
        )
        print(f"[OK] Connected: {time.time() - start_time:.2f}s")

        cursor = conn.cursor(as_dict=True)

        print("[QUERY] Querying user...")
        query_start = time.time()
        cursor.execute(
            "SELECT TOP 1 id, student_id, username, password, role FROM users WHERE student_id = %s",
            (student_id,)
        )
        user = cursor.fetchone()
        print(f"[OK] Query done: {time.time() - query_start:.2f}s")

        cursor.close()
        conn.close()

        if not user:
            print(f"[ERROR] User not found: {student_id}")
            return {"status": "error", "message": "学号/密码错误"}

        if user['password'] != password:
            print(f"[ERROR] Wrong password: {student_id}")
            return {"status": "error", "message": "密码错误"}

        total_time = time.time() - start_time
        print(f"[OK] Login success: {user['username']} ({user['role']}) - Time: {total_time:.2f}s")
        return {
            "status": "success",
            "user": {
                "id": user['id'],
                "student_id": user['student_id'],
                "username": user['username'],
                "role": user['role']
            }
        }
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] Login failed: {error_msg}")

        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            return {"status": "error", "message": "数据库连接超时"}
        elif "connect" in error_msg.lower():
            return {"status": "error", "message": "无法连接数据库"}
        else:
            return {"status": "error", "message": f"登录失败: {error_msg[:100]}"}


@router.post("/login")
async def login(
    username: str = Form(...),
    class_code: str = Form(...),
    role: str = Form("student"),  # teacher/student,默认学生
    topic: str = Form(None),
    reference_materials: str = Form(None),  # JSON字符串
    material_file: UploadFile = File(None),  # 上传文件
    material_url: str = Form(None),  # 材料URL
    template_path: str = Form(None),  # 模板路径
    student_id: str = Form(None),  # 用 student_id 查找用户，避免中文编码问题
    db: Session = Depends(get_db)
):
    """
    统一登录接口（兼容前端）
    - 学生端:加入课堂
    - 教师端:创建课堂
    """
    # 验证用户 — 优先用 student_id（纯ASCII，无编码问题）
    user = None
    if student_id:
        user = db.query(User).filter(User.student_id == student_id).first()
    if not user:
        user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"status": "error", "message": "用户不存在，请先注册"}
    
    # ??
    meeting = db.query(Meeting).filter(
        Meeting.class_code == class_code, 
        Meeting.status == "active"
    ).first()
    
    if meeting:
        if str(meeting.class_code) == "100":
            kp = meeting.knowledge_points if isinstance(meeting.knowledge_points, list) else []
            trimmed = kp[:3]
            if len(kp) != len(trimmed):
                meeting.knowledge_points = trimmed
                db.commit()
        # 已存在会议，直接返回
        return {
            "status": "success",
            "meeting_id": meeting.id,
            "goals": meeting.knowledge_points,
            "topic": meeting.topic,
            "role": user.role,
            "teaching_design": meeting.teaching_design
        }
    else:
        # 创建新会议
        if role == "student":
            return {"status": "error", "message": "课堂不存在，请联系老师"}

        # 验证主题
        if not topic:
            return {"status": "error", "message": "缺少主题"}
        
        # 生成教学目标
        print(f"[AI] 生成教学目标: {topic}")

        # 收集材料
        materials = []

        # 1. 上传文件
        if material_file:
            try:
                import os
                # 创建上传目录
                upload_dir = "uploads"
                os.makedirs(upload_dir, exist_ok=True)

                # 保存文件
                file_path = os.path.join(upload_dir, material_file.filename)
                with open(file_path, "wb") as f:
                    content = await material_file.read()
                    f.write(content)

                materials.append({
                    "type": "file",
                    "filename": material_file.filename,
                    "path": file_path,
                    "size": len(content)
                })
                print(f"已保存 文件: {material_file.filename}")
            except Exception as e:
                print(f"[ERROR] 文件上传失败: {e}")

        # 2. 添加URL
        if material_url:
            materials.append({
                "type": "url",
                "url": material_url
            })
            print(f"[DB] 添加URL: {material_url}")

        # 3. 处理reference_materials参数（兼容旧版）
        if reference_materials:
            try:
                old_materials = json.loads(reference_materials)
                if isinstance(old_materials, list):
                    materials.extend(old_materials)
                else:
                    materials.append(old_materials)
            except:
                materials.append({"type": "text", "content": reference_materials})

        # 调用LLM生成目标
        print(f"[AI] AI生成目标: {topic}")
        try:
            goals = llm.init_meeting_goals(topic)
            if not goals or len(goals) == 0:
                goals = [
                    {"id": 1, "desc": "理解基本概念", "status": "pending"},
                    {"id": 2, "desc": "掌握核心方法", "status": "pending"},
                    {"id": 3, "desc": "应用实践练习", "status": "pending"}
                ]
                print("[WARN] LLM返回空，使用默认目标")
            else:
                print(f"[OK] 生成了 {len(goals)} 个目标")
        except Exception as e:
            print(f"[ERROR] LLM生成失败: {e}, 使用默认")
            goals = [
                {"id": 1, "desc": "理解基本概念", "status": "pending"},
                {"id": 2, "desc": "掌握核心方法", "status": "pending"},
                {"id": 3, "desc": "应用实践练习", "status": "pending"}
            ]

        # 生成教学设计（可选）
        teaching_design = {
            "objectives": [g["desc"] for g in goals],
            "phases": [
                {"phase_name": "导入阶段", "duration": 10, "tasks": ["激活先验知识", "引入主题"]},
                {"phase_name": "探究阶段", "duration": 25, "tasks": ["小组讨论", "实践操作"]},
                {"phase_name": "总结阶段", "duration": 10, "tasks": ["归纳总结", "反思评价"]}
            ],
            "division_strategy": {
                "roles": ["记录员", "发言人", "协调员"],
                "responsibilities": "明确分工，协作完成"
            },
            "evaluation_criteria": ["参与度", "贡献度", "协作能力"]
        }

        # 创建会议
        meeting = Meeting(
            class_code=class_code,
            teacher_id=user.id,
            topic=topic,
            reference_materials=materials if materials else None,
            teaching_design=teaching_design,
            knowledge_points=goals,
            template_path=template_path  # 保存模板路径
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        return {
            "status": "success",
            "meeting_id": meeting.id,
            "goals": meeting.knowledge_points,
            "topic": meeting.topic,
            "role": user.role,
            "teaching_design": teaching_design,
            "message": "课堂创建成功"
        }
