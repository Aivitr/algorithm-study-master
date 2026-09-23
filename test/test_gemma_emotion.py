"""
测试 Gemma 4 情绪识别功能
"""

import sys
sys.path.insert(0, r"d:\Technology_file\Python_file\2026.4.10\algorithm-study-master")

def test_gemma_connection():
    """测试 Ollama 连接"""
    from gemma_emotion_client import GemmaEmotionClient

    print("=" * 50)
    print("测试 1: Gemma 客户端连接")
    print("=" * 50)

    client = GemmaEmotionClient(base_url="http://localhost:11434", model="gemma:4b")

    if client._check_health():
        print("✓ Ollama 服务正常")
    else:
        print("✗ Ollama 服务不可用，请确保运行: ollama serve")
        return False

    return True


def test_emotion_analysis():
    """测试情绪分析功能"""
    from gemma_emotion_client import GemmaEmotionClient

    print("\n" + "=" * 50)
    print("测试 2: 情绪分析功能")
    print("=" * 50)

    client = GemmaEmotionClient(model="gemma4:e4b")

    # 检查健康状态
    if client._check_health():
        print("✓ Ollama 服务正常")
    else:
        print("✗ Ollama 服务不可用")
        return

    # 模拟不同情绪的特征
    test_cases = [
        {
            "name": "开心",
            "features": {"mouth_open": 0.1, "smile_lift": 0.8, "brow_raise": 0.3, "eye_open": 0.6}
        },
        {
            "name": "惊讶",
            "features": {"mouth_open": 0.7, "smile_lift": 0.1, "brow_raise": 0.9, "eye_open": 0.9}
        },
        {
            "name": "愤怒",
            "features": {"mouth_open": 0.1, "smile_lift": -0.5, "brow_raise": -0.3, "eye_open": 0.5}
        },
        {
            "name": "悲伤",
            "features": {"mouth_open": 0.1, "smile_lift": -0.6, "brow_raise": 0.2, "eye_open": 0.3}
        },
        {
            "name": "中性/平静",
            "features": {"mouth_open": 0.05, "smile_lift": 0.0, "brow_raise": 0.0, "eye_open": 0.4}
        }
    ]

    for i, case in enumerate(test_cases, 1):
        print(f"\n测试案例 {i}: {case['name']}")
        print(f"  特征: {case['features']}")

        emotion, confidence = client.analyze_emotion(case["features"])
        print(f"  结果: {emotion} (置信度: {confidence:.2f})")


def test_video_processor_integration():
    """测试视频处理器集成"""
    print("\n" + "=" * 50)
    print("测试 3: VideoEmotionAnalyzer 集成")
    print("=" * 50)

    try:
        from video_processor import VideoEmotionAnalyzer

        analyzer = VideoEmotionAnalyzer()

        # 手动触发 Gemma 初始化
        analyzer._init_gemma()

        print(f"Gemma 启用状态: {analyzer._gemma_enabled}")

        if analyzer._gemma_enabled:
            print("✓ Gemma 成功集成到 VideoEmotionAnalyzer")
        else:
            print("⚠ Gemma 未启用，请检查 Ollama 服务")

        return True
    except Exception as e:
        print(f"✗ 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("Gemma 4 情绪识别功能测试")
    print("=" * 50)

    # 测试连接
    if not test_gemma_connection():
        print("\n请先启动 Ollama 服务: ollama serve")
        print("然后重新运行测试")
        return

    # 测试情绪分析
    test_emotion_analysis()

    # 测试集成
    test_video_processor_integration()

    print("\n" + "=" * 50)
    print("测试完成!")
    print("=" * 50)


if __name__ == "__main__":
    main()
