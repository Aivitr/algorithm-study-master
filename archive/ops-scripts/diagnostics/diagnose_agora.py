#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agora 配置诊断脚本

用于排查 Agora Token 生成问题的根本原因
"""
import sys
import os

def check_agora_library():
    """检查 agora-token-builder 库"""
    print("=" * 70)
    print("1️⃣  检查 Agora 库安装")
    print("=" * 70)
    
    try:
        import agora_token_builder
        print("✅ agora-token-builder 库已安装")
        print(f"   位置: {agora_token_builder.__file__}")
        return True
    except ImportError as e:
        print(f"❌ agora-token-builder 库未安装")
        print(f"   错误: {e}")
        print()
        print("💡 修复方案:")
        print("   pip install agora-token-builder")
        return False


def check_agora_credentials():
    """检查 Agora 凭证"""
    print()
    print("=" * 70)
    print("2️⃣  检查 Agora 凭证")
    print("=" * 70)
    
    # 从 server.py 读取凭证
    try:
        from server import AGORA_APP_ID, AGORA_APP_CERTIFICATE
        
        print(f"APP_ID:        {AGORA_APP_ID if AGORA_APP_ID else '❌ 未设置'}")
        print(f"APP_CERT:      {AGORA_APP_CERTIFICATE[:16] + '...' if AGORA_APP_CERTIFICATE else '❌ 未设置'}")
        
        if AGORA_APP_ID and AGORA_APP_CERTIFICATE:
            print("✅ 凭证已配置")
            return True
        else:
            print("❌ 凭证未配置或不完整")
            print()
            print("💡 修复方案:")
            print("   1. 从 https://console.agora.io 获取你的:")
            print("      - APP_ID (应用 ID)")
            print("      - APP_CERTIFICATE (应用证书)")
            print()
            print("   2. 更新 server.py 中的:")
            print("      AGORA_APP_ID = '你的APP_ID'")
            print("      AGORA_APP_CERTIFICATE = '你的APP_CERT'")
            return False
    except Exception as e:
        print(f"❌ 无法读取凭证: {e}")
        return False


def test_agora_token_generation():
    """测试 Token 生成"""
    print()
    print("=" * 70)
    print("3️⃣  测试 Token 生成")
    print("=" * 70)
    
    try:
        from agora_token_builder import RtcTokenBuilder
        from server import AGORA_APP_ID, AGORA_APP_CERTIFICATE
        import time
        
        if not AGORA_APP_ID or not AGORA_APP_CERTIFICATE:
            print("❌ 凭证缺失，跳过测试")
            return False
        
        # 测试参数
        test_channel = "test-channel"
        test_uid = "12345"
        expire_seconds = 86400
        current_ts = int(time.time())
        privilege_expired_ts = current_ts + expire_seconds
        
        print(f"测试参数:")
        print(f"  Channel: {test_channel}")
        print(f"  UID:     {test_uid}")
        print(f"  有效期:  {expire_seconds}s")
        print()
        
        # 生成 Token
        token = RtcTokenBuilder.buildTokenWithAccount(
            AGORA_APP_ID, AGORA_APP_CERTIFICATE,
            test_channel, test_uid, 1, privilege_expired_ts
        )
        
        print(f"✅ Token 生成成功!")
        print(f"   Token: {token[:50]}...")
        print(f"   长度:  {len(token)} 字节")
        return True
        
    except Exception as e:
        print(f"❌ Token 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_favicon():
    """检查 favicon 问题"""
    print()
    print("=" * 70)
    print("4️⃣  检查 favicon 问题")
    print("=" * 70)
    
    import os
    favicon_path = "static/favicon.ico"
    
    if os.path.exists(favicon_path):
        print(f"✅ favicon 文件存在: {favicon_path}")
        size = os.path.getsize(favicon_path)
        print(f"   大小: {size} 字节")
        return True
    else:
        print(f"❌ favicon 文件缺失: {favicon_path}")
        print()
        print("💡 修复方案:")
        print("   1. 创建 static/ 目录:")
        print("      mkdir -p static")
        print()
        print("   2. 添加一个 favicon.ico 文件（可以是任何有效的 ICO 文件）")
        print()
        print("   3. 或在 server.py 中禁用 favicon 让浏览器不加载")
        return False


def generate_summary():
    """生成诊断总结"""
    print()
    print("=" * 70)
    print("📊 诊断总结")
    print("=" * 70)
    print()
    
    results = []
    
    # 逐项检查
    print("执行检查...")
    results.append(("Agora 库", check_agora_library()))
    results.append(("凭证配置", check_agora_credentials()))
    results.append(("Token 生成", test_agora_token_generation()))
    results.append(("Favicon", check_favicon()))
    
    print()
    print("=" * 70)
    print("结果:")
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status} {name}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print()
        print("✅ 所有检查都通过！")
        print("   Agora 集成应该能正常工作")
    else:
        print()
        print("❌ 有些检查失败，请根据上述建议修复")
    
    return all_passed


def main():
    """主函数"""
    print()
    print("🔍 Agora 配置诊断工具")
    print(f"   时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    success = generate_summary()
    
    print()
    print("=" * 70)
    print("📚 常见问题 & 解决方案")
    print("=" * 70)
    print()
    print("Q1: Agora Token 端点返回 500 错误")
    print("A:  查看上面的诊断结果，按照建议进行修复")
    print()
    print("Q2: 如何获取 Agora 凭证？")
    print("A:  1. 访问 https://console.agora.io")
    print("    2. 注册和登录账户")
    print("    3. 创建应用获取 APP_ID")
    print("    4. 生成临时 Token 或获取 APP_CERTIFICATE")
    print()
    print("Q3: Token 生成后如何在音视频通话中使用？")
    print("A:  使用生成的 token 加入 Agora 频道:")
    print("    fetch('/api/agora-token?channel=room1&uid=user123')")
    print("      .then(res => res.json())")
    print("      .then(data => {")
    print("        // data.token 即为生成的 Token")
    print("        // 使用 Agora SDK 加入频道")
    print("      })")
    print()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
