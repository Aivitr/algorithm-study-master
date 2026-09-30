import os
import json
import subprocess
from datetime import timedelta
import shutil


def format_time(seconds):
    """[EMOJI]"""
    return str(timedelta(seconds=int(seconds)))[2:7]


def load_complete_analysis(audio_path):
    """
    [EMOJI] - [EMOJI]
    """
    analysis_file = audio_path.replace('.wav', '_complete_analysis.json')

    if not os.path.exists(analysis_file):
        print(f"[ERROR] [EMOJI]: {analysis_file}")
        return None

    with open(analysis_file, 'r', encoding='utf-8') as f:
        analysis_data = json.load(f)

    # [EMOJI]
    if 'detailed_transcription' in analysis_data:
        # [EMOJI]
        return analysis_data
    else:
        # [EMOJI]
        print("[WARN] [EMOJI]...")
        return convert_old_format(analysis_data)

def get_video_path(audio_path):
    """
    [EMOJI]
    """
    # [EMOJI]
    video_dir = os.path.dirname(audio_path)

    # [EMOJI]
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.wmv']

    for ext in video_extensions:
        video_file = audio_path.replace('_professional.wav', ext)
        if os.path.exists(video_file):
            return video_file

        # [EMOJI]
        video_file = audio_path.replace('_professional.wav', '') + ext
        if os.path.exists(video_file):
            return video_file

    # [EMOJI]
    original_video = r"C:\Users\31615\Documents\study--ex\goa\1\domo.mp4"
    if os.path.exists(original_video):
        return original_video

    return None


def create_output_directory(video_path):
    """
    [EMOJI]
    """
    video_dir = os.path.dirname(video_path)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output_dir = os.path.join(video_dir, f"{video_name}_slices")

    # [EMOJI]
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)

    os.makedirs(output_dir)
    print(f"[FILE] [EMOJI]: {output_dir}")

    return output_dir


def generate_slice_segments(enhanced_slices, total_duration):
    """
    [EMOJI]
    """
    print("[TARGET] [EMOJI]...")

    segments = []
    start_time = 0.0

    # [EMOJI]
    slice_times = [slice_point['time'] for slice_point in enhanced_slices]
    slice_times.append(total_duration)

    for i, end_time in enumerate(slice_times):
        segment_duration = end_time - start_time

        if segment_duration > 1.0:  # [EMOJI]1[EMOJI]
            segment_info = {
                'segment_id': i + 1,
                'start_time': start_time,
                'end_time': end_time,
                'duration': segment_duration,
                'start_formatted': format_time(start_time),
                'end_formatted': format_time(end_time)
            }
            segments.append(segment_info)

        start_time = end_time

    return segments


def slice_video_ffmpeg(video_path, segments, output_dir):
    """
    [EMOJI] FFmpeg [EMOJI]
    """
    print("[START] [EMOJI]...")

    successful_slices = []
    failed_slices = []

    for segment in segments:
        segment_id = segment['segment_id']
        start_time = segment['start_time']
        duration = segment['duration']

        output_file = os.path.join(output_dir, f"segment_{segment_id:03d}.mp4")

        print(f"  [EMOJI] {segment_id}: {segment['start_formatted']} - {segment['end_formatted']}")

        # FFmpeg [EMOJI]
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-ss', str(start_time),  # [EMOJI]
            '-t', str(duration),  # [EMOJI]
            '-c', 'copy',  # [EMOJI]
            '-avoid_negative_ts', '1',  # [EMOJI]
            '-y',  # [EMOJI]
            output_file
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0 and os.path.exists(output_file):
                file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
                segment['output_file'] = output_file
                segment['file_size_mb'] = round(file_size, 2)
                successful_slices.append(segment)
                print(f"    [OK] [EMOJI]: {os.path.basename(output_file)} ({file_size:.1f} MB)")
            else:
                segment['error'] = result.stderr
                failed_slices.append(segment)
                print(f"    [ERROR] [EMOJI]: {result.stderr[:100]}...")

        except Exception as e:
            segment['error'] = str(e)
            failed_slices.append(segment)
            print(f"    [ERROR] [EMOJI]: {e}")

    return successful_slices, failed_slices


def create_slice_metadata(successful_slices, analysis_data, output_dir):
    """
    [EMOJI]
    """
    print("[LIST] [EMOJI]...")

    metadata = {
        'project_info': {
            'video_source': os.path.basename(
                analysis_data['metadata']['audio_file'].replace('_professional.wav', '.mp4')),
            'total_segments': len(successful_slices),
            'total_duration': sum(segment['duration'] for segment in successful_slices),
            'created_time': '[EMOJI]'
        },
        'segments': [],
        'analysis_summary': analysis_data['conversation_summary']
    }

    for segment in successful_slices:
        segment_metadata = {
            'segment_id': segment['segment_id'],
            'start_time': segment['start_time'],
            'end_time': segment['end_time'],
            'duration': segment['duration'],
            'time_range': f"{segment['start_formatted']} - {segment['end_formatted']}",
            'output_file': os.path.basename(segment['output_file']),
            'file_size_mb': segment['file_size_mb']
        }
        metadata['segments'].append(segment_metadata)

    metadata_file = os.path.join(output_dir, "slices_metadata.json")
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"[SAVE] [EMOJI]: {metadata_file}")
    return metadata_file


def create_slice_preview(successful_slices, output_dir):
    """
    [EMOJI]
    """
    print("[EMOJI] [EMOJI]...")

    preview_content = []
    preview_content.append("# [EMOJI]")
    preview_content.append("")
    preview_content.append("## [EMOJI]")
    preview_content.append("")

    for segment in successful_slices:
        preview_content.append(f"### [EMOJI] {segment['segment_id']:03d}")
        preview_content.append(f"- **[EMOJI]**: {segment['start_formatted']} - {segment['end_formatted']}")
        preview_content.append(f"- **[EMOJI]**: {segment['duration']:.1f} [EMOJI]")
        preview_content.append(f"- **[EMOJI]**: `{os.path.basename(segment['output_file'])}`")
        preview_content.append(f"- **[EMOJI]**: {segment['file_size_mb']} MB")
        preview_content.append("")

    preview_file = os.path.join(output_dir, "SLICES_PREVIEW.md")
    with open(preview_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(preview_content))

    print(f"[EMOJI] [EMOJI]: {preview_file}")
    return preview_file


def generate_final_report(analysis_data, successful_slices, output_dir, video_path):
    """
    [EMOJI]
    """
    print("[STATS] [EMOJI]...")

    video_name = os.path.splitext(os.path.basename(video_path))[0]

    report = {
        'project_title': f'[EMOJI] - {video_name}',
        'analysis_overview': {
            'original_video': os.path.basename(video_path),
            'total_duration_seconds': analysis_data['conversation_summary']['conversation_overview'].get(
                'audio_duration', 0),
            'speakers_detected': analysis_data['conversation_summary']['conversation_overview']['total_speakers'],
            'conversation_segments': analysis_data['conversation_summary']['conversation_overview']['total_segments'],
            'total_words': analysis_data['conversation_summary']['conversation_overview']['total_words'],
            'questions_identified': analysis_data['conversation_summary']['conversation_overview']['questions_count']
        },
        'slicing_results': {
            'total_slices_created': len(successful_slices),
            'total_slice_duration': sum(segment['duration'] for segment in successful_slices),
            'average_slice_duration': sum(segment['duration'] for segment in successful_slices) / len(
                successful_slices) if successful_slices else 0,
            'output_directory': output_dir
        },
        'speaker_analysis': analysis_data['conversation_summary']['speaker_contributions'],
        'slice_details': [
            {
                'slice_id': segment['segment_id'],
                'time_range': f"{segment['start_formatted']} - {segment['end_formatted']}",
                'duration_seconds': segment['duration'],
                'file_name': os.path.basename(segment['output_file']),
                'file_size_mb': segment['file_size_mb']
            }
            for segment in successful_slices
        ]
    }

    report_file = os.path.join(output_dir, "FINAL_PROJECT_REPORT.json")
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # [EMOJI]
    text_report = create_readable_report(report, output_dir)

    return report_file, text_report


def create_readable_report(report_data, output_dir):
    """
    [EMOJI]
    """
    content = []
    content.append("# [TARGET] [EMOJI]")
    content.append("")

    # [EMOJI]
    overview = report_data['analysis_overview']
    content.append("## [STATS] [EMOJI]")
    content.append("")
    content.append(f"- **[EMOJI]**: {overview['original_video']}")
    content.append(f"- **[EMOJI]**: {format_time(overview['total_duration_seconds'])}")
    content.append(f"- **[EMOJI]**: {overview['speakers_detected']} [EMOJI]")
    content.append(f"- **[EMOJI]**: {overview['conversation_segments']} [EMOJI]")
    content.append(f"- **[EMOJI]**: {overview['total_words']} [EMOJI]")
    content.append(f"- **[EMOJI]**: {overview['questions_identified']} [EMOJI]")
    content.append("")

    # [EMOJI]
    slicing = report_data['slicing_results']
    content.append("## [START] [EMOJI]")
    content.append("")
    content.append(f"- **[EMOJI]**: {slicing['total_slices_created']} [EMOJI]")
    content.append(f"- **[EMOJI]**: {format_time(slicing['total_slice_duration'])}")
    content.append(f"- **[EMOJI]**: {slicing['average_slice_duration']:.1f} [EMOJI]")
    content.append(f"- **[EMOJI]**: `{slicing['output_directory']}`")
    content.append("")

    # [EMOJI]
    content.append("## [USERS] [EMOJI]")
    content.append("")
    for speaker, stats in report_data['speaker_analysis'].items():
        content.append(f"### {speaker}")
        content.append(f"- [EMOJI]: {stats['segment_count']} [EMOJI]")
        content.append(f"- [EMOJI]: {stats['word_count']} [EMOJI]")
        content.append(f"- [EMOJI]: {stats['word_ratio']:.1f}%")
        content.append(f"- [EMOJI]: {stats['questions_asked']} [EMOJI]")
        content.append("")

    # [EMOJI]
    content.append("## [FILE] [EMOJI]")
    content.append("")
    content.append("| [EMOJI]ID | [EMOJI] | [EMOJI] | [EMOJI] |")
    content.append("|--------|----------|------|----------|")

    for slice_info in report_data['slice_details']:
        content.append(
            f"| {slice_info['slice_id']:02d} | {slice_info['time_range']} | {slice_info['duration_seconds']:.1f}s | {slice_info['file_size_mb']} MB |")

    content.append("")
    content.append("## [DONE] [EMOJI]")
    content.append("")
    content.append("[EMOJI]")

    text_report_file = os.path.join(output_dir, "PROJECT_REPORT.md")
    with open(text_report_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))

    print(f"[EMOJI] [EMOJI]: {text_report_file}")
    return text_report_file


def display_final_summary(successful_slices, failed_slices, output_dir, report_files):
    """
    [EMOJI]
    """
    print("\n" + "=" * 70)
    print("[DONE] [EMOJI]")
    print("=" * 70)

    total_duration = sum(segment['duration'] for segment in successful_slices)
    avg_duration = total_duration / len(successful_slices) if successful_slices else 0

    print(f"[STATS] [EMOJI]:")
    print(f"  • [EMOJI]: {len(successful_slices)} [EMOJI]")
    print(f"  • [EMOJI]: {len(failed_slices)} [EMOJI]")
    print(f"  • [EMOJI]: {format_time(total_duration)}")
    print(f"  • [EMOJI]: {avg_duration:.1f} [EMOJI]")

    print(f"\n[FILE] [EMOJI]:")
    print(f"  • [EMOJI]: {output_dir}")
    for report_file in report_files:
        print(f"  • {os.path.basename(report_file)}")

    print(f"\n[START] [EMOJI]:")
    for segment in successful_slices[:5]:  # [EMOJI]5[EMOJI]
        # [EMOJI]
        time_range = f"{segment['start_formatted']} - {segment['end_formatted']}"
        print(f"  • {os.path.basename(segment['output_file'])} - {time_range}")

    if len(successful_slices) > 5:
        print(f"  ... [EMOJI] {len(successful_slices) - 5} [EMOJI]")

    if failed_slices:
        print(f"\n[WARN]  [EMOJI]:")
        for failed in failed_slices:
            print(f"  • [EMOJI] {failed['segment_id']}: {failed.get('error', '[EMOJI]')}")

def main():
    """[EMOJI]"""
    print("=" * 70)
    print("[TARGET] [EMOJI]")
    print("=" * 70)

    # [EMOJI]
    audio_path = r"../domo_professional.wav"

    if not os.path.exists(audio_path):
        print(f"[ERROR] [EMOJI]: {audio_path}")
        return

    print(f"[FILE] [EMOJI]: {audio_path}")

    # 1. [EMOJI]
    analysis_data = load_complete_analysis(audio_path)
    if not analysis_data:
        return

    print("[OK] [EMOJI]")

    # 2. [EMOJI]
    video_path = get_video_path(audio_path)
    if not video_path:
        print("[ERROR] [EMOJI]")
        return

    print(f"[START] [EMOJI]: {video_path}")

    # 3. [EMOJI]
    output_dir = create_output_directory(video_path)

    # 4. [EMOJI]
    enhanced_slices = analysis_data.get('enhanced_slice_recommendations', [])
    total_duration = analysis_data['conversation_summary']['conversation_overview'].get('audio_duration', 0)

    slice_segments = generate_slice_segments(enhanced_slices, total_duration)

    if not slice_segments:
        print("[ERROR] [EMOJI]")
        return

    print(f"[STATS] [EMOJI] {len(slice_segments)} [EMOJI]")

    # 5. [EMOJI]
    successful_slices, failed_slices = slice_video_ffmpeg(video_path, slice_segments, output_dir)

    if not successful_slices:
        print("[ERROR] [EMOJI]")
        return

    # 6. [EMOJI]
    metadata_file = create_slice_metadata(successful_slices, analysis_data, output_dir)
    preview_file = create_slice_preview(successful_slices, output_dir)
    report_file, text_report = generate_final_report(analysis_data, successful_slices, output_dir, video_path)

    # 7. [EMOJI]
    display_final_summary(successful_slices, failed_slices, output_dir,
                          [metadata_file, preview_file, report_file, text_report])

    print("\n" + "=" * 70)
    print("[DONE] [EMOJI]")
    print("[OK] [EMOJI]")
    print("[STATS] [EMOJI]")
    print("[TARGET] [EMOJI]AI[EMOJI]")
    print(f"[SAVE] [EMOJI]: {output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()