"""学习报告域的路由。

本组 3 条：

    POST /api/generate-report               生成整节课的学习报告（本组最大）
    GET  /api/reports/{user_id}             某学生的历史报告
    GET  /api/meeting-reports/{meeting_id}  某节课的成员报告

本组带走两个私有辅助：`_select_latest_reports` 与 `_build_report_metric_maps`。
全仓库只有 `get_meeting_reports` 用它们，因此随本组放在这里——不能留在
server.py（新模块要靠 `from server import ...` 才能拿到，见
`app/routers/__init__.py`）。

`/api/generate-report-stream` **不在这里**——它在 `app/routers/report_stream.py`。
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Form
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.emotions import normalize_emotion_label
from app.models import (
    EmotionLog,
    Exercise,
    LearningReport,
    Meeting,
    Transcript,
    User,
)
from app.services.llm_service import llm
from app.services.research_runtime import research_runtime

router = APIRouter()

@router.post("/api/generate-report")
async def generate_learning_report(
    meeting_id: int = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """生成学习报告（按上次报告后的新发言生成，保留历史版本）"""
    try:
        # 最近一次报告（用于截断“本轮课堂发言窗口”）
        last_report = db.query(LearningReport).filter(
            LearningReport.meeting_id == meeting_id,
            LearningReport.user_id == user_id
        ).order_by(LearningReport.created_at.desc()).first()
        cutoff_time = last_report.created_at if last_report else None

        # 查询数据
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        user = db.query(User).filter(User.id == user_id).first()

        if not meeting or not user:
            return {"status": "error", "message": "课堂或用户不存在"}

        # 获取“本轮课堂窗口”数据（上次报告之后）
        transcript_query = db.query(Transcript).filter(Transcript.meeting_id == meeting_id)
        emotion_query = db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting_id)
        if cutoff_time:
            transcript_query = transcript_query.filter(Transcript.created_at > cutoff_time)
            emotion_query = emotion_query.filter(EmotionLog.created_at > cutoff_time)

        all_transcripts = transcript_query.order_by(Transcript.id).all()
        all_emotions = emotion_query.all()

        # 报告生成只面向学生：过滤掉教师账号相关数据，避免教师被纳入学习报告
        student_transcripts = [t for t in all_transcripts if getattr(t.user, "role", None) != "teacher"]
        student_emotions = [e for e in all_emotions if getattr(e.user, "role", None) != "teacher"]

        # 统计个人数据
        user_transcripts = [t for t in student_transcripts if t.user_id == user_id]
        speech_count = len(user_transcripts)
        avg_relevance = (
            sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
            if speech_count > 0 else 0
        )

        print(f"[STATS] 报告生成 - 用户名:{user.username}, user_id:{user_id}, 发言数:{speech_count}, 总发言:{len(all_transcripts)}")

        # 如果没找到，按用户名查找
        if speech_count == 0:
            user_transcripts = [t for t in student_transcripts if t.user.username == user.username]
            speech_count = len(user_transcripts)
            avg_relevance = (
                sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
                if speech_count > 0 else 0
            )
            print(f"[STATS] 按用户名查找 - 发言数:{speech_count}")

        # 本轮无学生发言，不生成新报告（避免空报告覆盖体验）
        if speech_count == 0:
            return {
                "status": "no_new_data",
                "message": "本次课堂无你的新发言，未生成新报告"
            }

        user_emotions = [e for e in student_emotions if e.user_id == user_id]
        emotion_stats = {}
        for e in user_emotions:
            emotion_key = normalize_emotion_label(e.emotion_type)
            emotion_stats[emotion_key] = emotion_stats.get(emotion_key, 0) + 1

        # 构建全课堂数据（供LLM分析）
        all_transcripts_data = [{
            "username": t.user.username,
            "content": t.content,
            "timestamp": t.created_at.isoformat()
        } for t in student_transcripts]

        # 统计所有学生表现（供LLM对比）
        students = db.query(User).join(Transcript).filter(
            Transcript.meeting_id == meeting_id,
            User.role != "teacher"
        ).distinct().all()

        student_performances = []
        for s in students:
            s_transcripts = [t for t in student_transcripts if t.user_id == s.id]
            s_count = len(s_transcripts)
            s_relevance = (
                sum([(t.relevance_score or 0) for t in s_transcripts]) / s_count
                if s_count > 0 else 0
            )
            student_performances.append({
                "username": s.username,
                "speech_count": s_count,
                "avg_relevance": round(s_relevance, 2)
            })

        all_emotion_stats = {}
        for e in student_emotions:
            emotion_key = normalize_emotion_label(e.emotion_type)
            all_emotion_stats[emotion_key] = all_emotion_stats.get(emotion_key, 0) + 1

        # 调用LLM生成报告
        print("[AI] 生成课程报告...")
        course_report = llm.generate_course_report(
            meeting_topic=meeting.topic,
            all_transcripts=all_transcripts_data,
            emotion_stats=all_emotion_stats,
            student_performances=student_performances
        )
        if research_runtime.research_algorithms_active:
            course_report = research_runtime.enrich_course_report(
                meeting_topic=meeting.topic,
                all_transcripts=all_transcripts_data,
                emotion_stats=all_emotion_stats,
                student_performances=student_performances,
                course_report=course_report,
            )

        # 提取学生评价
        student_review = None
        for review in course_report.get("student_reviews", []):
            if review.get("student_name") == user.username:
                student_review = review
                break

        if not student_review:
            student_review = {
                "strengths": [],
                "weaknesses": [],
                "unmastered_concepts": [],
                "suggestions": "继续保持，积极参与"
            }

        # 确保 basic_info.members 存在
        members_list = list(set([t.user.username for t in student_transcripts]))
        basic_info = course_report.get("basic_info") or {}
        if not basic_info.get("members") or not isinstance(basic_info.get("members"), list):
            basic_info = {
                **basic_info,
                "topic": meeting.topic,
                "members": members_list,
                "recorder": basic_info.get("recorder", "课程助手")
            }

        # 构建报告数据
        report_data = {
            "student_name": user.username,
            "meeting_topic": meeting.topic,
            "speech_count": speech_count,
            "avg_relevance": round(avg_relevance, 2),
            "emotion_stats": emotion_stats,
            "strengths": student_review.get("strengths", []),
            "weaknesses": student_review.get("weaknesses", []),
            "unmastered_concepts": student_review.get("unmastered_concepts", []),
            "improvement_suggestions": student_review.get("suggestions", ""),
            "course_summary": course_report.get("summary", ""),
            "discussion_process": course_report.get("discussion_process", ""),
            "key_findings": course_report.get("key_findings", []),
            "class_atmosphere": course_report.get("class_atmosphere", ""),
            "summary": course_report.get("summary", ""),
            "basic_info": basic_info,
            "core_questions": course_report.get("core_questions", []),
            "viewpoints": course_report.get("viewpoints", []),
            "highlights": course_report.get("highlights") or {},
            "consensus": course_report.get("consensus", []),
            "unresolved": course_report.get("unresolved") or {},
            "action_plan": course_report.get("action_plan") or {},
            "student_reviews": course_report.get("student_reviews", []),
        }
        if research_runtime.research_algorithms_active:
            report_data["ipa_profile"] = student_review.get("ipa_profile", {})
            report_data["diagnostic_tags"] = student_review.get("diagnostic_tags", [])
            report_data["research"] = course_report.get("research", {})

        print(f"[DEBUG] 报告数据: speech_count={report_data['speech_count']}, avg_relevance={report_data['avg_relevance']}")

        # 保存新报告（保留历史版本，不覆盖）
        report = LearningReport(
            meeting_id=meeting_id,
            user_id=user_id,
            report_data=report_data
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        # 生成练习题（基于薄弱点）
        unmastered = "; ".join(student_review.get("unmastered_concepts", []))
        if not unmastered:
            unmastered = "基础知识：" + meeting.topic

        exercises_result = llm.generate_exercises(unmastered, meeting.topic)
        exercises_list = exercises_result.get("exercises", [])

        # 保存练习题
        for ex in exercises_list:
            exercise = Exercise(
                report_id=report.id,
                question=ex.get("question"),
                question_type=ex.get("type"),
                options=ex.get("options"),
                answer=ex.get("answer"),
                knowledge_tag=ex.get("knowledge_tag"),
                difficulty=ex.get("difficulty", 0.5),
                estimated_time=ex.get("estimated_time", 5)
            )
            db.add(exercise)

        db.commit()

        return {
            "status": "success",
            "report": report_data,
            "exercises": exercises_list,
            "cached": False,
            "regenerated": True if last_report else False
        }

    except Exception as e:
        print(f"报告生成失败: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@router.get("/api/reports/{user_id}")
async def get_user_reports(user_id: int, db: Session = Depends(get_db)):
    """获取用户的所有报告"""
    reports = db.query(LearningReport).filter(LearningReport.user_id == user_id).order_by(LearningReport.created_at.desc()).all()
    result = []
    for r in reports:
        meeting = db.query(Meeting).filter(Meeting.id == r.meeting_id).first()
        exercise_count = db.query(Exercise).filter(Exercise.report_id == r.id).count()
        result.append({
            "report_id": r.id,
            "meeting_id": r.meeting_id,
            "class_code": meeting.class_code if meeting else "",
            "data": r.report_data,
            "exercise_count": exercise_count,
            "created_at": r.created_at.isoformat()
        })
    return {
        "status": "success",
        "reports": result
    }


# 获取某次课堂的所有学生报告
@router.get("/api/meeting-reports/{meeting_id}")
async def get_meeting_reports(meeting_id: int, db: Session = Depends(get_db)):
    """获取课堂的所有学生报告"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        reports = db.query(LearningReport).filter(
            LearningReport.meeting_id == meeting_id
        ).order_by(LearningReport.created_at.desc()).all()
        latest_reports = _select_latest_reports(reports)

        user_ids = sorted({int(r.user_id) for r in latest_reports})
        users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
        user_map = {int(user.id): user for user in users}

        metric_maps = _build_report_metric_maps(db, [meeting_id], user_ids)
        by_user_id = metric_maps["by_user_id"]
        by_username = metric_maps["by_username"]

        result = []
        for report in latest_reports:
            user = user_map.get(int(report.user_id))
            if not user or user.role == "teacher":
                continue

            data = report.report_data or {}
            metrics = by_user_id.get((int(report.meeting_id), int(report.user_id))) or by_username.get((int(report.meeting_id), user.username)) or {}
            result.append({
                "report_id": report.id,
                "meeting_id": report.meeting_id,
                "user_id": report.user_id,
                "class_code": meeting.class_code if meeting else "",
                "student_id": user.student_id,
                "student_name": user.username,
                "speech_count": int(metrics.get("speech_count", 0) or data.get("speech_count", 0)),
                "avg_relevance": metrics.get("avg_relevance", data.get("avg_relevance", 0)),
                "improvement_suggestions": data.get("improvement_suggestions", ""),
                "summary": data.get("course_summary", "")[:100] + "..." if data.get("course_summary") else "",
                "created_at": report.created_at.isoformat()
            })
        
        return {
            "status": "success",
            "reports": result
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


def _select_latest_reports(reports: List[LearningReport]) -> List[LearningReport]:
    latest_reports: List[LearningReport] = []
    seen_keys = set()
    for report in reports:
        key = (int(report.meeting_id), int(report.user_id))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        latest_reports.append(report)
    return latest_reports


def _build_report_metric_maps(
    db: Session,
    meeting_ids: List[int],
    user_ids: List[int],
) -> Dict[str, Dict[Any, Dict[str, Any]]]:
    if not meeting_ids or not user_ids:
        return {"by_user_id": {}, "by_username": {}, "exercise_count": {}}

    rows = db.query(
        Transcript.meeting_id.label("meeting_id"),
        Transcript.user_id.label("user_id"),
        User.username.label("username"),
        sa_func.count(Transcript.id).label("speech_count"),
        sa_func.avg(Transcript.relevance_score).label("avg_relevance"),
    ).join(
        User, User.id == Transcript.user_id
    ).filter(
        Transcript.meeting_id.in_(meeting_ids),
        Transcript.user_id.in_(user_ids),
        User.role != "teacher",
    ).group_by(
        Transcript.meeting_id,
        Transcript.user_id,
        User.username,
    ).all()

    by_user_id: Dict[Any, Dict[str, Any]] = {}
    by_username: Dict[Any, Dict[str, Any]] = {}
    for row in rows:
        avg_relevance = float(row.avg_relevance) if row.avg_relevance is not None else 0.0
        payload = {
            "speech_count": int(row.speech_count or 0),
            "avg_relevance": round(avg_relevance, 1),
        }
        by_user_id[(int(row.meeting_id), int(row.user_id))] = payload
        by_username[(int(row.meeting_id), row.username)] = payload

    return {
        "by_user_id": by_user_id,
        "by_username": by_username,
        "exercise_count": {},
    }
