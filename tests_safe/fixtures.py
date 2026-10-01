"""合成测试数据（零 PII）。

设计约束（本地库 + 合成数据 + 只读 schema 校验）：
  - 数据**完全由本文件生成**，不含任何来自生产库的真实内容
  - 表结构按 ORM 建立（已验证 ORM 可在 sqlite 上完整建表）
  - 覆盖本地路由需要访问的主要实体

所有标识与内容均为编造，中文文本用于验证 NVARCHAR 在 sqlite 上的往返。
"""

from datetime import datetime, timedelta

# 固定时间基准，避免每次运行生成不同数据
BASE_TIME = datetime(2026, 1, 1, 9, 0, 0)


def seed_all(db) -> dict:
    """写入一整套合成数据，返回关键 ID。"""
    from app.models import (
        AIInsight,
        EmotionLog,
        Exercise,
        KnowledgeGraph,
        LearningReport,
        Meeting,
        MemberConnection,
        MentalHealthAssessment,
        ReportTemplate,
        StudentAnswer,
        Transcript,
        User,
        ViewpointVote,
    )

    if db.query(User).first() is not None:
        return _known_ids()

    teacher = User(
        id=1, student_id="T2026001", username="张老师",
        password="not-a-real-hash", role="teacher", created_at=BASE_TIME,
    )
    student_a = User(
        id=2, student_id="S2026001", username="李同学",
        password="not-a-real-hash", role="student", created_at=BASE_TIME,
    )
    student_b = User(
        id=3, student_id="S2026002", username="王同学",
        password="not-a-real-hash", role="student", created_at=BASE_TIME,
    )
    db.add_all([teacher, student_a, student_b])

    meeting = Meeting(
        id=1, class_code="CLS2026001", teacher_id=1,
        topic="测试课堂：光合作用", status="ended",
        knowledge_points=[], created_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(hours=1),
    )
    db.add(meeting)

    # 第二节：**进行中**的课堂。
    # `/api/active-groups/{teacher_id}` 只返回 `status == "active"` 的课，
    # 只有 ended 的会议会让它恒返回空列表——那样基线就锁不住它的聚合逻辑。
    #
    # `created_at` 必须与第一节**不同**：`/api/class-history/{user_id}` 用它倒序
    # 排序，而它前面的候选集来自 `list(set(...))`（server.py:4854），迭代顺序随
    # 进程变化。两者相同即平局，返回顺序随之变成未定义值。详见
    # test_fixture_determinism.py::test_meeting_timestamps_are_distinct。
    # 取"晚一天"是顺带贴合语义的：进行中的课晚于已结束的课。
    db.add(Meeting(
        id=2, class_code="CLS2026002", teacher_id=1,
        topic="测试课堂：细胞呼吸", status="active",
        knowledge_points=[], created_at=BASE_TIME + timedelta(days=1),
    ))

    for i, (uid, text) in enumerate([
        (2, "我认为光合作用需要光照和叶绿体"),
        (3, "还有二氧化碳和水"),
        (2, "产物是葡萄糖和氧气"),
    ]):
        db.add(Transcript(
            meeting_id=1, user_id=uid, content=text,
            audio_file_path=f"storage/audio_chunks/seg_{i}.wav",
            relevance_score=80, quality_score=85,
            emotion_tag="专注", body_action="举手", audio_tone="平稳",
            timestamp=BASE_TIME + timedelta(minutes=i),
            created_at=BASE_TIME + timedelta(minutes=i),
        ))

    # 第二节的发言：6 条 / 2 人，使 active-groups 的活跃度计算
    # （base + volume + breadth）与状态标签全部落在非零分支上
    for i in range(6):
        db.add(Transcript(
            meeting_id=2, user_id=2 if i % 2 == 0 else 3,
            content=f"关于细胞呼吸的第 {i + 1} 次发言",
            audio_file_path=f"storage/audio_chunks/m2_seg_{i}.wav",
            relevance_score=75, quality_score=80,
            emotion_tag="专注", body_action="听讲", audio_tone="平稳",
            timestamp=BASE_TIME + timedelta(minutes=i),
            created_at=BASE_TIME + timedelta(minutes=i),
        ))

    db.add_all([
        EmotionLog(
            meeting_id=1, user_id=2, emotion_type="专注", intensity=0.8,
            snapshot_path="storage/snapshots/s1.jpg",
            video_url="storage/video_chunks/v1.mp4",
            video_start_time=0.0, created_at=BASE_TIME,
        ),
        AIInsight(
            meeting_id=1, target_user="李同学", type="participation",
            content="课堂参与度较高", created_at=BASE_TIME,
        ),
        KnowledgeGraph(
            meeting_id=1,
            graph_data={"nodes": [{"id": "n1", "label": "光合作用"}], "edges": []},
            created_at=BASE_TIME, updated_at=BASE_TIME,
        ),
        MemberConnection(
            meeting_id=1, user_id=2, username="李同学",
            is_online=1, video_enabled=1, audio_enabled=1,
            joined_at=BASE_TIME, last_heartbeat=BASE_TIME,
        ),
        ViewpointVote(
            meeting_id=1, vote_session_id="vote-1",
            viewpoints=[{"id": 1, "text": "观点一"}, {"id": 2, "text": "观点二"}],
            votes={"1": [2]}, status="closed", created_at=BASE_TIME,
        ),
        MentalHealthAssessment(
            user_id=2, meeting_id=1, risk_level="normal",
            assessment_data={"note": "合成数据"}, created_at=BASE_TIME,
        ),
        ReportTemplate(
            teacher_id=1, filename="默认模板.docx",
            filepath="storage/templates/default.docx", is_default=1,
            created_at=BASE_TIME,
        ),
    ])

    report = LearningReport(
        id=1, meeting_id=1, user_id=2,
        report_data={"summary": "合成了一份学习报告", "score": 88},
        created_at=BASE_TIME,
    )
    db.add(report)

    db.add_all([
        Exercise(
            id=1, report_id=1, question="光合作用的产物是什么？",
            question_type="简答题", options=None,
            answer="葡萄糖和氧气", knowledge_tag="光合作用",
            difficulty=0.4, estimated_time=120,
        ),
        Exercise(
            id=2, report_id=1, question="光合作用发生在哪个细胞器？",
            question_type="选择题",
            options=["线粒体", "叶绿体", "核糖体", "高尔基体"],
            answer="叶绿体", knowledge_tag="光合作用",
            difficulty=0.3, estimated_time=60,
        ),
    ])

    db.add(StudentAnswer(
        exercise_id=1, user_id=2, answer_content="葡萄糖和氧气",
        is_correct=1, submitted_at=BASE_TIME,
    ))

    db.commit()
    return _known_ids()


def _known_ids() -> dict:
    """合成数据的固定 ID 约定，供各测试引用。"""
    return {
        "teacher_id": 1,
        "student_id": 2,
        "student_id_b": 3,
        "meeting_id": 1,
        "meeting_id_active": 2,
        "report_id": 1,
        "exercise_id": 1,
        "template_id": 1,
    }
