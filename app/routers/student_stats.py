"""学生与班级统计域的路由。

本组 3 条，都是"按 user_id / teacher_id 汇总历史数据"这一族：

    GET /api/class-history/{user_id}        某学生的历史课堂
    GET /api/student-home-stats/{user_id}   学生首页统计
    GET /api/active-groups/{teacher_id}     某教师名下仍在进行的分组

它们共用 `ClassStatsService`（`app/services/class_stats_service.py`）提供的课堂窗口与
活跃度聚合——该服务**也**被教师域的 `/api/teacher-classes` 使用（不能
`from server import`，见 `app/routers/__init__.py`）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import LearningReport, Meeting, Transcript
from app.services.class_stats_service import ClassStatsService

router = APIRouter()

@router.get("/api/class-history/{user_id}")
async def get_class_history(user_id: int, db: Session = Depends(get_db)):
    """获取用户的课堂历史"""
    try:
        from datetime import datetime

        # 查询参与的课堂
        user_meetings = db.query(Meeting).join(Transcript).filter(
            Transcript.user_id == user_id
        ).distinct().all()

        # 查询创建的课堂
        created_meetings = db.query(Meeting).filter(
            Meeting.teacher_id == user_id
        ).all()

        all_meetings = list(set(user_meetings + created_meetings))

        stats = ClassStatsService(db)
        window_map = stats.window_map([int(m.id) for m in all_meetings])

        history = []
        for m in all_meetings:
            window = window_map.get(int(m.id), {})
            start_time = window.get("first_at") or m.created_at
            end_time = window.get("last_at") or m.created_at
            participant_count = stats.participant_count(m.id)
            user_speech_count = stats.user_speech_count(m.id, user_id)

            # 查询是否有报告
            has_report = db.query(LearningReport).filter(
                LearningReport.meeting_id == m.id,
                LearningReport.user_id == user_id
            ).first() is not None

            history.append({
                "meeting_id": m.id,
                "class_code": m.class_code,
                "topic": m.topic,
                "status": m.status,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_minutes": int((end_time - start_time).total_seconds() / 60),
                "participant_count": participant_count,
                "speech_count": user_speech_count,
                "has_report": has_report,
                "created_at": m.created_at.isoformat()
            })

        # 按时间倒序排列
        history.sort(key=lambda x: x["created_at"], reverse=True)

        return {"status": "success", "history": history}
    except Exception as e:
        print(f"[ERROR] 获取历史失败: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/student-home-stats/{user_id}")
async def get_student_home_stats(user_id: int, db: Session = Depends(get_db)):
    """涓虹櫥褰曞悗棣栭〉鎻愪緵杞婚噺瀛︿範姒傝鏁版嵁"""
    try:
        meeting_ids = [
            int(meeting_id)
            for (meeting_id,) in db.query(Transcript.meeting_id).filter(
                Transcript.user_id == user_id
            ).distinct().all()
        ]
        if not meeting_ids:
            return {
                "status": "success",
                "stats": {
                    "activeClasses": 0,
                    "completedClasses": 0,
                    "studyHours": "0.0",
                }
            }

        meetings = db.query(Meeting).filter(Meeting.id.in_(meeting_ids)).all()
        window_map = ClassStatsService(db).window_map(meeting_ids)

        active_classes = 0
        completed_classes = 0
        total_minutes = 0
        for meeting in meetings:
            if meeting.status == "active":
                active_classes += 1
            else:
                completed_classes += 1

            window = window_map.get(int(meeting.id), {})
            start_time = window.get("first_at") or meeting.created_at
            end_time = window.get("last_at") or meeting.created_at
            total_minutes += max(0, int((end_time - start_time).total_seconds() / 60))

        return {
            "status": "success",
            "stats": {
                "activeClasses": active_classes,
                "completedClasses": completed_classes,
                "studyHours": f"{(total_minutes / 60):.1f}",
            }
        }
    except Exception as e:
        print(f"[ERROR] 鑾峰彇棣栭〉缁熻澶辫触: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/active-groups/{teacher_id}")
async def get_active_groups(teacher_id: int, db: Session = Depends(get_db)):
    """获取老师的活跃课堂"""
    try:
        # 查询活跃课堂
        meetings = db.query(Meeting).filter(
            Meeting.teacher_id == teacher_id,
            Meeting.status == "active"
        ).all()

        meeting_ids = [int(m.id) for m in meetings]
        stats = ClassStatsService(db)
        activity_map = stats.activity_map(meeting_ids, exclude_teacher=True)

        groups = []
        for m in meetings:
            activity = activity_map.get(int(m.id), {})
            speech_count = int(activity.get("speech_count", 0))
            member_count = int(activity.get("member_count", 0))

            # 计算活跃度（避免轻易封顶 100）
            avg_speech = speech_count / max(member_count, 1)
            score = stats.class_score(speech_count, member_count)

            # 状态标签
            status_tag = stats.active_status_tag(speech_count, avg_speech)

            groups.append({
                "meeting_id": m.id,
                "class_code": m.class_code,
                "topic": m.topic,
                "member_count": member_count,
                "speech_count": speech_count,
                "score": score,
                "status_tag": status_tag
            })

        # 按分数排序
        groups.sort(key=lambda x: x['score'], reverse=True)

        return {"status": "success", "groups": groups}
    except Exception as e:
        print(f"[ERROR] 获取活跃课堂失败: {e}")
        return {"status": "error", "message": str(e)}
