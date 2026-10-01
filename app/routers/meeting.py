"""会议与转写域的路由。

本组 4 条，都是"给定 meeting_id 取这节课的数据"这一族：

    /summary                        整节课的文字摘要（会调 LLM）
    /api/knowledge-graph/{id}       知识点图谱
    /api/meeting/{id}               课堂基本信息
    /api/transcripts/{id}           逐条发言 + 情绪

它们与 `app/routers/votes.py` 的区别是**不碰任何模块级可变状态**：只是
`db.query(...)` 之后组织返回值，因此是依赖最少的一组。

`normalize_emotion_label` 取自 `app.core.emotions`——不能从 `server` 取，
见 `app/routers/__init__.py`。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.emotions import normalize_emotion_label
from app.models import EmotionLog, KnowledgeGraph, Meeting, Transcript
from app.services.knowledge_graph_service import kg_service
from app.services.llm_service import llm

router = APIRouter()

@router.get("/summary")
async def get_summary(meeting_id: int, db: Session = Depends(get_db)):
    transcripts = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).all()
    emotions = db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting_id).all()
    emo_stats = {}
    for e in emotions:
        emotion_key = normalize_emotion_label(e.emotion_type)
        emo_stats[emotion_key] = emo_stats.get(emotion_key, 0) + 1
    full_text = "\n".join([f"{t.user.username}: {t.content}" for t in transcripts])
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    return llm.analyze_emotion_and_summary(meeting.topic, full_text, emo_stats)


@router.get("/api/knowledge-graph/{meeting_id}")
async def get_knowledge_graph(meeting_id: int, db: Session = Depends(get_db)):
    """获取知识图谱"""
    kg = db.query(KnowledgeGraph).filter(KnowledgeGraph.meeting_id == meeting_id).first()
    if not kg:
        return {"status": "empty", "data": {"nodes": [], "edges": []}}

    # 生成可视化数据
    viz_data = kg_service.generate_graph_visualization_data(kg.graph_data)
    return {"status": "success", "data": viz_data}


@router.get("/api/meeting/{meeting_id}")
async def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """获取课堂信息（包括目标）"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        return {"status": "error", "message": "课堂不存在"}

    return {
        "status": "success",
        "meeting_id": meeting.id,
        "topic": meeting.topic,
        "goals": meeting.knowledge_points or [],
        "teaching_design": meeting.teaching_design
    }


@router.get("/api/transcripts/{meeting_id}")
async def get_transcripts(meeting_id: int, limit: int = 500, db: Session = Depends(get_db)):
    """获取课堂历史发言（用于前端对话栏展示）"""
    try:
        limit = max(1, min(int(limit), 2000))
        transcripts = db.query(Transcript).options(joinedload(Transcript.user)).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.created_at.asc()).limit(limit).all()

        items = []
        for t in transcripts:
            # 课堂对话历史只展示学生发言（不包含老师）
            if getattr(t.user, "role", None) == "teacher":
                continue
            ts = t.created_at or t.timestamp
            items.append({
                "id": t.id,
                "username": t.user.username if t.user else "",
                "text": t.content,
                "timestamp": int(ts.timestamp() * 1000) if ts else None,
                "quality_score": getattr(t, "quality_score", None),
                "quality_feedback": getattr(t, "quality_feedback", None),
                "emotion": getattr(t, "emotion_tag", None),
                "action": getattr(t, "body_action", None),
            })

        return {"status": "success", "transcripts": items}
    except Exception as e:
        print(f"[ERROR] 获取课堂发言失败: {e}")
        return {"status": "error", "message": str(e)}
