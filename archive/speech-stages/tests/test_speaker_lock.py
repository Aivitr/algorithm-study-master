#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
发言席位锁 (Speaker Lock) 单元测试

验证内容：
1. 单用户获取和释放锁
2. 多用户竞争锁 
3. 锁超时自动释放
4. 并发安全性
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import manager


def test_single_user_lock():
    """测试：单用户获取和释放锁"""
    print("\n=== 测试1: 单用户获取和释放锁 ===")
    meeting_id = "test_meeting_1"
    username = "user_a"
    
    # 首次尝试获取锁 - 应该成功
    success, lock_holder = manager.try_acquire_speaker_lock(meeting_id, username)
    assert success == True, f"第一次获取锁应该成功，但失败了"
    print(f"✓ {username} 成功获取锁")
    
    # 再次尝试获取锁 - 应该失败（已被自己持有）
    success2, lock_holder2 = manager.try_acquire_speaker_lock(meeting_id, username)
    assert success2 == False, f"重复获取锁应该失败（已持有）"
    assert lock_holder2 == username, f"锁持有者应该是{username}"
    print(f"✓ {username} 重复获取锁失败（已持有）")
    
    # 释放锁
    manager.release_speaker_lock(meeting_id, username)
    print(f"✓ {username} 释放锁")
    
    # 再次尝试获取锁 - 应该成功（锁已释放）
    success3, lock_holder3 = manager.try_acquire_speaker_lock(meeting_id, username)
    assert success3 == True, f"释放后再次获取应该成功"
    print(f"✓ {username} 再次成功获取锁")
    
    manager.release_speaker_lock(meeting_id, username)
    print("✅ 测试1通过\n")


def test_multi_user_contention():
    """测试：多用户竞争锁"""
    print("\n=== 测试2: 多用户竞争锁 ===")
    meeting_id = "test_meeting_2"
    user_a = "user_a"
    user_b = "user_b"
    user_c = "user_c"
    
    # User A 获取锁
    success_a, _ = manager.try_acquire_speaker_lock(meeting_id, user_a)
    assert success_a == True, "User A 应该成功获取锁"
    print(f"✓ {user_a} 获取锁")
    
    # User B 尝试获取锁 - 应该失败
    success_b, holder_b = manager.try_acquire_speaker_lock(meeting_id, user_b)
    assert success_b == False, "User B 应该获取锁失败（A已持有）"
    assert holder_b == user_a, f"锁持有者应该是{user_a}，但是{holder_b}"
    print(f"✓ {user_b} 获取锁失败（{user_a}已持有）")
    
    # User C 尝试获取锁 - 应该也失败
    success_c, holder_c = manager.try_acquire_speaker_lock(meeting_id, user_c)
    assert success_c == False, "User C 应该获取锁失败（A已持有）"
    assert holder_c == user_a
    print(f"✓ {user_c} 获取锁失败（{user_a}已持有）")
    
    # User A 释放锁
    manager.release_speaker_lock(meeting_id, user_a)
    print(f"✓ {user_a} 释放锁")
    
    # User B 尝试获取锁 - 应该成功（A已释放）
    success_b2, _ = manager.try_acquire_speaker_lock(meeting_id, user_b)
    assert success_b2 == True, "User B 应该成功获取锁（A已释放）"
    print(f"✓ {user_b} 成功获取锁")
    
    manager.release_speaker_lock(meeting_id, user_b)
    print("✅ 测试2通过\n")


def test_lock_timeout():
    """测试：锁超时自动释放"""
    print("\n=== 测试3: 锁超时自动释放 ===")
    meeting_id = "test_meeting_3"
    user_a = "user_a"
    user_b = "user_b"
    timeout_sec = 0.5  # 短超时用于快速测试
    
    # User A 获取锁
    success_a, _ = manager.try_acquire_speaker_lock(meeting_id, user_a, timeout_sec=timeout_sec)
    assert success_a == True
    print(f"✓ {user_a} 获取锁")
    
    # User B 立即尝试获取 - 应该失败
    success_b, holder = manager.try_acquire_speaker_lock(meeting_id, user_b, timeout_sec=timeout_sec)
    assert success_b == False and holder == user_a
    print(f"✓ {user_b} 获取锁失败（{user_a}已持有）")
    
    # 等待锁超时
    print(f"⏱️  等待{timeout_sec}秒，等锁超时...")
    time.sleep(timeout_sec + 0.1)
    
    # 此时 User B 尝试获取 - 应该成功（因为User A的锁已超时被自动释放）
    success_b2, holder2 = manager.try_acquire_speaker_lock(meeting_id, user_b, timeout_sec=timeout_sec)
    assert success_b2 == True, "User B 应该通过超时机制成功获取锁"
    print(f"✓ {user_b} 通过超时机制成功获取锁")
    
    manager.release_speaker_lock(meeting_id, user_b)
    print("✅ 测试3通过\n")


def test_get_current_speaker():
    """测试：获取当前发言人"""
    print("\n=== 测试4: 获取当前发言人 ===")
    meeting_id = "test_meeting_4"
    user_a = "user_a"
    
    # 初始状态 - 无发言人
    current = manager.get_current_speaker_lock(meeting_id)
    assert current is None, "初始状态应该无发言人"
    print(f"✓ 初始状态：无发言人")
    
    # User A 获取锁
    manager.try_acquire_speaker_lock(meeting_id, user_a)
    current = manager.get_current_speaker_lock(meeting_id)
    assert current == user_a, f"发言人应该是{user_a}"
    print(f"✓ {user_a} 获取锁后，当前发言人={current}")
    
    # 释放锁
    manager.release_speaker_lock(meeting_id, user_a)
    current = manager.get_current_speaker_lock(meeting_id)
    assert current is None, "释放后应该无发言人"
    print(f"✓ 释放锁后：无发言人")
    
    print("✅ 测试4通过\n")


def test_cross_meeting_isolation():
    """测试：不同课堂的锁隔离"""
    print("\n=== 测试5: 不同课堂的锁隔离 ===")
    meeting_1 = "meeting_1"
    meeting_2 = "meeting_2"
    user = "user_a"
    
    # 在课堂1获取锁
    success_1, _ = manager.try_acquire_speaker_lock(meeting_1, user)
    assert success_1 == True
    print(f"✓ {user} 在课堂1获取锁")
    
    # 在课堂2也应该能获取锁（不同课堂的锁是隔离的）
    success_2, _ = manager.try_acquire_speaker_lock(meeting_2, user)
    assert success_2 == True, "不同课堂的锁应该隔离"
    print(f"✓ {user} 在课堂2也能获取锁（隔离的）")
    
    # 同一课堂只有一个锁持有者
    user_b = "user_b"
    success_b, holder = manager.try_acquire_speaker_lock(meeting_1, user_b)
    assert success_b == False and holder == user, f"课堂1已有锁持有者{user}"
    print(f"✓ 课堂1中{user}持有锁，{user_b}无法获取")
    
    manager.release_speaker_lock(meeting_1, user)
    manager.release_speaker_lock(meeting_2, user)
    print("✅ 测试5通过\n")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("   发言席位锁 (Speaker Lock) 单元测试")
    print("="*60)
    
    try:
        test_single_user_lock()
        test_multi_user_contention()
        test_lock_timeout()
        test_get_current_speaker()
        test_cross_meeting_isolation()
        
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
