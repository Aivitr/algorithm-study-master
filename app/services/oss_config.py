"""OSS 配置：完全来自环境变量（经 app.core.config 分层加载）。

这里不再写死 bucket / endpoint / domain。未配置时对应值为空，调用方会
在真正上传时失败并走本地兜底，而不是静默连到某个固定桶。
"""

from app.core.config import settings

OSS_ACCESS_KEY_ID = settings.oss.access_key_id
OSS_ACCESS_KEY_SECRET = settings.oss.access_key_secret
OSS_BUCKET_NAME = settings.oss.bucket_name
OSS_ENDPOINT = settings.oss.endpoint
OSS_DOMAIN = settings.oss.domain

VIDEO_PREFIX = settings.oss.video_prefix
SNAPSHOT_PREFIX = settings.oss.snapshot_prefix
