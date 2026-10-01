"""情绪统计域的路由。

本组 2 条，是"一节课的情绪/互动汇总"这一族：

    GET /api/realtime-stats/{meeting_id}    实时统计：饼图、互动网络、时间线、成员得分
    GET /api/emotion-details/{meeting_id}   情绪明细：个人/群体时间线、视频片段、发言

本组带走 `emotion_value_for_label`——它把归一化后的情绪标签映射成 0-100 的
"情绪分"，只有这两条路由用得上。

另两个依赖住在中立模块里（都不能 `from server import ...`，见
`app/routers/__init__.py`）：
  * `normalize_emotion_label` ← `app.core.emotions`
  * `resolve_user_by_identifier` ← `app.services.user_lookup`
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.emotions import normalize_emotion_label
from app.models import EmotionLog, Transcript
from app.services.user_lookup import resolve_user_by_identifier

router = APIRouter()

@router.get("/api/realtime-stats/{meeting_id}")
async def get_realtime_stats(meeting_id: int, db: Session = Depends(get_db)):
    """获取实时统计数据"""
    try:
        import time
        start_time = time.time()
        print(f"[TIME] [realtime-stats] 开始查询 meeting_id={meeting_id}")

        # 使用joinedload优化查询
        from sqlalchemy.orm import joinedload

        # [OK] 查询转录
        transcripts = db.query(Transcript).options(
            joinedload(Transcript.user)
        ).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.timestamp.desc()).all()

        # 反转顺序
        transcripts.reverse()

        print(f"  [OK] 查询到 {len(transcripts)} 条发言: {time.time() - start_time:.2f}秒")

        # [OK] 查询情绪
        emotions = db.query(EmotionLog).options(
            joinedload(EmotionLog.user)
        ).filter(
            EmotionLog.meeting_id == meeting_id
        ).order_by(EmotionLog.created_at.desc()).all()

        emotions.reverse()

        print(f"  [OK] 查询到 {len(emotions)} 条情绪: {time.time() - start_time:.2f}秒")

        # 1. 发言统计
        speech_stats = {}
        user_transcripts = {}  # 保存每个用户的发言
        for t in transcripts:
            username = t.user.username
            speech_stats[username] = speech_stats.get(username, 0) + 1
            if username not in user_transcripts:
                user_transcripts[username] = []
            user_transcripts[username].append(t.content)

        pie_data = [{'name': k, 'value': v} for k, v in speech_stats.items()]

        # 2. 互动网络
        users = list(speech_stats.keys())
        interaction_matrix = {u: {u2: 0 for u2 in users} for u in users}

        # 统计互动
        for i in range(1, len(transcripts)):
            prev_user = transcripts[i-1].user.username
            curr_user = transcripts[i].user.username
            if prev_user != curr_user:
                interaction_matrix[prev_user][curr_user] += 1
                interaction_matrix[curr_user][prev_user] += 1

        # 转换为ECharts格式
        nodes = [{'name': u, 'value': speech_stats[u]} for u in users]
        edges = []
        for u1 in users:
            for u2 in users:
                if u1 < u2 and interaction_matrix[u1][u2] > 0:
                    edges.append({
                        'source': u1,
                        'target': u2,
                        'value': interaction_matrix[u1][u2]
                    })

        # 3. 情绪时间线
        emotion_timeline = {}
        user_emotions = {}  # 保存每个用户的情绪
        for e in emotions:
            username = e.user.username
            if username not in emotion_timeline:
                emotion_timeline[username] = []
                user_emotions[username] = []
            
            emotion_type = normalize_emotion_label(e.emotion_type)
            emotion_value = emotion_value_for_label(emotion_type)
            
            emotion_timeline[username].append({
                'time': e.created_at.isoformat(),
                'value': emotion_value,
                'emotion': emotion_type
            })
            user_emotions[username].append(emotion_value)
        
        # 4. 成员综合评分
        member_scores = []
        total_speeches = sum(speech_stats.values()) if speech_stats else 1

        # 收集每个用户的quality_score
        user_quality_scores = {}
        for t in transcripts:
            username = t.user.username
            if username not in user_quality_scores:
                user_quality_scores[username] = []
            if hasattr(t, 'quality_score') and t.quality_score:
                user_quality_scores[username].append(t.quality_score)

        for username in users:
            speech_count = speech_stats.get(username, 0)

            # LLM评分50分满分
            quality_scores = user_quality_scores.get(username, [])
            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 50
            llm_score = avg_quality * 0.5  # 0-50分

            # 参与度25分满分
            speech_ratio = speech_count / total_speeches
            if 0.15 <= speech_ratio <= 0.35:
                participation_score = 25
            elif speech_ratio < 0.15:
                participation_score = max(10, 25 * (speech_ratio / 0.15))
            else:
                participation_score = max(15, 25 - (speech_ratio - 0.35) * 50)

            # 互动性15分满分
            interaction_count = sum(interaction_matrix.get(username, {}).values())
            interaction_score = min(15, interaction_count * 2.5)

            # 情绪状态10分满分- 积极情绪加分
            avg_emotion = sum(user_emotions.get(username, [50])) / len(user_emotions.get(username, [50]))
            emotion_score = avg_emotion * 0.1  # 0-10分

            total_score = int(llm_score + participation_score + interaction_score + emotion_score)
            total_score = max(0, min(100, total_score))  # 限制在0-100

            # 获取最新反馈
            latest_feedback = ""
            for t in reversed(transcripts):
                if t.user.username == username and hasattr(t, 'quality_feedback') and t.quality_feedback:
                    latest_feedback = t.quality_feedback
                    break
            
            member_scores.append({
                'name': username,
                'score': total_score,
                'speech_count': speech_count,
                'interaction_count': interaction_count,
                'avg_emotion': int(avg_emotion),
                'avg_quality': int(avg_quality),
                'latest_feedback': latest_feedback
            })
        
        # ??
        member_scores.sort(key=lambda x: x['score'], reverse=True)
        
        print(f"  [OK] ??: {time.time() - start_time:.2f}??")
        
        return {
            'status': 'success',
            'pie_data': pie_data,
            'interaction': {'nodes': nodes, 'edges': edges},
            'emotion_timeline': emotion_timeline,
            'member_scores': member_scores
        }
    except Exception as e:
        print(f'[ERROR] ??: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(e)}


# 情绪详情 API
@router.get("/api/emotion-details/{meeting_id}")
async def get_emotion_details(
    meeting_id: int,
    username: str = None,
    minutes: int = 15,
    db: Session = Depends(get_db)
):
    """获取情绪详细数据"""
    try:
        import time
        start_time = time.time()
        print(f"[TIME] [emotion-details] 开始查询 meeting_id={meeting_id}")
        # minutes 支持:
        # - 5/15/30: 最近 N 分钟
        # - 0: 整节课（不过滤时间）
        allowed_windows = {0, 5, 15, 30}
        if minutes not in allowed_windows:
            minutes = 15
        cutoff_time = datetime.now() - timedelta(minutes=minutes) if minutes > 0 else None

        # 使用joinedload避免N+1查询问题
        from sqlalchemy.orm import joinedload

        # [OK] 查询情绪
        emotion_query = db.query(EmotionLog).options(
            joinedload(EmotionLog.user)
        ).filter(
            EmotionLog.meeting_id == meeting_id
        )
        if cutoff_time is not None:
            emotion_query = emotion_query.filter(EmotionLog.created_at >= cutoff_time)
        emotions = emotion_query.order_by(EmotionLog.created_at.desc()).all()

        print(f"  [OK] 查询到 {len(emotions)} 条情绪: {time.time() - start_time:.2f}秒")

        # [OK] 查询转录
        transcript_query = db.query(Transcript).options(
            joinedload(Transcript.user)
        ).filter(
            Transcript.meeting_id == meeting_id
        )
        if cutoff_time is not None:
            transcript_query = transcript_query.filter(Transcript.timestamp >= cutoff_time)
        transcripts = transcript_query.order_by(Transcript.timestamp.desc()).all()

        print(f"  [OK] 查询到 {len(transcripts)} 条发言: {time.time() - start_time:.2f}秒")

        # 反转顺序
        emotions.reverse()
        transcripts.reverse()

        # 1. 个人情绪时间线 (智能采样：动态间隔 + 大幅波动时额外记录)
        individual_emotions = {}
        last_emotion_by_user = {}      # {username: last_emotion_value}
        last_point_time_by_user = {}   # {username: last_point_timestamp}

        # 动态采样间隔：根据课堂时长自适应
        # 短课堂（<30分钟）：2分钟间隔
        # 中等课堂（30-60分钟）：5分钟间隔
        # 长课堂（>60分钟）：10分钟间隔
        if emotions:
            course_duration_minutes = (emotions[-1].created_at - emotions[0].created_at).total_seconds() / 60
            if course_duration_minutes < 30:
                INTERVAL_SECONDS = 2 * 60   # 2分钟
            elif course_duration_minutes < 60:
                INTERVAL_SECONDS = 5 * 60   # 5分钟
            else:
                INTERVAL_SECONDS = 10 * 60  # 10分钟
        else:
            INTERVAL_SECONDS = 2 * 60       # 默认2分钟

        BIG_SHIFT_THRESHOLD = 15       # 情绪值变化超过15视为大幅波动

        for e in emotions:
            uname = e.user.username
            if uname not in individual_emotions:
                individual_emotions[uname] = []

            emotion_type = normalize_emotion_label(e.emotion_type)
            emotion_value = emotion_value_for_label(emotion_type)

            current_ts = e.created_at.timestamp()
            should_add = False

            if uname not in last_emotion_by_user:
                # 第一个点，必须加
                should_add = True
            else:
                last_val = last_emotion_by_user[uname]
                last_ts = last_point_time_by_user[uname]
                time_gap = current_ts - last_ts

                # 大幅情绪波动（即使在15分钟内也要加）
                if abs(emotion_value - last_val) >= BIG_SHIFT_THRESHOLD:
                    should_add = True
                # 超过15分钟间隔，保底加一个点
                elif time_gap >= INTERVAL_SECONDS:
                    should_add = True

            if should_add:
                last_emotion_by_user[uname] = emotion_value
                last_point_time_by_user[uname] = current_ts
                individual_emotions[uname].append({
                    'id': e.id,
                    'time': e.created_at.isoformat(),
                    'timestamp': int(e.created_at.timestamp() * 1000),
                    'emotion_type': emotion_type,
                    'emotion_value': emotion_value,
                    'intensity': e.intensity,
                    'snapshot_path': e.snapshot_path
                })

        # 确保每个用户的最后一个情绪记录也被包含（折线不会断在中间）
        for e in reversed(emotions):
            uname = e.user.username
            if uname in individual_emotions and individual_emotions[uname]:
                last_point = individual_emotions[uname][-1]
                if last_point['id'] != e.id:
                    emotion_type = normalize_emotion_label(e.emotion_type)
                    emotion_value = emotion_value_for_label(emotion_type)
                    individual_emotions[uname].append({
                        'id': e.id,
                        'time': e.created_at.isoformat(),
                        'timestamp': int(e.created_at.timestamp() * 1000),
                        'emotion_type': emotion_type,
                        'emotion_value': emotion_value,
                        'intensity': e.intensity,
                        'snapshot_path': e.snapshot_path
                    })
                # 只处理每个用户一次
                last_emotion_by_user.pop(uname, None)
            if not last_emotion_by_user:
                break

        # 2. 全班情绪趋势
        all_emotions_timeline = []
        time_buckets = {}  # 按分钟聚合

        for e in emotions:
            time_key = e.created_at.strftime('%Y-%m-%d %H:%M')  # 按分钟分组
            if time_key not in time_buckets:
                time_buckets[time_key] = []

            emotion_type = normalize_emotion_label(e.emotion_type)
            emotion_value = emotion_value_for_label(emotion_type)
            
            time_buckets[time_key].append(emotion_value)
        
        for time_key in sorted(time_buckets.keys()):
            values = time_buckets[time_key]
            avg_value = sum(values) / len(values) if values else 50
            all_emotions_timeline.append({
                'time': time_key,
                'value': int(avg_value),
                'count': len(values)
            })
        
        # 3. 视频片段列表
        video_segments = []
        for t in transcripts:
            if t.audio_file_path:
                # 推测视频路径
                video_path = t.audio_file_path.replace('audio_chunks', 'video_chunks').replace('.wav', '.webm')

                video_segments.append({
                    'id': t.id,
                    'username': t.user.username,
                    'text': t.content,
                    'emotion': t.emotion_tag or 'neutral',
                    'timestamp': int(t.timestamp.timestamp() * 1000),
                    'time': t.timestamp.isoformat(),
                    'video_path': video_path,
                    'audio_path': t.audio_file_path
                })

        print(f"  [OK] 处理完成: {time.time() - start_time:.2f}秒")

        # 如果指定了username，个体情绪只返回该用户自己的数据（隐私保护）
        # 但群体情绪图表需要所有人的数据，所以返回两份
        filtered_individual = individual_emotions
        current_user_key = None
        if username:
            filtered_individual = {}
            candidate_keys = {str(username)}
            resolved_user = resolve_user_by_identifier(db, username)
            if resolved_user:
                if getattr(resolved_user, "username", None):
                    candidate_keys.add(str(resolved_user.username))
                if getattr(resolved_user, "student_id", None):
                    candidate_keys.add(str(resolved_user.student_id))

            for key in candidate_keys:
                if key in individual_emotions:
                    filtered_individual[key] = individual_emotions[key]
                    current_user_key = key
                    break

            # 兼容旧数据：如果查询参数没对上，但该课堂只有一个人的情绪曲线，
            # 不返回空图，直接给学生端展示这条曲线。
            if not filtered_individual and len(individual_emotions) == 1:
                current_user_key = next(iter(individual_emotions.keys()))
                filtered_individual[current_user_key] = individual_emotions[current_user_key]

        return {
            'status': 'success',
            'individual_emotions': filtered_individual,  # 个体图表用（可能被过滤）
            'all_individual_emotions': individual_emotions,  # 群体图表用（完整数据）
            'group_emotion_timeline': all_emotions_timeline,
            'video_segments': video_segments,
            'current_user_key': current_user_key
        }
    except Exception as e:
        print(f'[ERROR] ??a??: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(e)}


def emotion_value_for_label(label: str) -> int:
    values = {
        "excited": 92,
        "happy": 85,
        "surprised": 75,
        "calm": 60,
        "neutral": 50,
        "thinking": 45,
        "confused": 35,
        "sad": 25,
        "angry": 15,
    }
    return values.get(normalize_emotion_label(label), 50)
