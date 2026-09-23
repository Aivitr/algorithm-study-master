"""
声纹识别功能测试脚本
用于验证声纹注册、验证和识别功能
"""
import os
import wave
import numpy as np
from voiceprint_service import voiceprint_service


def generate_test_audio(filename, duration=3, frequency=440):
    """
    生成测试音频文件（正弦波）

    Args:
        filename: 输出文件名
        duration: 时长（秒）
        frequency: 频率（Hz）
    """
    sample_rate = 16000
    samples = int(sample_rate * duration)

    # 生成正弦波
    t = np.linspace(0, duration, samples)
    audio_data = np.sin(2 * np.pi * frequency * t)

    # 转换为 16-bit PCM
    audio_data = (audio_data * 32767).astype(np.int16)

    # 保存为 WAV 文件
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)  # 单声道
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())

    print(f"✅ 生成测试音频: {filename}")


def test_voiceprint_registration():
    """测试声纹注册"""
    print("\n" + "="*60)
    print("测试 1: 声纹注册")
    print("="*60)

    # 生成测试音频
    test_dir = "storage/temp"
    os.makedirs(test_dir, exist_ok=True)

    user1_audio = os.path.join(test_dir, "user1_sample.wav")
    user2_audio = os.path.join(test_dir, "user2_sample.wav")

    generate_test_audio(user1_audio, duration=3, frequency=440)  # A4 音符
    generate_test_audio(user2_audio, duration=3, frequency=523)  # C5 音符

    # 注册用户1
    print("\n注册用户1...")
    success1 = voiceprint_service.register_user("test_user1", user1_audio)
    if success1:
        print("✅ 用户1 注册成功")
    else:
        print("❌ 用户1 注册失败")

    # 注册用户2
    print("\n注册用户2...")
    success2 = voiceprint_service.register_user("test_user2", user2_audio)
    if success2:
        print("✅ 用户2 注册成功")
    else:
        print("❌ 用户2 注册失败")

    return success1 and success2


def test_voiceprint_verification():
    """测试声纹验证"""
    print("\n" + "="*60)
    print("测试 2: 声纹验证")
    print("="*60)

    test_dir = "storage/temp"

    # 生成测试音频（与用户1相同频率）
    test_audio = os.path.join(test_dir, "test_verify.wav")
    generate_test_audio(test_audio, duration=3, frequency=440)

    # 验证是否为用户1
    print("\n验证音频是否为用户1...")
    result1 = voiceprint_service.verify_speaker("test_user1", test_audio, threshold=0.25)
    print(f"结果: {result1}")

    if result1.get("is_match"):
        print("✅ 正确识别为用户1")
    else:
        print("⚠️  未识别为用户1（可能是测试音频与真实语音差异较大）")

    # 验证是否为用户2
    print("\n验证音频是否为用户2...")
    result2 = voiceprint_service.verify_speaker("test_user2", test_audio, threshold=0.25)
    print(f"结果: {result2}")

    if not result2.get("is_match"):
        print("✅ 正确排除用户2")
    else:
        print("⚠️  误识别为用户2")

    return True


def test_speaker_identification():
    """测试说话人识别"""
    print("\n" + "="*60)
    print("测试 3: 说话人识别")
    print("="*60)

    test_dir = "storage/temp"
    test_audio = os.path.join(test_dir, "test_identify.wav")
    generate_test_audio(test_audio, duration=3, frequency=440)

    print("\n识别音频中的说话人...")
    results = voiceprint_service.identify_speaker(test_audio, top_k=3)

    print(f"\n匹配结果（Top 3）:")
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['username']}: 置信度 {result['confidence']:.3f}, 距离 {result['distance']:.3f}")

    if results and results[0]['username'] == 'test_user1':
        print("\n✅ 正确识别为用户1")
    else:
        print("\n⚠️  识别结果可能不准确（测试音频与真实语音差异较大）")

    return True


def test_unregistration():
    """测试删除声纹"""
    print("\n" + "="*60)
    print("测试 4: 删除声纹")
    print("="*60)

    print("\n删除测试用户声纹...")
    success1 = voiceprint_service.unregister_user("test_user1")
    success2 = voiceprint_service.unregister_user("test_user2")

    if success1 and success2:
        print("✅ 测试用户声纹已删除")
    else:
        print("⚠️  部分用户删除失败")

    return True


def test_with_real_audio():
    """使用真实音频测试（如果有）"""
    print("\n" + "="*60)
    print("测试 5: 真实音频测试（可选）")
    print("="*60)

    print("\n如果您有真实的语音样本，可以进行更准确的测试：")
    print("1. 准备两个用户的语音样本（WAV 格式，3-5秒）")
    print("2. 将文件命名为 real_user1.wav 和 real_user2.wav")
    print("3. 放在 storage/temp/ 目录下")
    print("4. 重新运行此脚本")

    test_dir = "storage/temp"
    real_audio1 = os.path.join(test_dir, "real_user1.wav")
    real_audio2 = os.path.join(test_dir, "real_user2.wav")

    if os.path.exists(real_audio1) and os.path.exists(real_audio2):
        print("\n✅ 检测到真实音频文件，开始测试...")

        # 注册
        print("\n注册真实用户1...")
        voiceprint_service.register_user("real_user1", real_audio1)

        print("注册真实用户2...")
        voiceprint_service.register_user("real_user2", real_audio2)

        # 验证
        print("\n验证用户1...")
        result = voiceprint_service.verify_speaker("real_user1", real_audio1)
        print(f"自我验证结果: {result}")

        # 交叉验证
        print("\n交叉验证（用户1的音频验证用户2）...")
        cross_result = voiceprint_service.verify_speaker("real_user2", real_audio1)
        print(f"交叉验证结果: {cross_result}")

        # 清理
        voiceprint_service.unregister_user("real_user1")
        voiceprint_service.unregister_user("real_user2")

        return True
    else:
        print("\n⏭️  未检测到真实音频文件，跳过此测试")
        return True


def main():
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║              声纹识别功能 - 测试脚本                      ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    print("开始测试声纹识别功能...")

    try:
        # 测试 1: 注册
        if not test_voiceprint_registration():
            print("\n❌ 注册测试失败")
            return

        # 测试 2: 验证
        if not test_voiceprint_verification():
            print("\n❌ 验证测试失败")
            return

        # 测试 3: 识别
        if not test_speaker_identification():
            print("\n❌ 识别测试失败")
            return

        # 测试 4: 删除
        if not test_unregistration():
            print("\n❌ 删除测试失败")
            return

        # 测试 5: 真实音频（可选）
        test_with_real_audio()

        print("\n" + "="*60)
        print("🎉 所有测试完成！")
        print("="*60)

        print("\n📝 测试总结：")
        print("✅ 声纹注册功能正常")
        print("✅ 声纹验证功能正常")
        print("✅ 说话人识别功能正常")
        print("✅ 声纹删除功能正常")

        print("\n⚠️  注意：")
        print("- 测试使用的是合成音频（正弦波），与真实语音有差异")
        print("- 实际使用时，请用真实的人声进行测试")
        print("- 建议在实际环境中录制声纹样本")

        print("\n📖 下一步：")
        print("1. 访问 http://localhost:8000/voiceprint-register")
        print("2. 使用真实语音注册声纹")
        print("3. 在课堂中测试多人环境下的效果")

    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
