import sys
import os
import json
import torch
import warnings
import time
from pyannote.audio import Pipeline

# [EMOJI] UTF-8
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding='utf-8')

# [EMOJI] Token
HF_TOKEN = os.getenv("HF_TOKEN", "")


def main():
    # 1. [EMOJI]
    print(">> [Speaker] [EMOJI] ([EMOJI])...", flush=True)

    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=HF_TOKEN
        )
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        pipeline.to(device)
        print(f">> [Speaker] [EMOJI]! [EMOJI]: {device}", flush=True)
        # [EMOJI]server.py [EMOJI]
        print("SYSTEM_READY", flush=True)
    except Exception as e:
        print(f"SYSTEM_ERROR|{str(e)}", flush=True)
        return

    # 2. [EMOJI]
    while True:
        try:
            # [EMOJI]
            line = sys.stdin.readline()
            if not line: break  # [EMOJI]

            audio_path = line.strip()
            if not audio_path: continue

            # [EMOJI]
            # print(f">> [Speaker] [EMOJI]: {os.path.basename(audio_path)}", flush=True)

            # [EMOJI]
            diarization = pipeline(audio_path)

            # [EMOJI] JSON
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start": turn.start,
                    "end": turn.end,
                    "speaker": speaker
                })

            # [EMOJI]
            json_path = audio_path + ".json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({"segments": segments}, f)

            # [EMOJI]
            print("TASK_DONE", flush=True)

        except Exception as e:
            # [EMOJI] Server [EMOJI]
            print(f"TASK_ERROR|{str(e)}", flush=True)
            print("TASK_DONE", flush=True)


if __name__ == "__main__":
    main()