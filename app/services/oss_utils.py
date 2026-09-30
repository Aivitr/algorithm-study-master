# -*- coding: utf-8 -*-
"""
[EMOJI]OSS[EMOJI]
"""
import oss2
import os
from datetime import datetime
from app.services.oss_config import (
    OSS_ACCESS_KEY_ID,
    OSS_ACCESS_KEY_SECRET,
    OSS_BUCKET_NAME,
    OSS_ENDPOINT,
    OSS_DOMAIN,
    VIDEO_PREFIX,
    SNAPSHOT_PREFIX
)


class OSSManager:
    """[EMOJI]OSS[EMOJI]"""
    
    def __init__(self):
        """[EMOJI]OSS[EMOJI]"""
        try:
            # [EMOJI]
            self.auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
            
            # [EMOJI]Bucket[EMOJI]
            self.bucket = oss2.Bucket(
                self.auth, 
                OSS_ENDPOINT, 
                OSS_BUCKET_NAME,
                connect_timeout=30  # [EMOJI]30[EMOJI]
            )
            
            print(f"[OK] OSS[EMOJI]: {OSS_BUCKET_NAME}")
        except Exception as e:
            print(f"[ERROR] OSS[EMOJI]: {e}")
            # [EMOJI]
            self.bucket = None
    
    def upload_video(self, local_path: str, user_id: int, meeting_id: int) -> str:
        """
        [EMOJI]OSS
        
        Args:
            local_path: [EMOJI]
            user_id: [EMOJI]ID
            meeting_id: [EMOJI]ID
        
        Returns:
            [EMOJI]URL
        """
        if not self.bucket:
            raise Exception("OSS[EMOJI]")
            
        try:
            # [EMOJI]OSS[EMOJI]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            file_ext = os.path.splitext(local_path)[1]  # [EMOJI]
            oss_path = f"{VIDEO_PREFIX}meeting_{meeting_id}/user_{user_id}/{timestamp}{file_ext}"
            
            # [EMOJI]
            with open(local_path, 'rb') as f:
                result = self.bucket.put_object(
                    oss_path, 
                    f,
                    headers={'x-oss-request-timeout': '120'}  # 120[EMOJI]
                )
            
            if result.status == 200:
                video_url = f"{OSS_DOMAIN}/{oss_path}"
                print(f"[OK] [EMOJI]: {video_url}")
                return video_url
            else:
                raise Exception(f"[EMOJI]: {result.status}")
                
        except Exception as e:
            print(f"[ERROR] [EMOJI]: {e}")
            raise
    
    def upload_snapshot(self, local_path: str, user_id: int, meeting_id: int) -> str:
        """
        [EMOJI]OSS
        
        Args:
            local_path: [EMOJI]
            user_id: [EMOJI]ID
            meeting_id: [EMOJI]ID
        
        Returns:
            [EMOJI]URL
        """
        if not self.bucket:
            raise Exception("OSS[EMOJI]")
            
        try:
            # [EMOJI]OSS[EMOJI]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            file_ext = os.path.splitext(local_path)[1]
            oss_path = f"{SNAPSHOT_PREFIX}meeting_{meeting_id}/user_{user_id}/{timestamp}{file_ext}"
            
            # [EMOJI]
            with open(local_path, 'rb') as f:
                result = self.bucket.put_object(
                    oss_path, 
                    f,
                    headers={'x-oss-request-timeout': '120'}
                )
            
            if result.status == 200:
                snapshot_url = f"{OSS_DOMAIN}/{oss_path}"
                print(f"[OK] [EMOJI]: {snapshot_url}")
                return snapshot_url
            else:
                raise Exception(f"[EMOJI]: {result.status}")
                
        except Exception as e:
            print(f"[ERROR] [EMOJI]: {e}")
            raise
    
    def delete_video(self, oss_url: str) -> bool:
        """
        [EMOJI]OSS[EMOJI]
        
        Args:
            oss_url: [EMOJI]OSS URL
        
        Returns:
            [EMOJI]
        """
        try:
            # [EMOJI]URL[EMOJI]OSS[EMOJI]
            oss_path = oss_url.replace(f"{OSS_DOMAIN}/", "")
            
            # [EMOJI]
            result = self.bucket.delete_object(oss_path)
            
            if result.status == 204:
                print(f"[OK] [EMOJI]: {oss_path}")
                return True
            else:
                print(f"[WARN] [EMOJI]: {result.status}")
                return False
                
        except Exception as e:
            print(f"[ERROR] [EMOJI]: {e}")
            return False

    def upload_voiceprint(self, local_path: str, username: str) -> str:
        """
        上传声纹音频到OSS

        Args:
            local_path: 本地音频文件路径
            username: 用户名

        Returns:
            音频文件的OSS URL
        """
        if not self.bucket:
            raise Exception("OSS未初始化")

        try:
            # 生成OSS路径
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            file_ext = os.path.splitext(local_path)[1]
            oss_path = f"voiceprints/{username}/{timestamp}{file_ext}"

            # 上传文件
            with open(local_path, 'rb') as f:
                result = self.bucket.put_object(
                    oss_path,
                    f,
                    headers={'x-oss-request-timeout': '60'}
                )

            if result.status == 200:
                audio_url = f"{OSS_DOMAIN}/{oss_path}"
                print(f"[OK] 声纹音频上传成功: {audio_url}")
                return audio_url
            else:
                raise Exception(f"上传失败: {result.status}")

        except Exception as e:
            print(f"[ERROR] 声纹音频上传失败: {e}")
            raise

    def delete_voiceprint(self, oss_url: str) -> bool:
        """
        删除OSS上的声纹音频

        Args:
            oss_url: 音频文件的OSS URL

        Returns:
            是否删除成功
        """
        try:
            # 从URL中提取OSS路径
            oss_path = oss_url.replace(f"{OSS_DOMAIN}/", "")

            # 删除文件
            result = self.bucket.delete_object(oss_path)

            if result.status == 204:
                print(f"[OK] 声纹音频删除成功: {oss_path}")
                return True
            else:
                print(f"[WARN] 删除失败: {result.status}")
                return False

        except Exception as e:
            print(f"[ERROR] 声纹音频删除失败: {e}")
            return False

    def check_file_exists(self, oss_url: str) -> bool:
        """
        [EMOJI]
        
        Args:
            oss_url: [EMOJI]OSS URL
        
        Returns:
            [EMOJI]
        """
        try:
            oss_path = oss_url.replace(f"{OSS_DOMAIN}/", "")
            return self.bucket.object_exists(oss_path)
        except Exception as e:
            print(f"[ERROR] [EMOJI]: {e}")
            return False


# [EMOJI]OSS[EMOJI]
oss_manager = None

def get_oss_manager():
    """[EMOJI]OSS[EMOJI]"""
    global oss_manager
    if oss_manager is None:
        oss_manager = OSSManager()
    return oss_manager
