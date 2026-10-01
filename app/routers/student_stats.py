"""学生与班级统计域的路由。

本组 3 条，都是"按 user_id / teacher_id 汇总历史数据"这一族：

    GET /api/class-history/{user_id}        某学生的历史课堂
    GET /api/student-home-stats/{user_id}   学生首页统计
    GET /api/active-groups/{teacher_id}     某教师名下仍在进行的分组

它们共用 `_build_meeting_window_map`——该辅助**也**被教师域的
`/api/teacher-classes` 使用，因此住在中立的 `app/services/meeting_metrics.py`，
本模块从那里导入（不能 `from server import`，见 `app/routers/__init__.py`）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import LearningReport, Meeting, Transcript, User
from app.services.meeting_metrics import _build_meeting_window_map

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

        history = []
        for m in all_meetings:
            # 统计参与人数
            participant_count = db.query(Transcript.user_id).filter(
                Transcript.meeting_id == m.id
            ).distinct().count()

            # 获取报告
            first_transcript = db.query(Transcript).filter(
                Transcript.meeting_id == m.id
            ).order_by(Transcript.created_at).first()
            
            last_transcript = db.query(Transcript).filter(
                Transcript.meeting_id == m.id
            ).order_by(Transcript.created_at.desc()).first()
            
            start_time = first_transcript.created_at if first_transcript else m.created_at
            end_time = last_transcript.created_at if last_transcript else m.created_at

            # 查询该用户在此会议的发言数
            user_speech_count = db.query(Transcript).filter(
                Transcript.meeting_id == m.id,
                Transcript.user_id == user_id
            ).count()

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
        window_map = _build_meeting_window_map(db, meeting_ids)

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

        groups = []
        for m in meetings:
            # 统计发言数
            speech_count = db.query(Transcript).join(User, User.id == Transcript.user_id).filter(
                Transcript.meeting_id == m.id,
                User.role != "teacher"
            ).count()

            # 参与成员数（排除老师）
            member_count = db.query(Transcript.user_id).join(User, User.id == Transcript.user_id).filter(
                Transcript.meeting_id == m.id,
                User.role != "teacher"
            ).distinct().count()

            # 计算活跃度（避免轻易封顶 100）
            avg_speech = speech_count / max(member_count, 1)
            base = min(60.0, avg_speech * 12.0)          # 0~60：人均发言贡献
            volume = min(30.0, speech_count * 0.8)       # 0~30：总体发言量
            breadth = min(10.0, member_count * 1.0)      # 0~10：参与广度
            score = int(min(100.0, base + volume + breadth))

            # 状态标签
            if speech_count < 5:
                status_tag = "冷清"
            elif avg_speech < 2:
                status_tag = "一般"
            else:
                status_tag = "活跃"

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
