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

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.meeting_state import ENDED, RUNNING, meeting_status_error
from app.models import KnowledgeGraph, Meeting
from app.services.class_stats_service import ClassStatsService
from app.services.knowledge_graph_service import kg_service
from app.services.knowledge_trace_service import KnowledgeTraceService
from app.services.llm_service import llm
from app.services.meeting_context_service import MeetingContextService
from app.services.session_service import SessionContext, require_session
from app.services.transcript_query_service import TranscriptQueryService

router = APIRouter()

@router.get("/summary")
async def get_summary(meeting_id: int, db: Session = Depends(get_db)):
    transcripts = TranscriptQueryService(db).list_for_meeting(meeting_id)
    emo_stats = ClassStatsService(db).emotion_counts(meeting_id)
    full_text = "\n".join([f"{t.user.username}: {t.content}" for t in transcripts])
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        return {"status": "error", "message": "课堂不存在"}
    state_error = meeting_status_error(meeting.status, {RUNNING, ENDED})
    if state_error:
        return {"status": "error", "message": state_error}
    return llm.analyze_emotion_and_summary(meeting.topic, full_text, emo_stats)


@router.get("/api/knowledge-graph/{meeting_id}")
async def get_knowledge_graph(meeting_id: int, db: Session = Depends(get_db)):
    """获取知识图谱"""
    return KnowledgeTraceService(db).visualize(meeting_id)


@router.post("/api/knowledge-graph/{meeting_id}/generate")
async def generate_knowledge_graph(
    meeting_id: int,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    """用课堂转写现场构建知识图谱并保存；没有发言时不调用 LLM。"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}
        if ctx.user.role != "teacher" or int(meeting.teacher_id) != int(ctx.user.id):
            return {"status": "error", "message": "只有本课堂教师可以生成知识图谱"}
        state_error = meeting_status_error(meeting.status, {RUNNING, ENDED})
        if state_error:
            return {"status": "error", "message": state_error}

        service = KnowledgeTraceService(db)
        graph = service.build_from_transcripts(meeting_id)
        if not graph or not graph.get("nodes"):
            return {"status": "error", "message": "暂无可用发言，无法生成知识图谱"}

        row = db.query(KnowledgeGraph).filter(
            KnowledgeGraph.meeting_id == meeting_id
        ).first()
        if row:
            row.graph_data = graph
            row.updated_at = datetime.now()
        else:
            db.add(KnowledgeGraph(meeting_id=meeting_id, graph_data=graph))
        db.commit()

        return {
            "status": "success",
            "data": kg_service.generate_graph_visualization_data(graph),
        }
    except Exception as e:
        db.rollback()
        print(f"[ERROR] 生成知识图谱失败: {e}")
        return {"status": "error", "message": "生成知识图谱失败，请稍后重试"}


@router.get("/api/meeting/{meeting_id}")
async def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """获取课堂信息（包括状态、时间与目标）"""
    return MeetingContextService(db).build_response(meeting_id)


@router.get("/api/transcripts/{meeting_id}")
async def get_transcripts(meeting_id: int, limit: int = 500, db: Session = Depends(get_db)):
    """获取课堂历史发言（用于前端对话栏展示）"""
    try:
        limit = max(1, min(int(limit), 2000))
        transcripts = TranscriptQueryService(db).list_for_meeting(
            meeting_id, limit=limit
        )

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
