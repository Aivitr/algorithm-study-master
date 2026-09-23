#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stage 4 Audio Constraint Verification Script
阶段4：音频约束前端测试验证脚本

Purpose: 生成音频约束应用情况的验证报告
"""

import json
import re
from pathlib import Path
from datetime import datetime


def analyze_audio_constraints():
    """分析 index.html 中的音频约束应用"""
    
    html_path = Path(__file__).parent / "index.html"
    
    if not html_path.exists():
        return {
            "status": "error",
            "message": "index.html not found"
        }
    
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查 getUserMedia 调用
    results = {
        "timestamp": datetime.now().isoformat(),
        "file": str(html_path),
        "getUserMedia_calls": [],
        "getDisplayMedia_calls": [],
        "audio_constraint_found": False,
        "toast_notification_found": False,
        "expected_constraints": {
            "echoCancellation": True,
            "noiseSuppression": True,
            "autoGainControl": True,
            "channelCount": 1,
            "sampleRate": 16000
        }
    }
    
    # 查找获取媒体的调用
    getUserMedia_pattern = r"navigator\.mediaDevices\.getUserMedia\s*\(\s*\{([^}]+)\}\s*\)"
    getDisplayMedia_pattern = r"navigator\.mediaDevices\.getDisplayMedia\s*\(\s*\{([^}]+)\}\s*\)"
    
    for match in re.finditer(getUserMedia_pattern, content):
        params = match.group(1)
        results["getUserMedia_calls"].append({
            "line": content[:match.start()].count('\n') + 1,
            "params": params.strip(),
            "has_audio_constraints": "echoCancellation" in params or "noiseSuppression" in params
        })
    
    for match in re.finditer(getDisplayMedia_pattern, content):
        params = match.group(1)
        results["getDisplayMedia_calls"].append({
            "line": content[:match.start()].count('\n') + 1,
            "params": params.strip(),
            "has_audio_constraints": "echoCancellation" in params or "noiseSuppression" in params
        })
    
    # 检查音频约束定义
    if "echoCancellation" in content and "noiseSuppression" in content:
        results["audio_constraint_found"] = True
    
    # 检查吐司通知
    toast_patterns = [
        r"showToast.*音频处理",
        r"🎤.*音频处理",
        r"📢.*耳机",
    ]
    for pattern in toast_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            results["toast_notification_found"] = True
            break
    
    # 验证所有约束都存在
    constraint_patterns = {
        "echoCancellation": "echoCancellation\\s*:\\s*true",
        "noiseSuppression": "noiseSuppression\\s*:\\s*true",
        "autoGainControl": "autoGainControl\\s*:\\s*true",
        "channelCount": "channelCount\\s*:\\s*1",
        "sampleRate": "16000|16\\s*kHz"
    }
    
    results["constraint_verification"] = {}
    for constraint, pattern in constraint_patterns.items():
        results["constraint_verification"][constraint] = bool(re.search(pattern, content))
    
    # 计算总体状态
    all_constraints_found = all(results["constraint_verification"].values())
    all_calls_updated = all(call["has_audio_constraints"] for call in results["getUserMedia_calls"]) and \
                       all(call["has_audio_constraints"] for call in results["getDisplayMedia_calls"])
    
    results["summary"] = {
        "total_getUserMedia_calls": len(results["getUserMedia_calls"]),
        "updated_getUserMedia_calls": sum(1 for call in results["getUserMedia_calls"] if call["has_audio_constraints"]),
        "total_getDisplayMedia_calls": len(results["getDisplayMedia_calls"]),
        "updated_getDisplayMedia_calls": sum(1 for call in results["getDisplayMedia_calls"] if call["has_audio_constraints"]),
        "all_constraints_found": all_constraints_found,
        "all_calls_updated": all_calls_updated,
        "toast_notification_found": results["toast_notification_found"],
        "implementation_status": "✅ 完全实现" if all_constraints_found and all_calls_updated and results["toast_notification_found"] else "⚠️ 部分实现"
    }
    
    return results


def generate_report():
    """生成验证报告"""
    
    print("\n" + "="*80)
    print("🎤 Stage 4 - 前端音频约束验证报告")
    print("="*80 + "\n")
    
    analysis = analyze_audio_constraints()
    
    if "error" in analysis:
        print(f"❌ 错误: {analysis['message']}")
        return
    
    summary = analysis["summary"]
    
    print(f"📋 验证时间: {analysis['timestamp']}")
    print(f"📄 分析文件: {analysis['file']}\n")
    
    # 约束验证
    print("✅ 音频约束参数验证:")
    for constraint, found in analysis["constraint_verification"].items():
        status = "✅" if found else "❌"
        print(f"  {status} {constraint:20} {'已应用' if found else '未找到'}")
    
    print(f"\n📊 媒体获取调用统计:")
    print(f"  getUserMedia 调用:  {summary['total_getUserMedia_calls']} 个")
    print(f"    - 已更新:         {summary['updated_getUserMedia_calls']} 个")
    print(f"  getDisplayMedia 调用: {summary['total_getDisplayMedia_calls']} 个")
    print(f"    - 已更新:         {summary['updated_getDisplayMedia_calls']} 个")
    
    print(f"\n🎯 功能检查:")
    print(f"  {'✅' if summary['all_constraints_found'] else '❌'} 所有约束参数都已定义")
    print(f"  {'✅' if summary['all_calls_updated'] else '❌'} 所有媒体获取调用都已更新")
    print(f"  {'✅' if summary['toast_notification_found'] else '❌'} 用户通知已添加")
    
    print(f"\n🔍 详细信息:")
    print(f"  getUserMedia 调用详情:")
    for i, call in enumerate(analysis["getUserMedia_calls"], 1):
        status = "✅" if call["has_audio_constraints"] else "❌"
        print(f"    {status} 第 {call['line']} 行: {call['params'][:50]}...")
    
    if analysis["getDisplayMedia_calls"]:
        print(f"  getDisplayMedia 调用详情:")
        for i, call in enumerate(analysis["getDisplayMedia_calls"], 1):
            status = "✅" if call["has_audio_constraints"] else "❌"
            print(f"    {status} 第 {call['line']} 行: {call['params'][:50]}...")
    
    print(f"\n📈 整体状态: {summary['implementation_status']}\n")
    
    # 测试建议
    print("🧪 建议的测试步骤:\n")
    print("  1. 打开 audio_constraint_test.html 进行实捷测试")
    print("  2. 点击 '✅ 测试（带约束）' 按钮")
    print("  3. 打开浏览器开发者工具 (F12) > Console")
    print("  4. 检查日志中的以下信息:")
    print("     - [LOCK] 日志（阶段1：发言人锁）")
    print("     - [DUP] 日志（阶段2：重复文本抑制）")
    print("     - [VOLUME] 日志（阶段3：音量仲裁）")
    print("     - [阶段4] 日志（阶段4：前端约束）")
    print("  5. 在网络标签页 (Network) 观察 WebSocket 消息中的:")
    print("     - audio_rms (音频RMS采样)")
    print("     - speaker_confidence (说话人置信度)")
    print("     - speaker_rank (说话人排名)")
    print("  6. 对比 '✅ 测试（带约束）' vs '❌ 对比（无约束）' 的音量表现")
    print("     - 带约束应该有更稳定的平均音量（50-70%范围）")
    print("     - 无约束可能会有较大波动和更多噪音尖峰\n")
    
    print("="*80 + "\n")


def generate_json_report():
    """生成JSON格式的报告"""
    
    analysis = analyze_audio_constraints()
    report_path = Path(__file__).parent / "STAGE4_VERIFICATION_REPORT.json"
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    
    print(f"✅ JSON报告已生成: {report_path}")
    return report_path


if __name__ == "__main__":
    generate_report()
    generate_json_report()
