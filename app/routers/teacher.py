"""教师端域的路由。

本组 6 条，是"教师视角的班级/报告/模板"这一族：

    GET    /api/teacher-templates/{teacher_id}        报告模板列表
    DELETE /api/delete-template/{template_id}         删模板
    GET    /api/teacher-stats/{teacher_id}            教师统计
    GET    /api/teacher-classes/{teacher_id}          教师带过的课堂
    GET    /api/class-groups/{meeting_id}             某节课的分组
    GET    /api/all-student-reports/{teacher_id}      全班报告汇总

`_build_meeting_window_map` / `_build_meeting_activity_map` 取自
`app/services/meeting_metrics.py`——它们同时服务学生统计域
（`/api/student-home-stats`），因此住在中立的服务模块里（不能 `from server import`，
见 `app/routers/__init__.py`）。

`sa_func`（`sqlalchemy.func` 的别名）是模块级别名，本组有聚合查询用到它。
漏掉这个导入不会导入失败，只会执行到那条路由时 NameError，再被处理器的
try/except 吞成 200 的错误响应——`tests_safe/test_module_free_names.py` 拦这个。
"""

import os

from fastapi import APIRouter, Depends
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Exercise, LearningReport, Meeting, Transcript, User
from app.services.meeting_metrics import (
    _build_meeting_activity_map,
    _build_meeting_window_map,
)

router = APIRouter()

@router.get("/api/teacher-templates/{teacher_id}")
async def get_teacher_templates(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        from app.models import ReportTemplate
        
        templates = db.query(ReportTemplate).filter(
            ReportTemplate.teacher_id == teacher_id
        ).order_by(ReportTemplate.created_at.desc()).all()
        
        result = []
        for t in templates:
            result.append({
                "id": t.id,
                "filename": t.filename,
                "filepath": t.filepath,
                "is_default": t.is_default,
                "created_at": t.created_at.isoformat()
            })
        
        return {"status": "success", "templates": result}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@router.delete("/api/delete-template/{template_id}")
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        from app.models import ReportTemplate
        
        template = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
        if template:
            # ??
            if os.path.exists(template.filepath):
                os.remove(template.filepath)
            # ??
            db.delete(template)
            db.commit()
        
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/teacher-stats/{teacher_id}")
async def get_teacher_stats(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        meetings = db.query(Meeting).filter(Meeting.teacher_id == teacher_id).all()
        meeting_ids = [int(m.id) for m in meetings]
        total_classes = len(meeting_ids)

        total_students = 0
        avg_score = 0
        risk_groups = 0

        if meeting_ids:
            total_students = db.query(
                sa_func.count(sa_func.distinct(Transcript.user_id))
            ).join(
                User, User.id == Transcript.user_id
            ).filter(
                Transcript.meeting_id.in_(meeting_ids),
                User.role != "teacher"
            ).scalar() or 0

            activity_map = _build_meeting_activity_map(db, meeting_ids, exclude_teacher=True)
            total_score = 0
            for meeting_id in meeting_ids:
                activity = activity_map.get(meeting_id, {})
                speech_count = int(activity.get("speech_count", 0))
                member_count = int(activity.get("member_count", 0))
                avg_speech = speech_count / max(member_count, 1)
                base = min(60.0, avg_speech * 12.0)
                volume = min(30.0, speech_count * 0.8)
                breadth = min(10.0, member_count * 1.0)
                score = int(min(100.0, base + volume + breadth))
                total_score += score
                if score < 60:
                    risk_groups += 1

            if total_classes > 0:
                avg_score = int(total_score / total_classes)
        
        return {
            "status": "success",
            "stats": {
                "totalClasses": total_classes,
                "totalStudents": total_students,
                "avgScore": avg_score,
                "riskGroups": risk_groups
            }
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/teacher-classes/{teacher_id}")
async def get_teacher_classes(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        meetings = db.query(Meeting).filter(
            Meeting.teacher_id == teacher_id
        ).order_by(Meeting.created_at.desc()).all()

        meeting_ids = [int(m.id) for m in meetings]
        activity_map = _build_meeting_activity_map(db, meeting_ids, exclude_teacher=True)
        window_map = _build_meeting_window_map(db, meeting_ids)

        classes = []
        for m in meetings:
            activity = activity_map.get(int(m.id), {})
            speech_count = int(activity.get("speech_count", 0))
            member_count = int(activity.get("member_count", 0))

            avg_speech = speech_count / max(member_count, 1)
            base = min(60.0, avg_speech * 12.0)
            volume = min(30.0, speech_count * 0.8)
            breadth = min(10.0, member_count * 1.0)
            score = int(min(100.0, base + volume + breadth))

            if score >= 80:
                score_level = '优秀'
                score_color = 'green'
            elif score >= 60:
                score_level = '良好'
                score_color = 'yellow'
            else:
                score_level = '待提高'
                score_color = 'red'
            
            window = window_map.get(int(m.id), {})
            first_at = window.get("first_at")
            last_at = window.get("last_at")
            if first_at and last_at:
                duration_minutes = max(0, int((last_at - first_at).total_seconds() / 60))
            else:
                duration_minutes = 0

            classes.append({
                "meeting_id": m.id,
                "class_code": m.class_code,
                "topic": m.topic,
                "status": m.status,
                "member_count": member_count,
                "speech_count": speech_count,
                "duration_minutes": duration_minutes,
                "score": score,
                "score_level": score_level,
                "score_color": score_color,
                "created_at": m.created_at.isoformat()
            })
        
        return {"status": "success", "classes": classes}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/class-groups/{meeting_id}")
async def get_class_groups(meeting_id: int, db: Session = Depends(get_db)):
    """??/??"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "??"}
        
        # ??
        transcripts = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).all()
        
        # ??
        user_stats = {}
        for t in transcripts:
            user = t.user
            # 教师端查看学生表现时，排除老师账号
            if getattr(user, "role", None) == "teacher":
                continue
            if user.id not in user_stats:
                user_stats[user.id] = {
                    "user_id": user.id,
                    "username": user.username,
                    "speech_count": 0,
                    "total_relevance": 0,
                    "total_quality": 0
                }
            user_stats[user.id]["speech_count"] += 1
            user_stats[user.id]["total_relevance"] += t.relevance_score or 0
            user_stats[user.id]["total_quality"] += t.quality_score or 50
        
        # ??
        groups = []
        for uid, stats in user_stats.items():
            sc = stats["speech_count"]
            avg_relevance = stats["total_relevance"] / sc if sc > 0 else 0
            avg_quality = stats["total_quality"] / sc if sc > 0 else 50
            
            # ??
            score = int(avg_quality * 0.6 + avg_relevance * 0.4)
            
            if score >= 70:
                status = '优秀'
                status_color = 'green'
            elif score >= 50:
                status = '良好'
                status_color = 'yellow'
            else:
                status = '待提高'
                status_color = 'red'
            
            groups.append({
                "user_id": uid,
                "username": stats["username"],
                "speech_count": sc,
                "avg_relevance": round(avg_relevance, 1),
                "avg_quality": round(avg_quality, 1),
                "score": score,
                "status": status,
                "status_color": status_color
            })
        
        # ??
        groups.sort(key=lambda x: x["score"])
        
        return {
            "status": "success",
            "meeting_topic": meeting.topic,
            "groups": groups
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/all-student-reports/{teacher_id}")
async def get_all_student_reports(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        # ??
        meetings = db.query(Meeting).filter(Meeting.teacher_id == teacher_id).all()
        meeting_ids = [m.id for m in meetings]
        meeting_map = {m.id: m for m in meetings}
        
        if not meeting_ids:
            return {"status": "success", "reports": []}
        
        # ??
        reports = db.query(LearningReport).filter(
            LearningReport.meeting_id.in_(meeting_ids)
        ).order_by(LearningReport.created_at.desc()).all()
        
        result = []
        for r in reports:
            user = db.query(User).filter(User.id == r.user_id).first()
            meeting = meeting_map.get(r.meeting_id)

            data = r.report_data or {}

            # 从数据库实时查询真实的发言数（整个会议的累计值，而非窗口增量）
            real_speech_count = db.query(Transcript).filter(
                Transcript.meeting_id == r.meeting_id,
                Transcript.user_id == r.user_id
            ).count()
            # 如果按user_id查不到，尝试按用户名查
            if real_speech_count == 0 and user:
                real_speech_count = db.query(Transcript).join(User).filter(
                    Transcript.meeting_id == r.meeting_id,
                    User.username == user.username
                ).count()

            # 查询真实的习题数
            exercise_count = db.query(Exercise).filter(Exercise.report_id == r.id).count()

            # 计算真实的专注度（平均相关度）
            from sqlalchemy import func as sa_func
            avg_rel_result = db.query(sa_func.avg(Transcript.relevance_score)).filter(
                Transcript.meeting_id == r.meeting_id,
                Transcript.user_id == r.user_id,
                Transcript.relevance_score > 0
            ).scalar()
            real_avg_relevance = round(avg_rel_result, 1) if avg_rel_result else data.get("avg_relevance", 0)

            result.append({
                "report_id": r.id,
                "meeting_id": r.meeting_id,
                "user_id": r.user_id,
                "class_code": meeting.class_code if meeting else "",
                "topic": meeting.topic if meeting else "",
                "student_name": user.username if user else "未知",
                "student_id": user.student_id if user else "",
                "speech_count": real_speech_count or data.get("speech_count", 0),
                "exercise_count": exercise_count,
                "avg_relevance": real_avg_relevance,
                "summary": data.get("course_summary", "")[:100] + "..." if data.get("course_summary") else "",
                "created_at": r.created_at.isoformat()
            })
        
        return {"status": "success", "reports": result}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}
