import os
import sys
import traceback

from oss_utils import get_oss_manager
from aliyun_emotion_client import AliyunEmotionClient


def main():
    print(">>> start aliyun expression test")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    snap_dir = os.path.join(base_dir, "storage", "snapshots")
    print("snap_dir:", snap_dir)

    # 允许通过命令行指定文件
    if len(sys.argv) > 1:
        filename = sys.argv[1]
        if os.path.isabs(filename):
            local_path = filename
        else:
            local_path = os.path.join(snap_dir, filename)
        
        if not os.path.isfile(local_path):
            print(f"指定的图片不存在: {local_path}")
            return
        print(f"使用指定快照: {local_path}")
    else:
        if not os.path.isdir(snap_dir):
            print("snapshots 目录不存在")
            return

        files = [f for f in os.listdir(snap_dir) if f.lower().endswith(".jpg")]
        print("found jpg files:", len(files))

        if not files:
            print("snapshots 目录里没有 jpg 文件")
            return

        # 之前是取最新的一张，但最新的几张可能是一片漆黑（文件体积很小）
        # 我们根据文件大小排序，取一张大一点的，通常包含更多细节（人脸）
        file_details = []
        for f in files:
            path = os.path.join(snap_dir, f)
            file_details.append((f, os.path.getsize(path)))
        
        # 按文件大小降序排列
        file_details.sort(key=lambda x: x[1], reverse=True)
        
        filename, size = file_details[0]
        local_path = os.path.join(snap_dir, filename)
        print(f"自动选择本地快照: {local_path} (大小: {size} bytes)")

    oss_mgr = get_oss_manager()
    print("get_oss_manager OK")

    # 这里 user_id / meeting_id 随便给个测试值即可
    oss_url = oss_mgr.upload_snapshot(local_path, user_id=1, meeting_id=1)
    print("上传到 OSS 的 URL:", oss_url)

    client = AliyunEmotionClient()
    print("AliyunEmotionClient OK")

    label, score = client.recognize_expression_by_url(oss_url)
    print("阿里云表情识别结果:", label, score)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(">>> ERROR in test_aliyun_expression:", e)
        traceback.print_exc()