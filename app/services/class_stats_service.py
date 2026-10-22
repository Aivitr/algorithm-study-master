"""课堂级统计口径（只读）。

把原先散在教师域、学生统计域与会议域里的聚合和评分公式收成一处：
  - activity_map / window_map       共享聚合（委托 meeting_metrics，单一实现）
  - class_score / score_level       课堂活跃度评分与等级（原先三处重复）
  - active_status_tag               活跃/一般/冷清标签
  - emotion_counts                  情绪标签分布
  - participant_count / user_speech_count

本类是**只读**的：不写入、不提交事务。
"""

from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.emotions import normalize_emotion_label
from app.models import EmotionLog, Transcript
from app.services.meeting_metrics import (
    _build_meeting_activity_map,
    _build_meeting_window_map,
)


class ClassStatsService:
    def __init__(self, db: Optional[Session] = None):
        self.db = db

    # ------------------------------------------------------------- 共享聚合
    def activity_map(
        self, meeting_ids: List[int], *, exclude_teacher: bool = True
    ) -> Dict[int, Dict[str, int]]:
        return _build_meeting_activity_map(
            self.db, meeting_ids, exclude_teacher=exclude_teacher
        )

    def window_map(self, meeting_ids: List[int]) -> Dict[int, Dict]:
        return _build_meeting_window_map(self.db, meeting_ids)

    # ------------------------------------------------------- 确定性计算口径
    @staticmethod
    def class_score(speech_count: int, member_count: int) -> int:
        """课堂活跃度评分：人均发言 0~60 + 总量 0~30 + 参与广度 0~10。"""
        avg_speech = speech_count / max(member_count, 1)
        base = min(60.0, avg_speech * 12.0)
        volume = min(30.0, speech_count * 0.8)
        breadth = min(10.0, member_count * 1.0)
        return int(min(100.0, base + volume + breadth))

    @staticmethod
    def score_level(score: int) -> Tuple[str, str]:
        if score >= 80:
            return ("优秀", "green")
        if score >= 60:
            return ("良好", "yellow")
        return ("待提高", "red")

    @staticmethod
    def active_status_tag(speech_count: int, avg_speech: float) -> str:
        if speech_count < 5:
            return "冷清"
        if avg_speech < 2:
            return "一般"
        return "活跃"

    @staticmethod
    def window_duration_minutes(first_at, last_at) -> int:
        if first_at and last_at:
            return max(0, int((last_at - first_at).total_seconds() / 60))
        return 0

    # ------------------------------------------------------------- 情绪分布
    def emotion_counts(self, meeting_id: int) -> Dict[str, int]:
        rows = (
            self.db.query(EmotionLog.emotion_type, func.count(EmotionLog.id))
            .filter(EmotionLog.meeting_id == meeting_id)
            .group_by(EmotionLog.emotion_type)
            .all()
        )
        counts: Dict[str, int] = {}
        for emotion_type, count in rows:
            label = normalize_emotion_label(emotion_type)
            counts[label] = counts.get(label, 0) + int(count)
        return counts

    # --------------------------------------------------------- 发言计数口径
    def participant_count(self, meeting_id: int) -> int:
        """发言过的不同用户数（与历史行为一致：含教师记录）。"""
        return (
            self.db.query(Transcript.user_id)
            .filter(Transcript.meeting_id == meeting_id)
            .distinct()
            .count()
        )

    def user_speech_count(self, meeting_id: int, user_id: int) -> int:
        return (
            self.db.query(Transcript)
            .filter(
                Transcript.meeting_id == meeting_id,
                Transcript.user_id == user_id,
            )
            .count()
        )
