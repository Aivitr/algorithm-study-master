import sys
import os
import time
import subprocess
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')

# === [EMOJI] ===
CHUNK_DURATION = 8.0  # [EMOJI] ([EMOJI]8[EMOJI])
STEP_SIZE = 6.0  # [EMOJI] ([EMOJI]6[EMOJI]2[EMOJI])

# [EMOJI]: "funasr" ([EMOJI]) [EMOJI] "aliyun" ([EMOJI])
ASR_ENGINE = "aliyun"

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_1_DIR = os.path.join(ROOT_DIR, '1')
VIDEO_PATH = os.path.join(ROOT_DIR, "domo.mp4")

SERVICE_SPEAKER = os.path.join(MODULE_1_DIR, 'service_speaker.py')
SERVICE_ALIYUN = os.path.join(MODULE_1_DIR, 'service_aliyun.py')
SERVICE_FUNASR = os.path.join(MODULE_1_DIR, 'service_funasr.py')


def print_flush(msg):
    print(msg, flush=True)


class ServiceManager:
    def __init__(self, script_path, name):
        self.name = name
        self.lock = threading.Lock()
        self.process = subprocess.Popen(
            [sys.executable, "-u", script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            cwd=MODULE_1_DIR,
            bufsize=1
        )
        self.wait_for_ready()

    def wait_for_ready(self):
        while True:
            line = self.process.stdout.readline()
            if not line: break
            line = line.strip()
            if "SERVICE_READY" in line:
                print_flush(f"[OK] {self.name} [EMOJI]")
                break
            elif "SERVICE_ERROR" in line:
                print_flush(f"[ERROR] {self.name} [EMOJI]: {line}")
                break
            else:
                print_flush(f"[{self.name}] {line}")

    def process_task(self, msg, end_marker):
        with self.lock:
            if self.process.poll() is not None: return None
            self.process.stdin.write(msg + "\n")
            self.process.stdin.flush()

            result_data = None
            while True:
                line = self.process.stdout.readline()
                if not line: break
                line = line.strip()
                if end_marker in line:
                    break
                elif "TEXT_RESULT" in line:
                    parts = line.split('|', 1)
                    if len(parts) > 1: result_data = parts[1]
                elif "TASK_ERROR" in line:
                    print_flush(f"[WARN] {self.name} [EMOJI]: {line}")
                # else: print_flush(line) # [EMOJI]
            return result_data


def get_video_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
               'default=noprint_wrappers=1:nokey=1', file_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return float(res.stdout.strip())
    except:
        return 60.0


def get_dominant_speaker(json_path):
    if not os.path.exists(json_path): return "Unknown"
    try:
        import json
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        segments = data.get("segments", [])
        if not segments: return "Unknown"
        stats = {}
        for seg in segments:
            spk = seg['speaker']
            dur = seg['end'] - seg['start']
            stats[spk] = stats.get(spk, 0) + dur
        return max(stats, key=stats.get)
    except:
        return "Unknown"


# === [EMOJI] ===
def worker_task(chunk_wav, start_time, duration, speaker_service, aliyun_service):
    """
    [EMOJI]
    1. [EMOJI] -> [EMOJI] (Speaker: [EMOJI]..., Text: [EMOJI])
    2. [EMOJI] -> [EMOJI] (Speaker: SPEAKER_01, Text: [EMOJI])
    """

    # [EMOJI]
    current_text = "..."
    current_speaker = "[EMOJI]..."  # [EMOJI]

    # [EMOJI]
    def do_aliyun():
        nonlocal current_text
        # print_flush(f">> [Async] [EMOJI] ({start_time}s)...")
        text = aliyun_service.process_task(chunk_wav, "TEXT_RESULT")
        if text:
            current_text = text
            # [FAST][EMOJI] [EMOJI]
            print_flush(
                f"[EMOJI]: {start_time:.2f}-{start_time + duration:.2f}s | Spk: {current_speaker} | Text: {current_text}")
        return text

    def do_speaker():
        nonlocal current_speaker
        # print_flush(f">> [Async] [EMOJI] ({start_time}s)...")
        speaker_service.process_task(chunk_wav, "ANALYSIS_DONE")

        json_path = chunk_wav + ".json"
        speaker = get_dominant_speaker(json_path)
        if speaker != "Unknown":
            current_speaker = speaker

        # [EMOJI]JSON
        if os.path.exists(json_path): os.remove(json_path)
        return current_speaker

    # [EMOJI]
    with ThreadPoolExecutor(max_workers=2) as executor:
        # [EMOJI]
        future_ali = executor.submit(do_aliyun)
        future_spk = executor.submit(do_speaker)

        # [EMOJI]
        future_ali.result()
        future_spk.result()

    # [FAST][EMOJI] [EMOJI]([EMOJI])
    if current_speaker != "[EMOJI]...":
        print_flush(
            f"[EMOJI]: {start_time:.2f}-{start_time + duration:.2f}s | Spk: {current_speaker} | Text: {current_text}")

    # [EMOJI]
    if os.path.exists(chunk_wav):
        try:
            os.remove(chunk_wav)
        except:
            pass


def realtime_integration():
    print_flush("=" * 60)
    print_flush("[TARGET] [EMOJI] v6.0 (FunASR[EMOJI])")
    print_flush(f">> [EMOJI]: {ASR_ENGINE.upper()}")
    print_flush(">> [EMOJI]: [EMOJI]")
    print_flush("=" * 60)

    if not os.path.exists(VIDEO_PATH):
        print_flush("[ERROR] [EMOJI] domo.mp4")
        return

    try:
        speaker_service = ServiceManager(SERVICE_SPEAKER, "Speaker")
        # [EMOJI]
        if ASR_ENGINE == "funasr":
            asr_service = ServiceManager(SERVICE_FUNASR, "FunASR")
            print_flush("[OK] [EMOJI]FunASR[EMOJI]")
        else:
            asr_service = ServiceManager(SERVICE_ALIYUN, "Aliyun")
            print_flush("[OK] [EMOJI]API[EMOJI]")
    except Exception as e:
        print_flush(f"[ERROR] [EMOJI]: {e}")
        return

    duration = get_video_duration(VIDEO_PATH)
    print_flush(f">> [EMOJI]: {duration:.1f}s. [EMOJI]...")

    # [EMOJI]
    # max_workers=2 [EMOJI]
    main_executor = ThreadPoolExecutor(max_workers=2)

    current_time = 0.0

    while current_time < duration:
        # [EMOJI] 8s
        extract_duration = CHUNK_DURATION
        if current_time + extract_duration > duration: extract_duration = duration - current_time

        # [EMOJI]
        chunk_wav = os.path.join(MODULE_1_DIR, f"stream_{int(current_time)}.wav")

        # FFmpeg [EMOJI]
        subprocess.run([
            'ffmpeg', '-y', '-ss', str(current_time), '-t', str(extract_duration),
            '-i', VIDEO_PATH, '-ac', '1', '-ar', '16000', '-f', 'wav', '-loglevel', 'error',
            chunk_wav
        ])

        if os.path.exists(chunk_wav):
            # print_flush(f">> [[EMOJI]] [EMOJI]: {current_time}s")
            main_executor.submit(worker_task, chunk_wav, current_time, CHUNK_DURATION, speaker_service, asr_service)

        # [EMOJI] 6s ([EMOJI] 2s [EMOJI])
        current_time += STEP_SIZE

        # [EMOJI]
        time.sleep(0.5)

    main_executor.shutdown(wait=True)
    print_flush("[DONE] [EMOJI]")

    speaker_service.process.kill()
    asr_service.process.kill()


if __name__ == "__main__":
    realtime_integration()