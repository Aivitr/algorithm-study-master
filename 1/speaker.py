import torch
from torch.torch_version import TorchVersion
from pyannote.audio.core.task import Specifications, Problem , Resolution  # [EMOJI] Problem [EMOJI]
from pyannote.audio import Pipeline

# 2. [EMOJI] Problem[EMOJI]
torch.serialization.add_safe_globals([
    TorchVersion,
    Specifications,
    Problem,
    Resolution
])

import os
import json
from datetime import timedelta
import subprocess

# [EMOJI]Silero VAD[EMOJI]
try:
    from silero_vad import load_silero_vad, read_audio, get_speech_timestamps

    SILERO_AVAILABLE = True
except ImportError:
    SILERO_AVAILABLE = False
    print("[WARN] Silero VAD[EMOJI]")


def format_time(seconds):
    """[EMOJI]"""
    return str(timedelta(seconds=int(seconds)))[2:7]


def get_audio_duration(audio_path):
    """[EMOJI]"""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except:
        return 0


def vad_preprocess(audio_path):
    """
    [EMOJI]Silero VAD[EMOJI]
    """
    if not SILERO_AVAILABLE:
        print("[ERROR] Silero VAD[EMOJI]: pip install silero-vad")
        return None

    print("[TARGET] [EMOJI]Silero VAD[EMOJI]...")

    try:
        torch.set_num_threads(1)
        model = load_silero_vad()
        wav = read_audio(audio_path)

        # [EMOJI]
        speech_timestamps = get_speech_timestamps(wav, model)

        # [EMOJI]16000Hz[EMOJI]
        speech_segments = []
        for ts in speech_timestamps:
            start_sec = ts['start'] / 16000.0
            end_sec = ts['end'] / 16000.0
            speech_segments.append({
                'start': start_sec,
                'end': end_sec,
                'duration': end_sec - start_sec
            })

        print(f"[OK] VAD[EMOJI] {len(speech_segments)} [EMOJI]")
        return speech_segments

    except Exception as e:
        print(f"[ERROR] VAD[EMOJI]: {e}")
        return None


def original_speaker_diarization(audio_path, hf_token):
    """
    [EMOJI]
    """
    print("[PROCESS] [EMOJI]...")
    try:
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        pipeline = pipeline.to(device)

        diarization = pipeline(audio_path)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segment = {
                'start': turn.start,
                'end': turn.end,
                'speaker': speaker,
                'duration': turn.end - turn.start,
                'vad_confidence': 'standard',
                'start_formatted': format_time(turn.start),
                'end_formatted': format_time(turn.end)
            }
            segments.append(segment)

        return segments
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return None


def professional_speaker_diarization(audio_path, hf_token):
    """
    VAD[EMOJI]
    """
    print("[TARGET] [EMOJI]VAD[EMOJI]...")

    try:
        from pyannote.audio import Pipeline

        # 1. VAD[EMOJI]
        vad_segments = vad_preprocess(audio_path)

        # [EMOJI]VAD[EMOJI]
        if vad_segments is None:
            print("[PROCESS] [EMOJI]...")
            return original_speaker_diarization(audio_path, hf_token)

        print("2. [EMOJI]...")
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )

        print("3. [EMOJI]...")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        pipeline = pipeline.to(device)
        print(f"   [EMOJI]: {device}")

        print("4. [EMOJI]VAD[EMOJI]...")
        all_segments = []

        # [EMOJI]VAD[EMOJI]
        full_diarization = pipeline(audio_path)

        # [EMOJI]VAD[EMOJI]
        for vad_seg in vad_segments:
            vad_start = vad_seg['start']
            vad_end = vad_seg['end']

            # [EMOJI]VAD[EMOJI]
            for turn, _, speaker in full_diarization.itertracks(yield_label=True):
                # [EMOJI]
                overlap_start = max(turn.start, vad_start)
                overlap_end = min(turn.end, vad_end)

                if overlap_end - overlap_start > 0.3:  # [EMOJI]0.3[EMOJI]
                    segment = {
                        'start': turn.start,
                        'end': turn.end,
                        'speaker': speaker,
                        'duration': turn.end - turn.start,
                        'vad_confidence': 'high',  # [EMOJI]VAD[EMOJI]
                        'start_formatted': format_time(turn.start),
                        'end_formatted': format_time(turn.end)
                    }
                    # [EMOJI]
                    if not any(s['start'] == segment['start'] and s['end'] == segment['end'] for s in all_segments):
                        all_segments.append(segment)

        print(f"[OK] VAD[EMOJI] {len(all_segments)} [EMOJI]")
        return all_segments

    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return None


def analyze_speaker_results(diarization_segments, audio_duration):
    """
    [EMOJI]
    """
    print("\n[STATS] [EMOJI]...")

    if not diarization_segments:
        print("[ERROR] [EMOJI]")
        return None

    # [EMOJI]
    segments = sorted(diarization_segments, key=lambda x: x['start'])

    # [EMOJI]
    speakers = sorted(set(seg['speaker'] for seg in segments))
    total_speech = sum(seg['duration'] for seg in segments)

    analysis = {
        'speakers_detected': len(speakers),
        'speaker_ids': speakers,
        'total_segments': len(segments),
        'total_speech_duration': total_speech,
        'audio_duration': audio_duration,
        'speech_ratio': (total_speech / audio_duration) * 100,
        'segments': segments,
        'speaker_statistics': {}
    }

    # [EMOJI]
    for speaker in speakers:
        speaker_segments = [s for s in segments if s['speaker'] == speaker]
        speaker_duration = sum(s['duration'] for s in speaker_segments)
        speaker_ratio = (speaker_duration / total_speech) * 100 if total_speech > 0 else 0

        analysis['speaker_statistics'][speaker] = {
            'segment_count': len(speaker_segments),
            'total_duration': speaker_duration,
            'speech_ratio': speaker_ratio,
            'average_segment_length': speaker_duration / len(speaker_segments) if speaker_segments else 0
        }

    return analysis


def generate_smart_slices(analysis):
    """
    [EMOJI]
    """
    print("[TARGET] [EMOJI]...")

    recommendations = []
    segments = analysis['segments']

    # 1. [EMOJI]
    for i in range(1, len(segments)):
        current = segments[i - 1]
        next_seg = segments[i]

        if current['speaker'] != next_seg['speaker']:
            gap = next_seg['start'] - current['end']

            slice_point = {
                'time': current['end'],
                'type': '[EMOJI]',
                'confidence': '[EMOJI]',
                'reason': f"{current['speaker']} → {next_seg['speaker']}",
                'previous_speaker': current['speaker'],
                'next_speaker': next_seg['speaker'],
                'gap_duration': gap
            }
            recommendations.append(slice_point)

    # 2. [EMOJI]
    for segment in segments:
        if segment['duration'] > 12.0:  # [EMOJI]12[EMOJI]
            # [EMOJI]1/3[EMOJI]2/3[EMOJI]
            points = [
                segment['start'] + segment['duration'] * 0.33,
                segment['start'] + segment['duration'] * 0.66
            ]

            for point in points:
                recommendations.append({
                    'time': point,
                    'type': '[EMOJI]',
                    'confidence': '[EMOJI]',
                    'reason': f"{segment['speaker']} [EMOJI]",
                    'segment_duration': segment['duration']
                })

    # [EMOJI]
    recommendations.sort(key=lambda x: x['time'])

    return recommendations


def display_comprehensive_report(analysis, recommendations):
    """
    [EMOJI]
    """
    print("\n" + "=" * 70)
    print("[TARGET] [EMOJI]")
    print("=" * 70)

    # [EMOJI]
    print(f"[STATS] [EMOJI]:")
    print(f"  • [EMOJI]: {analysis['speakers_detected']} [EMOJI]")
    print(f"  • [EMOJI]: {analysis['audio_duration']:.1f} [EMOJI]")
    print(f"  • [EMOJI]: {analysis['total_speech_duration']:.1f} [EMOJI]")
    print(f"  • [EMOJI]: {analysis['speech_ratio']:.1f}%")
    print(f"  • [EMOJI]: {analysis['total_segments']} [EMOJI]")

    # [EMOJI]
    print(f"\n[USERS] [EMOJI]:")
    for speaker, stats in analysis['speaker_statistics'].items():
        print(f"  • {speaker}:")
        print(f"     [EMOJI]: {stats['segment_count']} [EMOJI]")
        print(f"     [EMOJI]: {stats['total_duration']:.1f} [EMOJI]")
        print(f"     [EMOJI]: {stats['speech_ratio']:.1f}%")
        print(f"     [EMOJI]: {stats['average_segment_length']:.1f} [EMOJI]")

    # [EMOJI]
    print(f"\n[EMOJI] [EMOJI] ([EMOJI]10[EMOJI]):")
    for i, segment in enumerate(analysis['segments'][:10], 1):
        print(f"  {i:2d}. {segment['speaker']}: {segment['start_formatted']} - {segment['end_formatted']}")
        print(f"      [EMOJI]: {segment['duration']:.1f}[EMOJI]")

    if len(analysis['segments']) > 10:
        print(f"  ... [EMOJI] {len(analysis['segments']) - 10} [EMOJI]")

    # [EMOJI]
    print(f"\n[TARGET] [EMOJI]: {len(recommendations)} [EMOJI]")
    for i, rec in enumerate(recommendations[:15], 1):
        print(f"  {i:2d}. {format_time(rec['time'])} - {rec['type']}")
        print(f"      [EMOJI]: {rec['reason']}")
        print(f"      [EMOJI]: {rec['confidence']}")


def save_final_report(analysis, recommendations, output_path):
    """
    [EMOJI]
    """
    report = {
        'metadata': {
            'analysis_time': '[EMOJI]VAD[EMOJI]',
            'audio_duration': analysis['audio_duration'],
            'speakers_detected': analysis['speakers_detected'],
            'total_segments': analysis['total_segments'],
            'vad_enhanced': True
        },
        'summary': {
            'speakers': analysis['speaker_ids'],
            'total_speech_duration': analysis['total_speech_duration'],
            'speech_ratio': analysis['speech_ratio'],
            'speaker_statistics': analysis['speaker_statistics']
        },
        'detailed_timeline': analysis['segments'],
        'slice_recommendations': recommendations
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n[SAVE] [EMOJI]: {output_path}")


def main():
    """[EMOJI]"""
    print("=" * 70)
    print("[TARGET] [EMOJI]VAD[EMOJI]")
    print("=" * 70)

    # [EMOJI] pyannote.audio [EMOJI]
    try:
        import pyannote.audio
        print("[OK] pyannote.audio [EMOJI]")
    except ImportError as e:
        print(f"[ERROR] pyannote.audio [EMOJI]: {e}")
        print("[EMOJI]: pip install pyannote.audio")
        return

    # [EMOJI]
    audio_path = r"../domo_professional.wav"

    if not os.path.exists(audio_path):
        print(f"[ERROR] [EMOJI]: {audio_path}")
        return

    # HuggingFace Token
    HF_TOKEN = os.getenv("HF_TOKEN", "")

    if HF_TOKEN == "YOUR_HUGGINGFACE_TOKEN_HERE":
        print("\n[ERROR] [EMOJI] HuggingFace Token:")
        print("1. [EMOJI]: https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("2. [EMOJI] Access Token")
        print("3. [EMOJI] HF_TOKEN [EMOJI]Token")
        return

    # [EMOJI]
    audio_duration = get_audio_duration(audio_path)
    print(f"[FILE] [EMOJI]: {audio_path}")
    print(f"[TIME]  [EMOJI]: {audio_duration:.2f} [EMOJI]")
    print(f"[KEY] [EMOJI] Token: {HF_TOKEN[:10]}...")  # [EMOJI]10[EMOJI]

    # [EMOJI]
    diarization_segments = professional_speaker_diarization(audio_path, HF_TOKEN)

    if diarization_segments:
        # [EMOJI]
        analysis = analyze_speaker_results(diarization_segments, audio_duration)

        if analysis:
            # [EMOJI]
            recommendations = generate_smart_slices(analysis)

            # [EMOJI]
            display_comprehensive_report(analysis, recommendations)

            # [EMOJI]
            output_file = audio_path.replace('.wav', '_professional_diarization.json')
            save_final_report(analysis, recommendations, output_file)

            print("\n" + "=" * 70)
            print("[DONE] [EMOJI]")
            print("[OK] [EMOJI]")
            print("[STATS] [EMOJI]")
            print("[TARGET] [EMOJI]")
            print("\n[FAST] [EMOJI]")
            print("=" * 70)
        else:
            print("\n[ERROR] [EMOJI]")
    else:
        print("\n[ERROR] [EMOJI]")


if __name__ == "__main__":
    main()