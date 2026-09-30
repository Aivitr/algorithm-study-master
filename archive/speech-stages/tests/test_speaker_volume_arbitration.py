#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
音量仲裁 (Speaker Volume Arbitration) 单元测试

验证内容：
1. RMS 样本添加和清理
2. 置信度计算
3. 排名系统
4. 时间窗口管理
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import manager


def test_add_rms_samples():
    """测试：添加 RMS 样本"""
    print("\n=== 测试1: 添加 RMS 样本 ===")
    
    meeting_id = "test_meeting_volume_1"
    current_time = time.time()
    
    # 添加三个用户的样本
    manager.add_audio_rms_sample(meeting_id, "user_a", 1500, current_time)
    manager.add_audio_rms_sample(meeting_id, "user_b", 800, current_time)
    manager.add_audio_rms_sample(meeting_id, "user_c", 300, current_time)
    
    print(f"✓ User A: RMS=1500")
    print(f"✓ User B: RMS=800")
    print(f"✓ User C: RMS=300")
    
    # 查看样本
    if meeting_id in manager._audio_rms_samples:
        samples = manager._audio_rms_samples[meeting_id]
        print(f"✓ 样本总数: {len(samples)}")
        assert len(samples) == 3, "应该有3个样本"
    
    print("✅ 测试1通过\n")


def test_speaker_confidence_top1():
    """测试：Top-1 说话人（主说话人，置信度=1.0）"""
    print("\n=== 测试2: Top-1 说话人置信度 ===")
    
    meeting_id = "test_meeting_volume_2"
    current_time = time.time()
    
    # 场景：User A 音量最大（1500）
    manager.add_audio_rms_sample(meeting_id, "user_a", 1500, current_time)
    manager.add_audio_rms_sample(meeting_id, "user_b", 800, current_time - 0.5)
    manager.add_audio_rms_sample(meeting_id, "user_c", 300, current_time - 1.0)
    
    # 查询 User A 的置信度
    confidence, is_top, rank, top_speakers = manager.get_speaker_confidence(
        meeting_id, "user_a", 1500, time_window=2.0
    )
    
    assert confidence == 1.0, f"Top-1 恐信度应为1.0，得到{confidence}"
    assert is_top == True, "Top-1 应标记为 is_top=True"
    assert rank == 1, f"排名应为1，得到{rank}"
    
    print(f"✓ User A 置信度: {confidence:.2f} ✅ (Top-1 主说话人)")
    print(f"✓ 排名: {rank}")
    top_speakers_str = [f"{s['username']}({int(s['avg_rms'])})" for s in top_speakers]
    print(f"✓ Top 3 说话人: {top_speakers_str}")
    
    print("✅ 测试2通过\n")


def test_speaker_confidence_top2():
    """测试：Top-2 说话人（次要说话人，置信度=0.8）"""
    print("\n=== 测试3: Top-2 说话人置信度 ===")
    
    meeting_id = "test_meeting_volume_3"
    current_time = time.time()
    
    # 场景：User B 音量次大（800）
    manager.add_audio_rms_sample(meeting_id, "user_a", 1500, current_time)
    manager.add_audio_rms_sample(meeting_id, "user_b", 800, current_time - 0.5)
    manager.add_audio_rms_sample(meeting_id, "user_c", 300, current_time - 1.0)
    
    # 查询 User B 的置信度
    confidence, is_top, rank, top_speakers = manager.get_speaker_confidence(
        meeting_id, "user_b", 800, time_window=2.0
    )
    
    assert confidence == 0.8, f"Top-2 置信度应为0.8，得到{confidence}"
    assert is_top == False, "Top-2 应标记为 is_top=False"
    assert rank == 2, f"排名应为2，得到{rank}"
    
    print(f"✓ User B 置信度: {confidence:.2f} ✅ (Top-2 次说话人)")
    print(f"✓ 排名: {rank}")
    
    print("✅ 测试3通过\n")


def test_speaker_confidence_low():
    """测试：低置信度说话人"""
    print("\n=== 测试4: 低置信度说话人 ===")
    
    meeting_id = "test_meeting_volume_4"
    current_time = time.time()
    
    # 场景：User C 音量很小（300）
    manager.add_audio_rms_sample(meeting_id, "user_a", 1500, current_time)
    manager.add_audio_rms_sample(meeting_id, "user_b", 800, current_time - 0.5)
    manager.add_audio_rms_sample(meeting_id, "user_c", 300, current_time - 1.0)
    
    # 查询 User C 的置信度
    confidence, is_top, rank, top_speakers = manager.get_speaker_confidence(
        meeting_id, "user_c", 300, time_window=2.0
    )
    
    assert 0.3 <= confidence <= 0.6, f"低置信度应在0.3~0.6，得到{confidence}"
    assert is_top == False, "低置信度应标记为 is_top=False"
    assert rank >= 3, f"排名应 >= 3，得到{rank}"
    
    print(f"✓ User C 置信度: {confidence:.2f} ⚠️  (低置信度)")
    print(f"✓ 排名: {rank}")
    print(f"✓ 相对能量: {confidence:.2f} (主说话人的 {confidence*100:.0f}%)")
    
    print("✅ 测试4通过\n")


def test_time_window_expiry():
    """测试：时间窗口过期机制"""
    print("\n=== 测试5: 时间窗口过期机制 ===")
    
    meeting_id = "test_meeting_volume_5"
    current_time = time.time()
    
    # 添加旧样本（3秒前）
    old_time = current_time - 3.0
    manager.add_audio_rms_sample(meeting_id, "user_a", 1500, old_time)
    
    # 添加新样本（0.5秒前）
    new_time = current_time - 0.5
    manager.add_audio_rms_sample(meeting_id, "user_b", 800, new_time)
    
    print(f"✓ 添加旧样本 (3秒前): user_a RMS=1500")
    print(f"✓ 添加新样本 (0.5秒前): user_b RMS=800")
    
    # 用 2.0 秒时间窗口查询 - 旧样本应被忽略
    confidence_b, _, rank_b, _ = manager.get_speaker_confidence(
        meeting_id, "user_b", 800, time_window=2.0
    )
    
    # 由于旧样本被忽略，User B 应成为唯一的样本
    assert confidence_b == 1.0, f"在2秒窗口内，User B 应为Top-1 (confidence=1.0)，得到{confidence_b}"
    assert rank_b == 1, f"排名应为1，得到{rank_b}"
    
    print(f"✓ User B 置信度: {confidence_b:.2f} (旧样本已过期)")
    print(f"✓ User B 排名: {rank_b} (成为唯一有效样本)")
    
    print("✅ 测试5通过\n")


def test_meeting_isolation():
    """测试：课堂隔离"""
    print("\n=== 测试6: 课堂隔离 ===")
    
    meeting_1 = "test_meeting_1"
    meeting_2 = "test_meeting_2"
    current_time = time.time()
    
    # 在课堂1添加样本
    manager.add_audio_rms_sample(meeting_1, "user_a", 1500, current_time)
    manager.add_audio_rms_sample(meeting_1, "user_b", 800, current_time)
    print(f"✓ 课堂1中：user_a RMS=1500, user_b RMS=800")
    
    # 在课堂2添加样本
    manager.add_audio_rms_sample(meeting_2, "user_x", 500, current_time)
    print(f"✓ 课堂2中：user_x RMS=500")
    
    # 查询课堂1中user_a的置信度 - 应基于课堂1的数据
    conf_a, _, rank_a, _ = manager.get_speaker_confidence(
        meeting_1, "user_a", 1500, time_window=2.0
    )
    assert conf_a == 1.0 and rank_a == 1, "课堂1中user_a应为Top-1"
    print(f"✓ 课堂1 user_a 位置: 排名{rank_a} 置信度{conf_a:.2f}")
    
    # 查询课堂2中user_x的置信度 - 应基于课堂2的数据
    conf_x, _, rank_x, _ = manager.get_speaker_confidence(
        meeting_2, "user_x", 500, time_window=2.0
    )
    assert conf_x == 1.0 and rank_x == 1, "课堂2中user_x应为唯一user"
    print(f"✓ 课堂2 user_x 位置: 排名{rank_x} 置信度{conf_x:.2f}")
    
    print("✅ 测试6通过\n")


def test_dynamic_ranking():
    """测试：动态排名更新"""
    print("\n=== 测试7: 动态排名更新 ===")
    
    meeting_id = "test_meeting_volume_6"
    current_time = time.time()
    
    # 初始状态：User A 最大（1500）
    manager.add_audio_rms_sample(meeting_id, "user_a", 1500, current_time - 1.5)
    manager.add_audio_rms_sample(meeting_id, "user_b", 800, current_time - 1.0)
    
    conf_a, _, rank_a, _ = manager.get_speaker_confidence(
        meeting_id, "user_a", 1500, time_window=2.0
    )
    assert rank_a == 1, "初始: User A 应为Top-1"
    print(f"✓ 初始: User A 排名{rank_a} 置信度{conf_a:.2f}")
    
    # 新增样本：User B 大幅增加（加入新的较大音量）
    # 此时 User B 会有多个样本，但最新的样本更大
    manager.add_audio_rms_sample(meeting_id, "user_b", 2000, current_time - 0.5)
    
    conf_b, _, rank_b, _ = manager.get_speaker_confidence(
        meeting_id, "user_b", 2000, time_window=2.0
    )
    # User B 的平均 RMS 会是 (800 + 2000) / 2 = 1400，仍小于 1500
    # 所以我们调整一下，给 User B 两个都很大的值
    print(f"✓ 更新: User B 排名{rank_b} 置信度{conf_b:.2f}")
    
    # 用平均值更高的新样本再试一次
    manager.add_audio_rms_sample(meeting_id, "user_b", 2200, current_time - 0.2)
    
    conf_b2, _, rank_b2, _ = manager.get_speaker_confidence(
        meeting_id, "user_b", 2200, time_window=2.0
    )
    # 现在 User B 有 3 个样本：800, 2000, 2200，平均 = 1666.7
    # 这大于 User A 的 1500
    assert rank_b2 == 1, f"更新后: User B 应变成Top-1，但排名是{rank_b2}"
    print(f"✓ 再次更新: User B 排名{rank_b2} 置信度{conf_b2:.2f}")
    
    # User A 的排名应下降
    conf_a_new, _, rank_a_new, _ = manager.get_speaker_confidence(
        meeting_id, "user_a", 1500, time_window=2.0
    )
    assert rank_a_new == 2, f"更新后: User A 应变成Top-2，但排名是{rank_a_new}"
    print(f"✓ 更新: User A 排名{rank_a_new} 置信度{conf_a_new:.2f}")
    
    print("✅ 测试7通过\n")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("   音量仲裁 (Speaker Volume Arbitration) 单元测试")
    print("="*60)
    
    try:
        test_add_rms_samples()
        test_speaker_confidence_top1()
        test_speaker_confidence_top2()
        test_speaker_confidence_low()
        test_time_window_expiry()
        test_meeting_isolation()
        test_dynamic_ranking()
        
        print("\n" + "="*60)
        print("   ✅ 所有测试通过！")
        print("="*60 + "\n")
        return True
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}\n")
        return False
    except Exception as e:
        print(f"\n❌ 异常: {e}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
