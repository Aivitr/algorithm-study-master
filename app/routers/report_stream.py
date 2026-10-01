"""报告流式生成域的路由。

本组 2 条：

    GET  /api/exercises/{report_id}      取某份报告生成出来的随堂练习
    POST /api/generate-report-stream     以 SSE 流式生成学习报告

两条放在同一个模块，是因为 `/api/exercises` 读的正是报告产出物
（`Exercise.report_id`）。

本组只依赖 import 能解决的名字（无 server.py 内部辅助、不碰模块级可变状态），
唯一的"实时"味道是 SSE 本身——它不读任何进程内共享状态。
"""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import StreamingResponse
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

@router.get("/api/exercises/{report_id}")
async def get_exercises(report_id: int, db: Session = Depends(get_db)):
    """获取报告对应的习题列表（JSON格式）"""
    exercises = db.query(Exercise).filter(Exercise.report_id == report_id).all()
    return {
        "status": "success",
        "exercises": [
            {
                "id": ex.id,
                "question": ex.question,
                "type": ex.question_type,
                "options": ex.options,
                "answer": ex.answer,
                "knowledge_tag": ex.knowledge_tag,
                "difficulty": ex.difficulty,
                "estimated_time": ex.estimated_time
            }
            for ex in exercises
        ]
    }


@router.post("/api/generate-report-stream")
async def generate_report_stream(
    meeting_id: int = Form(...),
    user_id: int = Form(...),
):
    """流式生成学习报告 - SSE进度推送"""
    import json as _json

    def generate():
        db = SessionLocal()
        try:
            yield f"data: {_json.dumps({'type': 'progress', 'message': '正在分析课堂数据...'}, ensure_ascii=False)}\n\n"

            last_report = db.query(LearningReport).filter(
                LearningReport.meeting_id == meeting_id,
                LearningReport.user_id == user_id
            ).order_by(LearningReport.created_at.desc()).first()
            cutoff_time = last_report.created_at if last_report else None

            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            user = db.query(User).filter(User.id == user_id).first()

            if not meeting or not user:
                yield f"data: {_json.dumps({'type': 'error', 'message': '课堂或用户不存在'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            transcript_query = db.query(Transcript).filter(Transcript.meeting_id == meeting_id)
            emotion_query = db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting_id)
            if cutoff_time:
                transcript_query = transcript_query.filter(Transcript.created_at > cutoff_time)
                emotion_query = emotion_query.filter(EmotionLog.created_at > cutoff_time)

            all_transcripts = transcript_query.order_by(Transcript.id).all()
            all_emotions = emotion_query.all()

            student_transcripts = [t for t in all_transcripts if getattr(t.user, "role", None) != "teacher"]
            student_emotions = [e for e in all_emotions if getattr(e.user, "role", None) != "teacher"]

            user_transcripts = [t for t in student_transcripts if t.user_id == user_id]
            speech_count = len(user_transcripts)
            avg_relevance = (
                sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
                if speech_count > 0 else 0
            )

            if speech_count == 0:
                user_transcripts = [t for t in student_transcripts if t.user.username == user.username]
                speech_count = len(user_transcripts)
                avg_relevance = (
                    sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
                    if speech_count > 0 else 0
                )

            if speech_count == 0:
                yield f"data: {_json.dumps({'type': 'error', 'message': '本次课堂无你的新发言，未生成新报告'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            yield f"data: {_json.dumps({'type': 'progress', 'message': f'已找到 {speech_count} 条发言记录，正在生成AI报告...'}, ensure_ascii=False)}\n\n"

            user_emotions = [e for e in student_emotions if e.user_id == user_id]
            emotion_stats = {}
            for e in user_emotions:
                emotion_key = normalize_emotion_label(e.emotion_type)
                emotion_stats[emotion_key] = emotion_stats.get(emotion_key, 0) + 1

            all_transcripts_data = [{
                "username": t.user.username,
                "content": t.content,
                "timestamp": t.created_at.isoformat()
            } for t in student_transcripts]

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

            # LLM生成报告
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

            yield f"data: {_json.dumps({'type': 'progress', 'message': '报告生成完毕，正在生成针对性习题...'}, ensure_ascii=False)}\n\n"

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

            members_list = list(set([t.user.username for t in student_transcripts]))
            basic_info = course_report.get("basic_info") or {}
            if not basic_info.get("members") or not isinstance(basic_info.get("members"), list):
                basic_info = {
                    **basic_info,
                    "topic": meeting.topic,
                    "members": members_list,
                    "recorder": basic_info.get("recorder", "课程助手")
                }

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

            report = LearningReport(
                meeting_id=meeting_id,
                user_id=user_id,
                report_data=report_data
            )
            db.add(report)
            db.commit()
            db.refresh(report)

            # 生成习题
            unmastered = "; ".join(student_review.get("unmastered_concepts", []))
            if not unmastered:
                unmastered = "基础知识：" + meeting.topic

            exercises_result = llm.generate_exercises(unmastered, meeting.topic)
            exercises_list = exercises_result.get("exercises", [])

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

            yield f"data: {_json.dumps({'type': 'progress', 'message': f'习题生成完毕！共 {len(exercises_list)} 道题'}, ensure_ascii=False)}\n\n"

            # 最终结果
            yield f"data: {_json.dumps({'type': 'complete', 'report': report_data, 'exercises': exercises_list, 'report_id': report.id}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            print(f"[OK] 流式报告生成完毕: speech_count={speech_count}, exercises={len(exercises_list)}")

        except Exception as e:
            print(f"[ERROR] 流式报告生成失败: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {_json.dumps({'type': 'error', 'message': f'报告生成失败: {str(e)}'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="text/event-stream")
