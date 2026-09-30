# -*- coding: utf-8 -*-
"""
[EMOJI]OSS[EMOJI]
"""
import oss2
from oss_config import OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, OSS_BUCKET_NAME, OSS_ENDPOINT

print("="*50)
print("[EMOJI]OSS[EMOJI]")
print("="*50)

print(f"\n[LIST] [EMOJI]:")
print(f"  AccessKey ID: {OSS_ACCESS_KEY_ID[:10]}...")
print(f"  Bucket[EMOJI]: {OSS_BUCKET_NAME}")
print(f"  Endpoint: {OSS_ENDPOINT}")

try:
    print(f"\n[DB] [EMOJI]...")
    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    
    print(f"[DATA] [EMOJI]Bucket[EMOJI]...")
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME, connect_timeout=10)
    
    print(f"[OK] [EMOJI]...")
    # [EMOJI]
    result = bucket.list_objects(max_keys=1)
    
    print(f"\n[OK] OSS[EMOJI]")
    print(f"[STATS] Bucket[EMOJI]:")
    print(f"  - Bucket[EMOJI]: {OSS_BUCKET_NAME}")
    print(f"  - Endpoint: {OSS_ENDPOINT}")
    print(f"  - [EMOJI]: {len(result.object_list)}")
        
except oss2.exceptions.NoSuchBucket:
    print(f"\n[ERROR] Bucket[EMOJI]")
    print(f"\n[EMOJI]")
    print(f"  1. [EMOJI]OSS[EMOJI]: https://oss.console.aliyun.com/")
    print(f"  2. [EMOJI]Bucket[EMOJI]: {OSS_BUCKET_NAME}")
    print(f"  3. [EMOJI]Bucket[EMOJI]")
    
except oss2.exceptions.AccessDenied:
    print(f"\n[ERROR] [EMOJI]")
    print(f"\n[EMOJI]")
    print(f"  1. AccessKey ID[EMOJI]Secret[EMOJI]")
    print(f"  2. AccessKey[EMOJI]OSS[EMOJI]")
    
except oss2.exceptions.RequestError as e:
    print(f"\n[ERROR] [EMOJI]: {e}")
    print(f"\n[EMOJI]")
    print(f"  1. [EMOJI]")
    print(f"  2. Endpoint[EMOJI]")
    print(f"  3. [EMOJI]OSS[EMOJI]")
    
except Exception as e:
    print(f"\n[ERROR] [EMOJI]: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*50)
