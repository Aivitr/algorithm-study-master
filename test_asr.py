"""[EMOJI]"""
from ai_core import engine

# [EMOJI]Token[EMOJI]
print("=" * 60)
print("[EMOJI]")
print("=" * 60)

print("\n1[EMOJI]⃣ [EMOJI]Token...")
engine._refresh_token()

if engine.aliyun_token:
    print(f"[OK] Token[EMOJI]: {engine.aliyun_token[:20]}...")
    print(f"   [EMOJI]: {engine.token_expire}")
else:
    print("[ERROR] Token[EMOJI]")
    exit(1)

print("\n2[EMOJI]⃣ [EMOJI]...")
print("[EMOJI]")
print("[EMOJI]PCM, 16000Hz, [EMOJI]")

# [EMOJI]
import os
test_audio = "storage/audio_chunks"
if os.path.exists(test_audio):
    files = [f for f in os.listdir(test_audio) if f.endswith('.wav')]
    if files:
        audio_path = os.path.join(test_audio, files[0])
        print(f"   [EMOJI]: {audio_path}")
        
        text = engine.transcribe_audio(audio_path)
        if text:
            print(f"[OK] [EMOJI]: {text}")
        else:
            print("[ERROR] [EMOJI]")
    else:
        print("   [EMOJI]")
else:
    print(f"   [EMOJI]: {test_audio}")

print("\n" + "=" * 60)
print("[EMOJI]")
print("=" * 60)
