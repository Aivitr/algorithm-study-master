# -*- coding: utf-8 -*-
import os
from app.core import config  # 先加载 .env，确保 os.getenv 能读到 OSS 密钥
"""
[EMOJI]OSS[EMOJI]
"""

# ========== OSS[EMOJI] ==========
# [EMOJI]

# AccessKey ID[EMOJI] -> [EMOJI] -> AccessKey[EMOJI]
OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")

# AccessKey Secret
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")

# Bucket[EMOJI]OSS[EMOJI]Bucket[EMOJI]
OSS_BUCKET_NAME = "collaborative-learning-videos"

# OSS Endpoint[EMOJI]Bucket[EMOJI]
# [EMOJI]1([EMOJI]): oss-cn-hangzhou.aliyuncs.com
# [EMOJI]2([EMOJI]): oss-cn-shanghai.aliyuncs.com
# [EMOJI]2([EMOJI]): oss-cn-beijing.aliyuncs.com
# [EMOJI]1([EMOJI]): oss-cn-shenzhen.aliyuncs.com
OSS_ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"

# OSS[EMOJI]Bucket[EMOJI]
# [EMOJI]: https://{bucket_name}.{endpoint}
OSS_DOMAIN = f"https://{OSS_BUCKET_NAME}.{OSS_ENDPOINT}"

# [EMOJI]
VIDEO_PREFIX = "video_chunks/"
SNAPSHOT_PREFIX = "snapshots/"

# ========== [EMOJI] ==========
"""
1. [EMOJI] https://oss.console.aliyun.com/
2. [EMOJI]Bucket[EMOJI]
   - Bucket[EMOJI]: collaborative-learning-videos[EMOJI]
   - [EMOJI]: [EMOJI]
   - [EMOJI]: [EMOJI]
   
3. [EMOJI]AccessKey[EMOJI]
   - [EMOJI] -> AccessKey[EMOJI]
   - [EMOJI]AccessKey -> [EMOJI] AccessKey ID [EMOJI] Secret
   
4. [EMOJI]

5. [EMOJI]
   - [EMOJI]: 0.12[EMOJI]/GB/[EMOJI]
   - [EMOJI]: 0.50[EMOJI]/GB
   - [EMOJI]: 100GB[EMOJI] + [EMOJI]10GB[EMOJI] = 12 + 5 = 17[EMOJI]/[EMOJI]
"""
