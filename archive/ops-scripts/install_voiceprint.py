"""
声纹识别功能 - 快速安装脚本
运行此脚本自动安装依赖和配置
"""
import subprocess
import sys
import os

def print_step(step, message):
    print(f"\n{'='*60}")
    print(f"步骤 {step}: {message}")
    print('='*60)

def install_dependencies():
    """安装 Python 依赖"""
    print_step(1, "安装 Python 依赖")

    packages = [
        "speechbrain",
        "torch",
        "torchaudio",
        "numpy",
    ]

    for package in packages:
        print(f"\n安装 {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✅ {package} 安装成功")
        except subprocess.CalledProcessError:
            print(f"❌ {package} 安装失败")
            return False

    return True

def create_directories():
    """创建必要的目录"""
    print_step(2, "创建存储目录")

    directories = [
        "storage/voiceprints",
        "storage/voiceprint_samples",
        "storage/voiceprint_models",
        "storage/temp",
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"✅ 创建目录: {directory}")

    return True

def download_model():
    """下载声纹识别模型"""
    print_step(3, "下载声纹识别模型")

    print("正在下载 ECAPA-TDNN 模型（约 200MB）...")
    print("这可能需要几分钟，请耐心等待...")

    try:
        from speechbrain.pretrained import EncoderClassifier

        model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="storage/voiceprint_models"
        )

        print("✅ 模型下载成功")
        return True
    except Exception as e:
        print(f"❌ 模型下载失败: {e}")
        print("提示：可以稍后手动下载，或在首次使用时自动下载")
        return False

def test_installation():
    """测试安装"""
    print_step(4, "测试安装")

    try:
        from voiceprint_service import voiceprint_service
        print("✅ voiceprint_service 导入成功")

        from voiceprint_realtime_transcriber import VoiceprintRealtimeTranscriberV2
        print("✅ VoiceprintRealtimeTranscriberV2 导入成功")

        print("\n声纹识别功能已就绪！")
        return True
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def show_next_steps():
    """显示后续步骤"""
    print("\n" + "="*60)
    print("🎉 安装完成！")
    print("="*60)

    print("\n📋 后续步骤：")
    print("\n1. 集成到 server.py：")
    print("   - 打开 voiceprint_api.py")
    print("   - 复制所有 API 路由到 server.py")
    print("   - 修改 ASRSessionManager 使用 VoiceprintRealtimeTranscriberV2")

    print("\n2. 启动服务器：")
    print("   python server.py")

    print("\n3. 访问声纹注册页面：")
    print("   http://localhost:8000/voiceprint-register")

    print("\n4. 注册声纹：")
    print("   - 输入用户名")
    print("   - 录制 3-5 秒清晰语音")
    print("   - 提交注册")

    print("\n5. 进入课堂测试：")
    print("   - 已注册声纹的用户将自动启用声纹过滤")
    print("   - 在多人环境中测试效果")

    print("\n📖 详细文档：")
    print("   查看 VOICEPRINT_GUIDE.md")

    print("\n" + "="*60)

def main():
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║          声纹识别功能 - 快速安装脚本                      ║
    ║                                                          ║
    ║  功能：在多人环境中精准识别单个用户的声音                  ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    # 步骤 1: 安装依赖
    if not install_dependencies():
        print("\n❌ 依赖安装失败，请手动安装")
        return

    # 步骤 2: 创建目录
    if not create_directories():
        print("\n❌ 目录创建失败")
        return

    # 步骤 3: 下载模型（可选）
    print("\n是否现在下载声纹识别模型？（约 200MB）")
    print("输入 y 立即下载，输入 n 稍后下载（首次使用时自动下载）")
    choice = input("请选择 (y/n): ").strip().lower()

    if choice == 'y':
        download_model()
    else:
        print("⏭️  跳过模型下载，将在首次使用时自动下载")

    # 步骤 4: 测试安装
    test_installation()

    # 显示后续步骤
    show_next_steps()

if __name__ == "__main__":
    main()
