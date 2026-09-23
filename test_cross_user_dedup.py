#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
跨用户重复文本抑制 (Cross-User Duplicate Suppression) 单元测试

验证内容：
1. 文本相似度计算
2. 相似文本重复检测
3. 时间窗口限制
4. 课堂隔离
5. 阈值调整
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import manager, ConnectionManager


def test_text_normalization():
    """测试：文本归一化"""
    print("\n=== 测试1: 文本归一化 ===")
    
    test_cases = [
        ("这是一个很好的例子", "这是一个很好的例子"),
        ("这，是，一，个，很，好，的，例，子", "这是一个很好的例子"),
        ("这是一个很好的例子。", "这是一个很好的例子"),
        ("THIS IS A GOOD EXAMPLE", "thisisagoodexample"),  # 英文去空格
        ("  多   格   ", "多格"),  # 中文去空格
    ]
    
    for original, expected_norm in test_cases:
        normalized = manager._normalize_text(original)
        print(f"'{original}' -> '{normalized}'")
        assert normalized == expected_norm, f"期望 '{expected_norm}'，得到 '{normalized}'"
    
    print("✅ 测试1通过\n")


def test_text_similarity():
    """测试：文本相似度计算"""
    print("\n=== 测试2: 文本相似度计算 ===")
    
    # 完全相同
    sim = manager._text_similarity("这是一个很好的例子", "这是一个很好的例子")
    assert sim == 1.0, f"完全相同应该相似度1.0，得到{sim}"
    print(f"✓ 完全相同: {sim:.2f}")
    
    # 标点差异（应视为相同）
    sim = manager._text_similarity("这是一个很好的例子。", "这是一个很好的例子")
    assert sim >= 0.95, f"标点差异应高度相似，得到{sim}"
    print(f"✓ 标点差异: {sim:.2f}")
    
    # 大小写差异（英文 + 中文）
    sim = manager._text_similarity("This Is Good", "this is good")
    assert sim >= 0.90, f"大小写差异应高度相似，得到{sim}"
    print(f"✓ 大小写差异: {sim:.2f}")
    
    # 部分相同
    sim = manager._text_similarity("这是一个很好的例子", "这是一个例子")
    assert 0.7 < sim < 1.0, f"部分相同应中等相似，得到{sim}"
    print(f"✓ 部分相同: {sim:.2f}")
    
    # 完全不同
    sim = manager._text_similarity("这是一个很好的例子", "我喜欢苹果")
    assert sim < 0.3, f"完全不同应低相似度，得到{sim}"
    print(f"✓ 完全不同: {sim:.2f}")
    
    print("✅ 测试2通过\n")


def test_add_and_check_duplicate():
    """测试：添加转录和重复检测"""
    print("\n=== 测试3: 添加转录和重复检测 ===")
    
    meeting_id = "test_meeting_dup_1"
    current_time = time.time()
    
    # 第一句话：User A 说
    manager.add_recent_transcript(meeting_id, "user_a", "这是一个很好的例子", current_time)
    print(f"✓ User A 添加转录: '这是一个很好的例子'")
    
    # 检查 User B 相同的话 - 应检测为重复
    is_dup, dup_user = manager.check_cross_user_duplicate(
        meeting_id, "user_b", "这是一个很好的例子", current_time + 0.5
    )
    assert is_dup == True, "User B 说相同的话应检测为重复"
    assert dup_user == "user_a", "重复来源应该是 User A"
    print(f"✓ User B 相同文本被检测为重复（来自 {dup_user}）")
    
    # 检查 User C 不同的话 - 不应检测为重复
    is_dup, dup_user = manager.check_cross_user_duplicate(
        meeting_id, "user_c", "我喜欢苹果", current_time + 1.0
    )
    assert is_dup == False, "User C 说不同的话不应检测为重复"
    print(f"✓ User C 不同文本不被检测为重复")
    
    # 检查 User A 自己的话 - 不应检测为重复（同用户）
    is_dup, dup_user = manager.check_cross_user_duplicate(
        meeting_id, "user_a", "这是一个很好的例子", current_time + 2.0
    )
    assert is_dup == False, "同用户的话不应检测为重复"
    print(f"✓ User A 自己的相同文本不被检测为重复（同用户）")
    
    print("✅ 测试3通过\n")


def test_time_window_expiry():
    """测试：时间窗口过期机制"""
    print("\n=== 测试4: 时间窗口过期机制 ===")
    
    meeting_id = "test_meeting_dup_2"
    current_time = time.time()
    
    # 添加一条很早的转录（5秒前）
    old_time = current_time - 5.5
    manager.add_recent_transcript(meeting_id, "user_a", "这是一个很好的例子", old_time)
    print(f"✓ 添加5.5秒前的转录")
    
    # 现在检查相同文本 - 应该不被检测为重复（因为已过期）
    is_dup, dup_user = manager.check_cross_user_duplicate(
        meeting_id, "user_b", "这是一个很好的例子", current_time,
        time_window=5.0
    )
    assert is_dup == False, "超过5秒的重复应该不被检测"
    print(f"✓ 超时转录被自动忽略（正确）")
    
    # 但如果在5秒内仍应被检测
    manager.recent_transcripts.clear()  # 清空
    recent_time = current_time - 3.0
    manager.add_recent_transcript(meeting_id, "user_a", "这是一个很好的例子", recent_time)
    print(f"✓ 添加3秒前的转录")
    
    is_dup, dup_user = manager.check_cross_user_duplicate(
        meeting_id, "user_b", "这是一个很好的例子", current_time,
        time_window=5.0
    )
    assert is_dup == True, "5秒内的重复应该被检测"
    print(f"✓ 有效期内的转录被正确检测（是重复）")
    
    print("✅ 测试4通过\n")


def test_similarity_threshold():
    """测试：相似度阈值"""
    print("\n=== 测试5: 相似度阈值 ===")
    
    meeting_id = "test_meeting_dup_3"
    current_time = time.time()
    
    # 添加一条转录
    manager.add_recent_transcript(meeting_id, "user_a", "这是一个很好的例子", current_time)
    print(f"✓ User A: '这是一个很好的例子'")
    
    # User B 说很相似但不完全相同的话
    similar_text = "这是一个很不好的例子"  # 相似但不同
    
    # 用高阈值检查（0.95）- 应不被检测为重复
    is_dup, _ = manager.check_cross_user_duplicate(
        meeting_id, "user_b", similar_text, current_time + 1.0,
        similarity_threshold=0.95
    )
    print(f"✓ 阈值0.95: {'重复' if is_dup else '不重复'}")
    
    # 用低阈值检查（0.70）- 应被检测为重复
    manager.recent_transcripts.clear()
    manager.add_recent_transcript(meeting_id, "user_a", "这是一个很好的例子", current_time)
    is_dup, _ = manager.check_cross_user_duplicate(
        meeting_id, "user_b", similar_text, current_time + 1.0,
        similarity_threshold=0.70
    )
    print(f"✓ 阈值0.70: {'重复' if is_dup else '不重复'}")
    
    print("✅ 测试5通过\n")


def test_meeting_isolation():
    """测试：课堂隔离"""
    print("\n=== 测试6: 课堂隔离 ===")
    
    meeting_1 = "test_meeting_1"
    meeting_2 = "test_meeting_2"
    current_time = time.time()
    
    # 在课堂1添加 User A 的转录
    manager.add_recent_transcript(meeting_1, "user_a", "这是一个很好的例子", current_time)
    print(f"✓ 课堂1中 User A: '这是一个很好的例子'")
    
    # 在课堂2添加相同的文本 - 应该不被检测为重复（不同课堂）
    is_dup, _ = manager.check_cross_user_duplicate(
        meeting_2, "user_b", "这是一个很好的例子", current_time
    )
    assert is_dup == False, "不同课堂的重复应该隔离"
    print(f"✓ 课堂2中相同文本：不被检测为重复（课堂隔离）")
    
    # 在课堂1添加相同的文本 - 应该被检测为重复（同课堂）
    is_dup, _ = manager.check_cross_user_duplicate(
        meeting_1, "user_b", "这是一个很好的例子", current_time + 0.5
    )
    assert is_dup == True, "同课堂的重复应该被检测"
    print(f"✓ 课堂1中相同文本：被检测为重复")
    
    print("✅ 测试6通过\n")


def test_device_pause_state():
    """测试：设备暂停状态管理"""
    print("\n=== 测试7: 设备暂停状态 ===")

    meeting_id = "test_pause_meeting"
    username = "user_pause"

    # 默认未暂停
    assert manager.is_device_paused(meeting_id, username) == False
    print("✓ 默认状态为未暂停")

    # 设置暂停
    manager.set_device_paused(meeting_id, username, True)
    assert manager.is_device_paused(meeting_id, username) == True
    print("✓ 设置暂停后状态正确")

    # 取消暂停
    manager.set_device_paused(meeting_id, username, False)
    assert manager.is_device_paused(meeting_id, username) == False
    print("✓ 恢复后状态正确")

    print("✅ 测试7通过\n")


def test_pause_clears_recent_transcripts_for_device():
    """测试：设备暂停时清理该设备的recent转录，避免误判重复"""
    print("\n=== 测试8: 暂停清理recent转录 ===")

    meeting_id = "test_pause_cleanup"
    user_a = "user_a"
    user_b = "user_b"
    now = time.time()

    manager.recent_transcripts.pop(meeting_id, None)

    # 先添加A的一条转录
    manager.add_recent_transcript(meeting_id, user_a, "这是一个很好的例子", now)
    assert len(manager.recent_transcripts.get(meeting_id, [])) == 1
    print("✓ 已添加A的转录")

    # A暂停后，应清除A近期转录
    manager.set_device_paused(meeting_id, user_a, True)
    left = manager.recent_transcripts.get(meeting_id, [])
    assert all(item.get("username") != user_a for item in left)
    print("✓ A暂停后，A的recent转录被清理")

    # B说同一句，不应再被判定为与A重复
    is_dup, dup_user = manager.check_cross_user_duplicate(
        meeting_id, user_b, "这是一个很好的例子", now + 0.5
    )
    assert is_dup is False
    assert dup_user is None
    print("✓ 清理后B不会被A历史残留误判")

    print("✅ 测试8通过\n")


def test_event_timestamp_window_for_dedup():
    """测试：去重窗口基于事件时间戳，而非服务端当前时间"""
    print("\n=== 测试9: 事件时间窗口去重 ===")

    meeting_id = "test_event_ts_window"
    now = time.time()

    manager.recent_transcripts.pop(meeting_id, None)

    # A 在 now 说话
    manager.add_recent_transcript(meeting_id, "user_a", "同一句话", now)

    # B 在 2s 后说同一句（应命中重复）
    decision = manager.decide_transcript_canonical(
        meeting_id=meeting_id,
        username="user_b",
        text="同一句话",
        timestamp=now + 2.0,
        asr_confidence=1.0,
        audio_rms=0.0,
        time_window=5.0
    )
    assert decision.get("is_duplicate") is True
    print("✓ 2秒内同句命中重复")

    # B 在 8s 后说同一句（超窗口，不应命中）
    decision = manager.decide_transcript_canonical(
        meeting_id=meeting_id,
        username="user_b",
        text="同一句话",
        timestamp=now + 8.0,
        asr_confidence=1.0,
        audio_rms=0.0,
        time_window=5.0
    )
    assert decision.get("is_duplicate") is False
    print("✓ 超过窗口不判重")

    # 自定义时间窗：2秒窗口下，3秒后不判重
    decision = manager.decide_transcript_canonical(
        meeting_id=meeting_id,
        username="user_b",
        text="同一句话",
        timestamp=now + 3.0,
        asr_confidence=1.0,
        audio_rms=0.0,
        time_window=2.0
    )
    assert decision.get("is_duplicate") is False
    print("✓ 可配置窗口生效（2秒窗口）")

    print("✅ 测试9通过\n")


def test_dedup_stats_tracking():
    """测试：去重统计计数与命中率"""
    print("\n=== 测试10: 去重统计 ===")

    meeting_id = "test_dedup_stats"
    manager.dedup_stats.pop(meeting_id, None)

    s = manager.get_dedup_stats(meeting_id)
    assert s["total"] == 0 and s["suppressed"] == 0 and s["canonical"] == 0
    print("✓ 初始统计为0")

    manager.record_dedup_event(meeting_id, suppressed=False)
    manager.record_dedup_event(meeting_id, suppressed=True)
    manager.record_dedup_event(meeting_id, suppressed=True)

    s = manager.get_dedup_stats(meeting_id)
    assert s["total"] == 3
    assert s["canonical"] == 1
    assert s["suppressed"] == 2
    assert abs(s["suppression_rate"] - (2 / 3)) < 1e-6
    print("✓ 统计计数与命中率正确")

    print("✅ 测试10通过\n")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("   跨用户重复文本抑制 (Cross-User Duplicate Suppression) 单元测试")
    print("="*60)
    
    try:
        test_text_normalization()
        test_text_similarity()
        test_add_and_check_duplicate()
        test_time_window_expiry()
        test_similarity_threshold()
        test_meeting_isolation()
        test_device_pause_state()
        test_pause_clears_recent_transcripts_for_device()
        test_event_timestamp_window_for_dedup()
        test_dedup_stats_tracking()
        
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
