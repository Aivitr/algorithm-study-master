def test_environment():
    print("[EMOJI]...")

    try:
        import torch
        print(f"[OK] PyTorch [EMOJI]: {torch.__version__}")
    except ImportError:
        print("[ERROR] PyTorch [EMOJI]")
        return False

    try:
        import pyannote.audio
        print("[OK] pyannote.audio [EMOJI]")
    except ImportError as e:
        print(f"[ERROR] pyannote.audio [EMOJI]: {e}")
        return False

    try:
        import whisper
        print("[OK] Whisper [EMOJI]")
    except ImportError:
        print("[ERROR] Whisper [EMOJI]")
        return False

    try:
        import moviepy
        print("[OK] moviepy [EMOJI]")
    except ImportError:
        print("[ERROR] moviepy [EMOJI]")
        return False

    print("\n[DONE] [EMOJI]")
    return True


if __name__ == "__main__":
    test_environment()