import os
import subprocess
import sys


def check_ffmpeg():
    """[EMOJI]FFmpeg[EMOJI]"""
    try:
        result = subprocess.run(['ffmpeg', '-version'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            print("[OK] FFmpeg [EMOJI]")
            # [EMOJI]
            lines = result.stdout.split('\n')
            if lines:
                print(f"[LIST] [EMOJI]: {lines[0]}")
            return True
        else:
            print("[ERROR] FFmpeg [EMOJI]")
            return False
    except FileNotFoundError:
        print("[ERROR] FFmpeg [EMOJI]PATH")
        return False


def extract_audio_professional(video_path):
    """
    [EMOJI]FFmpeg[EMOJI]
    [EMOJI]
    - -i [EMOJI]
    - -vn [EMOJI]
    - -acodec pcm_s16le [EMOJI]PCM WAV[EMOJI]
    - -ar 44100 CD[EMOJI]
    - -ac 2 [EMOJI]
    - -y [EMOJI]
    """

    if not os.path.exists(video_path):
        print(f"[ERROR] [EMOJI]: {video_path}")
        return None

    # [EMOJI]
    video_dir = os.path.dirname(video_path)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output_audio = os.path.join(video_dir, f"{video_name}_professional.wav")

    print("[TARGET] [EMOJI]...")
    print(f"[EMOJI] [EMOJI]: {video_path}")
    print(f"[SEND] [EMOJI]: {output_audio}")
    print("[EMOJI]  [EMOJI]: [EMOJI]WAV[EMOJI], 44100Hz[EMOJI], [EMOJI]")

    # FFmpeg[EMOJI]
    cmd = [
        'ffmpeg',
        '-i', video_path,  # [EMOJI]
        '-vn',  # [EMOJI]
        '-acodec', 'pcm_s16le',  # [EMOJI]
        '-ar', '44100',  # [EMOJI]
        '-ac', '2',  # [EMOJI]
        '-y',  # [EMOJI]
        output_audio
    ]

    try:
        print("\n[PROCESS] [EMOJI]...[EMOJI]")

        # [EMOJI]FFmpeg
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            # [EMOJI]
            if os.path.exists(output_audio):
                file_size = os.path.getsize(output_audio) / (1024 * 1024)  # MB
                duration = get_audio_duration(output_audio)

                print("[OK] [EMOJI]")
                print(f"[STATS] [EMOJI]: {file_size:.2f} MB")
                print(f"[TIME]  [EMOJI]: {duration:.2f} [EMOJI]")
                print(f"[MUSIC] [EMOJI]: [EMOJI]WAV (PCM)")

                return output_audio
            else:
                print("[ERROR] [EMOJI]")
                return None
        else:
            print(f"[ERROR] FFmpeg[EMOJI]:")
            print(f"[EMOJI]: {result.stderr}")
            return None

    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return None


def get_audio_duration(audio_path):
    """[EMOJI]"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except:
        return 0


def main():
    """[EMOJI]"""
    print("=" * 60)
    print("[TARGET] [EMOJI]")
    print("=" * 60)

    # [EMOJI]FFmpeg
    if not check_ffmpeg():
        print("\n[BULB] [EMOJI]FFmpeg[EMOJI]")
        print("1. [EMOJI]: choco install ffmpeg")
        print("2. [EMOJI]: https://ffmpeg.org/download.html")
        return

    # [EMOJI]
    video_path = r"../domo.mp4"

    print(f"\n[FILE] [EMOJI]: {video_path}")

    if not os.path.exists(video_path):
        print("[ERROR] [EMOJI]")
        return

    # [EMOJI]
    audio_file = extract_audio_professional(video_path)

    if audio_file:
        print("\n" + "=" * 60)
        print("[DONE] [EMOJI]")
        print("[OK] [EMOJI]")
        print(f"[FILE] [EMOJI]: {audio_file}")
        print("\n[FAST] [EMOJI]")
        print("=" * 60)
    else:
        print("\n[ERROR] [EMOJI]")


if __name__ == "__main__":
    main()