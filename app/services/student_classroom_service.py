"""Read-only personal classroom overview; all records are scoped by user ID."""
from collections import Counter

from app.models import EmotionLog, Transcript


def build_student_classroom_overview(db, meeting, student):
    rows = db.query(Transcript).filter(Transcript.meeting_id == meeting.id, Transcript.user_id == student.id).order_by(Transcript.timestamp, Transcript.id).all()
    emotions = db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting.id, EmotionLog.user_id == student.id).order_by(EmotionLog.created_at).all()
    origin = meeting.started_at or meeting.created_at
    counts = Counter()
    speeches = []
    for row in rows:
        second = max(0, (row.timestamp - origin).total_seconds())
        bucket = int(second // 300)
        counts[bucket] += 1
        speeches.append({'id': row.id, 'text': row.content, 'second': second, 'bucket': bucket,
                         'quality': row.quality_score, 'relevance': row.relevance_score,
                         'feedback': row.quality_feedback})
    def average(field):
        values = [getattr(row, field) for row in rows if getattr(row, field) is not None]
        return round(sum(values) / len(values), 1) if values else None
    return {'status': 'success', 'student': {'name': student.username, 'student_id': student.student_id},
            'meeting': {'topic': meeting.topic, 'class_code': meeting.class_code, 'status': meeting.status,
                        'goals': meeting.knowledge_points or []},
            'summary': {'speech_count': len(rows), 'average_quality': average('quality_score'), 'average_relevance': average('relevance_score')},
            'distribution': [{'bucket': i, 'label': f'{i * 5}–{(i + 1) * 5}分钟', 'count': counts[i]} for i in range(max(counts, default=-1) + 1)],
            'speeches': speeches,
            'emotions': [{'second': max(0, (row.created_at - origin).total_seconds()), 'label': (row.emotion_type or 'neutral').split('|')[0]} for row in emotions]}
