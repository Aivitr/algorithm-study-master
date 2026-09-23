# -*- coding: utf-8 -*-
"""
[EMOJI]Bucket[EMOJI]
"""
import oss2
from oss_config import OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, OSS_BUCKET_NAME

# [EMOJI]Endpoint
ENDPOINTS = [
    ('[EMOJI]1-[EMOJI]', 'oss-cn-hangzhou.aliyuncs.com'),
    ('[EMOJI]2-[EMOJI]', 'oss-cn-shanghai.aliyuncs.com'),
    ('[EMOJI]1-[EMOJI]', 'oss-cn-qingdao.aliyuncs.com'),
    ('[EMOJI]2-[EMOJI]', 'oss-cn-beijing.aliyuncs.com'),
    ('[EMOJI]3-[EMOJI]', 'oss-cn-zhangjiakou.aliyuncs.com'),
    ('[EMOJI]1-[EMOJI]', 'oss-cn-shenzhen.aliyuncs.com'),
    ('[EMOJI]2-[EMOJI]', 'oss-cn-heyuan.aliyuncs.com'),
    ('[EMOJI]1-[EMOJI]', 'oss-cn-chengdu.aliyuncs.com'),
]

print("="*60)
print(f"[ZOOM] [EMOJI]Bucket: {OSS_BUCKET_NAME}")
print("="*60)

auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)

for region, endpoint in ENDPOINTS:
    try:
        print(f"\n[EMOJI] [EMOJI] {region} ({endpoint})...")
        bucket = oss2.Bucket(auth, endpoint, OSS_BUCKET_NAME, connect_timeout=5)
        result = bucket.list_objects(max_keys=1)
        
        print(f"[OK] [EMOJI]Bucket[EMOJI]: {region}")
        print(f"[STATS] Endpoint: {endpoint}")
        print(f"[FILE] [EMOJI]: {len(result.object_list)}")
        print(f"\n[EMOJI] oss_config.py [EMOJI]:")
        print(f'OSS_ENDPOINT = "{endpoint}"')
        break
        
    except oss2.exceptions.NoSuchBucket:
        print(f"   [WARN] Bucket[EMOJI]")
    except oss2.exceptions.AccessDenied:
        print(f"   [ERROR] [EMOJI]Bucket[EMOJI]")
    except Exception as e:
        print(f"   [ERROR] [EMOJI]: {e}")

print("\n" + "="*60)
