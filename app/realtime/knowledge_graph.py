"""实时链路的「知识图谱增量更新」（阶段 5 从 server.py 拆出）。

`update_knowledge_graph` 原本写在 server.py 的实时链路区块里，但**两个**模块都要
用它：语音分析（`app/realtime/speech.py`）与学生流式生成
（`app/realtime/stream.py`）。它不能只跟着其中一边走，所以给一个中立的家；
server.py 在原位置再导出，所有既有调用点保持不变。

它与实时链路里那堆进程内状态无关——只用 ORM 会话和知识图谱服务，因此可以
完全独立出来，不需要和任何缓存/锁同住。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import KnowledgeGraph, Meeting, Transcript
from app.services.knowledge_graph_service import kg_service

def update_knowledge_graph(meeting_id: int, db: Session):
    """🧠"""
    try:
        # 🧠10🧠
        transcripts = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id.desc()).limit(10).all()
        
        if len(transcripts) < 5:  # 🧠 5🧠
            return None
        
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()

        # 构建对话历史
        conversations = [
            {"username": t.user.username, "content": t.content}
            for t in reversed(transcripts)
        ]

        # 查询现有知识图谱
        existing_kg = db.query(KnowledgeGraph).filter(
            KnowledgeGraph.meeting_id == meeting_id
        ).first()

        existing_graph = existing_kg.graph_data if existing_kg else None

        # LLM提取新概念
        new_graph = kg_service.extract_concepts_from_conversation(
            topic=meeting.topic,
            conversations=conversations,
            existing_graph=existing_graph
        )

        if not new_graph.get("nodes"):
            return None

        # 记录发言人
        speakers = {}
        for node in new_graph.get("nodes", []):
            speakers[node["id"]] = list(set([c["username"] for c in conversations]))

        # 合并图谱
        merged_graph = kg_service.merge_graphs(existing_graph, new_graph, speakers)

        # 保存到数据库
        if existing_kg:
            existing_kg.graph_data = merged_graph
            existing_kg.updated_at = datetime.now()
        else:
            existing_kg = KnowledgeGraph(
                meeting_id=meeting_id,
                graph_data=merged_graph
            )
            db.add(existing_kg)
        
        db.commit()
        return merged_graph
        
    except Exception as e:
        print(f"知识图谱更新失败: {e}")
        return None
