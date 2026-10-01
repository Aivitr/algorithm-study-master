"""快照与视频上下文域的路由。

本组 2 条，都是"按时间点回看某节课当时的画面与发言"这一族：

    GET /api/snapshot/{meeting_id}      指定时间点的情绪快照（含截图路径）
    GET /api/get-video-context          指定时间点前后的视频片段与发言

两条都用 ±N 秒窗口去查 `EmotionLog`，因此对**时区**敏感：
`datetime.fromtimestamp()` 按本地时区还原入参。行为基线的两条用例据此从
`BASE_TIME` 反推时间戳，而不是硬编码——见 `tests_safe/test_route_baseline.py`。

`resolve_user_by_identifier` 来自 `app.services.user_lookup`（它被三块业务共用，
因此住在中立模块里）；不能 `from server import ...`，见 `app/routers/__init__.py`。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import EmotionLog
from app.services.user_lookup import resolve_user_by_identifier

router = APIRouter()

@router.get("/api/snapshot/{meeting_id}")
async def get_snapshot(meeting_id: int, username: str, timestamp: int, db: Session = Depends(get_db)):
    """获取指定时间点的快照"""
    try:
        # 转换为 datetime
        from datetime import datetime
        target_time = datetime.fromtimestamp(timestamp / 1000)

        # 查询用户
        user = resolve_user_by_identifier(db, username)
        if not user:
            return {'status': 'error', 'message': '用户不存在'}

        # 查询前后5秒范围
        from sqlalchemy import and_
        from datetime import timedelta

        time_start = target_time - timedelta(seconds=5)
        time_end = target_time + timedelta(seconds=5)

        candidates = db.query(EmotionLog).filter(
            and_(
                EmotionLog.meeting_id == meeting_id,
                EmotionLog.user_id == user.id,
                EmotionLog.created_at >= time_start,
                EmotionLog.created_at <= time_end,
                EmotionLog.snapshot_path.isnot(None)
            )
        ).all()
        emotion = min(
            candidates,
            key=lambda e: abs((e.created_at - target_time).total_seconds())
        ) if candidates else None

        if emotion and emotion.snapshot_path:
            return {
                'status': 'success',
                'snapshot_path': emotion.snapshot_path,
                'emotion_type': emotion.emotion_type,
                'timestamp': int(emotion.created_at.timestamp() * 1000)
            }
        else:
            return {'status': 'error', 'message': '未找到快照'}
    except Exception as e:
        print(f'[ERROR] 获取快照失败: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(e)}


# 获取视频上下文
@router.get("/api/get-video-context")
async def get_video_context(
    meeting_id: int,
    timestamp: float,  # 时间戳
    user_id: Optional[int] = None,  # 用户ID参数（兼容旧版）
    username: Optional[str] = None,  # 用户名/学号参数
    db: Session = Depends(get_db)
):
    """
    根据时间戳获取对应的视频片段
    返回值: {video_url, jump_to_time}
    """
    try:
        print(f"[QUERY] 查询视频上下文: meeting_id={meeting_id}, user_id={user_id}, username={username}, timestamp={timestamp}")
        from datetime import datetime, timedelta

        # 转换时间戳
        if timestamp > 10000000000:  # 毫秒级
            target_time = datetime.fromtimestamp(timestamp / 1000)
        else:  # 秒级
            target_time = datetime.fromtimestamp(timestamp)

        print(f"转换后 目标时间: {target_time}")

        # 查询前后±10秒范围

        time_start = target_time - timedelta(seconds=10)
        time_end = target_time + timedelta(seconds=10)

        print(f"[ZOOM2] 时间范围: {time_start} ~ {time_end}")

        # 解析用户ID（优先显式 user_id；否则通过 username/student_id 反查）
        resolved_user_id = user_id
        if not resolved_user_id and username:
            u = resolve_user_by_identifier(db, username)
            resolved_user_id = u.id if u else None

        if not resolved_user_id:
            return {'status': 'error', 'message': '缺少有效用户标识'}

        # 查询指定meeting_id和user_id
        candidates = db.query(EmotionLog).filter(
            EmotionLog.meeting_id == meeting_id,
            EmotionLog.user_id == resolved_user_id,
            EmotionLog.created_at >= time_start,
            EmotionLog.created_at <= time_end,
            EmotionLog.video_url.isnot(None)
        ).all()
        emotion = min(
            candidates,
            key=lambda e: abs((e.created_at - target_time).total_seconds())
        ) if candidates else None

        if not emotion:
            print(f"[ERROR] 未找到视频记录")
            # 返回错误
            return {'status': 'error', 'message': '未找到对应的视频片段'}

        print(f"[OK] 找到记录: ID={emotion.id}, video_url={emotion.video_url[:80]}...")

        # 检查video_url
        if not emotion.video_url:
            return {'status': 'error', 'message': '视频URL为空'}

        video_url = str(emotion.video_url or "").replace("\\", "/")
        if video_url and (not video_url.startswith("http")) and (not video_url.startswith("/")):
            video_url = "/" + video_url

        # OSS URL检查
        if video_url.startswith('http'):
            print(f'[OK] 返回OSS链接: {video_url[:80]}...')
        else:
            print(f'[WARN] 本地URL路径: {video_url}')

        jump_to_time = emotion.video_start_time if emotion.video_start_time else 0

        return {
            'status': 'success',
            'video_url': video_url,
            'jump_to_time': jump_to_time,
            'emotion_type': emotion.emotion_type,
            'timestamp': int(emotion.created_at.timestamp() * 1000)
        }

    except Exception as e:
        print(f'[ERROR] 查询失败: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': f'查询失败: {str(e)}'}
