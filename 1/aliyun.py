import os
import json
import requests
import base64
import hashlib
import hmac
import time
from datetime import timedelta
import subprocess
import uuid
import shutil


class AliyunSpeechRecognizer:
    """[EMOJI]"""

    def __init__(self, access_key_id, access_key_secret, app_key):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.app_key = app_key
        self.host = "wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1"

    def get_auth_token(self):
        """[EMOJI]Token"""
        try:
            url = "https://nls-meta.cn-shanghai.aliyuncs.com/"
            version = "2019-02-28"
            action = "CreateToken"

            # [EMOJI]
            params = {
                "Action": action,
                "Format": "JSON",
                "Version": version,
                "AccessKeyId": self.access_key_id,
                "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "SignatureMethod": "HMAC-SHA1",
                "SignatureVersion": "1.0",
                "SignatureNonce": str(uuid.uuid4())
            }

            # [EMOJI]
            sorted_params = sorted(params.items())
            canonicalized_query_string = ""
            for (k, v) in sorted_params:
                canonicalized_query_string += '&' + self._percent_encode(k) + '=' + self._percent_encode(v)

            string_to_sign = 'GET&%2F&' + self._percent_encode(canonicalized_query_string[1:])

            key = self.access_key_secret + '&'
            signature = base64.b64encode(
                hmac.new(key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
            ).decode()

            params['Signature'] = signature

            # [EMOJI]
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if 'Token' in result:
                    token = result['Token']['Id']
                    print("[OK] [EMOJI]Token[EMOJI]")
                    return token
                else:
                    print(f"[ERROR] Token[EMOJI]: {result}")
                    return None
            else:
                print(f"[ERROR] Token[EMOJI]: {response.status_code}")
                return None

        except Exception as e:
            print(f"[ERROR] [EMOJI]Token[EMOJI]: {e}")
            return None

    def _percent_encode(self, encode_str):
        """URL[EMOJI]"""
        import urllib.parse
        return urllib.parse.quote(encode_str, safe='')

    def recognize_audio_file(self, audio_file_path, sample_rate=16000):
        """[EMOJI]"""
        try:
            # [EMOJI]Token
            token = self.get_auth_token()
            if not token:
                return None

            # [EMOJI]
            with open(audio_file_path, 'rb') as f:
                audio_data = f.read()

            # [EMOJI]
            url = "http://nls-gateway.cn-shanghai.aliyuncs.com/stream/v1/asr"

            # [EMOJI]
            format = "pcm"
            if sample_rate == 8000:
                format = "pcm"
            elif sample_rate == 16000:
                format = "pcm"

            params = {
                "appkey": self.app_key,
                "format": format,
                "sample_rate": sample_rate,
                "enable_punctuation_prediction": True,
                "enable_inverse_text_normalization": True,
                "enable_voice_detection": True
            }

            headers = {
                "X-NLS-Token": token,
                "Content-Type": "application/octet-stream"
            }

            print(f"[AUDIO] [EMOJI]: {len(audio_data)} bytes")

            # [EMOJI]
            response = requests.post(url, params=params, headers=headers, data=audio_data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result.get("status") == 20000000 and "result" in result:
                    print(f"[OK] [EMOJI]: {result['result']}")
                    return result['result']
                else:
                    print(f"[ERROR] [EMOJI]: {result}")
                    return None
            else:
                print(f"[ERROR] [EMOJI]: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"[ERROR] [EMOJI]: {e}")
            return None


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


def load_speaker_analysis(audio_path):
    """
    [EMOJI]
    """
    analysis_file = audio_path.replace('.wav', '_professional_diarization.json')

    if not os.path.exists(analysis_file):
        print(f"[ERROR] [EMOJI]: {analysis_file}")
        return None

    with open(analysis_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_audio_segment(audio_path, start_time, end_time, output_path):
    """
    [EMOJI]FFmpeg[EMOJI]
    """
    duration = end_time - start_time

    # [EMOJI]0.5[EMOJI]
    if duration < 0.5:
        print(f"⏩ [EMOJI]: {start_time:.2f}-{end_time:.2f} ({duration:.2f}s)")
        return False

    cmd = [
        'ffmpeg',
        '-i', audio_path,
        '-ss', str(start_time),
        '-t', str(duration),
        '-acodec', 'pcm_s16le',  # 16bit PCM
        '-ar', '16000',  # 16kHz[EMOJI]
        '-ac', '1',  # [EMOJI]
        '-af', 'highpass=f=300,lowpass=f=3400',  # [EMOJI]
        '-y',
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"[OK] [EMOJI]: {format_time(start_time)}-{format_time(end_time)} ({file_size} bytes)")
            return True
        else:
            print(f"[ERROR] [EMOJI]: {result.stderr}")
            return False
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return False


def professional_speech_transcription(audio_path, speaker_analysis, config):
    """
    [EMOJI]API[EMOJI]
    """
    print("[TARGET] [EMOJI]API[EMOJI]...")

    # [EMOJI]VAD[EMOJI]
    if 'detailed_timeline' in speaker_analysis:
        speaker_segments = speaker_analysis['detailed_timeline']
    else:
        # [EMOJI]segments
        speaker_segments = speaker_analysis.get('segments', [])

    # [EMOJI]
    recognizer = AliyunSpeechRecognizer(
        access_key_id=config['ALIYUN_ACCESS_KEY_ID'],
        access_key_secret=config['ALIYUN_ACCESS_KEY_SECRET'],
        app_key=config['ALIYUN_APP_KEY']
    )

    transcribed_segments = []

    # [EMOJI]
    temp_dir = os.path.join(os.path.dirname(audio_path), "temp_segments")
    os.makedirs(temp_dir, exist_ok=True)

    total_segments = len(speaker_segments)
    success_count = 0

    print(f"[STATS] [EMOJI] {total_segments} [EMOJI]...")

    for i, speaker_seg in enumerate(speaker_segments, 1):
        start_time = speaker_seg['start']
        end_time = speaker_seg['end']
        duration = speaker_seg['duration']

        print(f"\n[SEARCH] [EMOJI] {i}/{total_segments}:")
        print(f"   [EMOJI]: {speaker_seg['speaker']}")
        print(f"   [EMOJI]: {speaker_seg['start_formatted']} - {speaker_seg['end_formatted']}")
        print(f"   [EMOJI]: {duration:.1f}[EMOJI]")

        # [EMOJI]
        temp_audio_path = os.path.join(temp_dir, f"segment_{i:04d}.wav")

        if extract_audio_segment(audio_path, start_time, end_time, temp_audio_path):
            # [EMOJI]API[EMOJI]
            recognized_text = recognizer.recognize_audio_file(temp_audio_path)

            if recognized_text and recognized_text.strip():
                # [EMOJI]
                transcribed_segment = {
                    'speaker': speaker_seg['speaker'],
                    'start': start_time,
                    'end': end_time,
                    'duration': duration,
                    'start_formatted': speaker_seg['start_formatted'],
                    'end_formatted': speaker_seg['end_formatted'],
                    'text': recognized_text.strip(),
                    'word_count': len(recognized_text.strip()),
                    'confidence': 'high',
                    'recognition_source': 'aliyun'
                }
                transcribed_segments.append(transcribed_segment)
                success_count += 1
                print(f"   [OK] [EMOJI]: {recognized_text}")
            else:
                # [EMOJI]
                transcribed_segment = {
                    'speaker': speaker_seg['speaker'],
                    'start': start_time,
                    'end': end_time,
                    'duration': duration,
                    'start_formatted': speaker_seg['start_formatted'],
                    'end_formatted': speaker_seg['end_formatted'],
                    'text': '[[EMOJI]]',
                    'word_count': 0,
                    'confidence': 'low',
                    'recognition_source': 'aliyun_failed'
                }
                transcribed_segments.append(transcribed_segment)
                print(f"   [ERROR] [EMOJI]")
        else:
            # [EMOJI]
            transcribed_segment = {
                'speaker': speaker_seg['speaker'],
                'start': start_time,
                'end': end_time,
                'duration': duration,
                'start_formatted': speaker_seg['start_formatted'],
                'end_formatted': speaker_seg['end_formatted'],
                'text': '[[EMOJI]]',
                'word_count': 0,
                'confidence': 'low',
                'recognition_source': 'extraction_failed'
            }
            transcribed_segments.append(transcribed_segment)
            print(f"   [ERROR] [EMOJI]")

    # [EMOJI]
    try:
        shutil.rmtree(temp_dir)
        print(f"[CLEAN] [EMOJI]")
    except:
        pass

    print(f"\n[STATS] [EMOJI]: {success_count}/{total_segments} [EMOJI]")

    return transcribed_segments


def analyze_text_content(transcribed_segments):
    """
    [EMOJI]
    """
    print("[STATS] [EMOJI]...")

    analysis = {
        'total_segments': len(transcribed_segments),
        'total_words': 0,
        'successful_transcriptions': 0,
        'speaker_text_analysis': {},
        'content_features': {
            'questions_detected': 0,
            'statements_detected': 0,
            'long_segments': 0,
            'short_segments': 0
        }
    }

    # [EMOJI]
    speakers = set(seg['speaker'] for seg in transcribed_segments)
    for speaker in speakers:
        analysis['speaker_text_analysis'][speaker] = {
            'segment_count': 0,
            'total_words': 0,
            'average_words_per_segment': 0,
            'successful_count': 0,
            'content_types': {'questions': 0, 'statements': 0},
            'segments': []
        }

    # [EMOJI]
    for segment in transcribed_segments:
        speaker = segment['speaker']
        text = segment['text']
        word_count = segment['word_count']

        # [EMOJI]
        is_successful = (segment.get('confidence') == 'high' and
                         text not in ['[[EMOJI]]', '[[EMOJI]]'] and
                         word_count > 0)

        # [EMOJI]
        if is_successful:
            analysis['total_words'] += word_count
            analysis['successful_transcriptions'] += 1

        # [EMOJI]
        analysis['speaker_text_analysis'][speaker]['segment_count'] += 1
        if is_successful:
            analysis['speaker_text_analysis'][speaker]['total_words'] += word_count
            analysis['speaker_text_analysis'][speaker]['successful_count'] += 1
        analysis['speaker_text_analysis'][speaker]['segments'].append(segment)

        # [EMOJI]
        if is_successful:
            if is_question(text):
                analysis['content_features']['questions_detected'] += 1
                analysis['speaker_text_analysis'][speaker]['content_types']['questions'] += 1
            else:
                analysis['content_features']['statements_detected'] += 1
                analysis['speaker_text_analysis'][speaker]['content_types']['statements'] += 1

            # [EMOJI]
            if word_count > 50:
                analysis['content_features']['long_segments'] += 1
            elif word_count < 10:
                analysis['content_features']['short_segments'] += 1

    # [EMOJI]
    for speaker in speakers:
        stats = analysis['speaker_text_analysis'][speaker]
        if stats['successful_count'] > 0:
            stats['average_words_per_segment'] = stats['total_words'] / stats['successful_count']
        else:
            stats['average_words_per_segment'] = 0

    return analysis


def is_question(text):
    """[EMOJI]"""
    if not text or text in ['[[EMOJI]]', '[[EMOJI]]']:
        return False

    question_indicators = ['[EMOJI]', '?', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]',
                           '[EMOJI]', '[EMOJI]']
    return any(indicator in text for indicator in question_indicators)


def enhance_slice_recommendations(original_slices, transcribed_segments, text_analysis):
    """
    [EMOJI]
    """
    print("[TARGET] [EMOJI]...")

    enhanced_slices = original_slices.copy()

    # [EMOJI]
    for segment in transcribed_segments:
        text = segment['text']

        # [EMOJI]
        if text in ['[[EMOJI]]', '[[EMOJI]]']:
            continue

        # 1. [EMOJI]
        if is_question(text) and segment['duration'] < 8.0:
            # [EMOJI]
            enhanced_slices.append({
                'time': segment['end'],
                'type': '[EMOJI]',
                'confidence': '[EMOJI]',
                'reason': f"[EMOJI]: {text[:30]}...",
                'based_on': '[EMOJI]'
            })

        # 2. [EMOJI]
        if segment['word_count'] > 80:
            # [EMOJI]
            points = [0.25, 0.5, 0.75]
            for ratio in points:
                slice_time = segment['start'] + segment['duration'] * ratio
                enhanced_slices.append({
                    'time': slice_time,
                    'type': '[EMOJI]',
                    'confidence': '[EMOJI]',
                    'reason': f"[EMOJI] ({segment['word_count']}[EMOJI])",
                    'based_on': '[EMOJI]'
                })

    # [EMOJI]
    enhanced_slices.sort(key=lambda x: x['time'])

    final_slices = []
    last_time = -3.0

    for slice_point in enhanced_slices:
        if slice_point['time'] - last_time > 2.0:
            final_slices.append(slice_point)
            last_time = slice_point['time']

    return final_slices


def generate_conversation_summary(transcribed_segments, text_analysis):
    """
    [EMOJI]
    """
    print("[NOTE] [EMOJI]...")

    summary = {
        'conversation_overview': {
            'total_speakers': len(text_analysis['speaker_text_analysis']),
            'total_segments': text_analysis['total_segments'],
            'successful_segments': text_analysis['successful_transcriptions'],
            'success_rate': (text_analysis['successful_transcriptions'] / text_analysis['total_segments']) * 100,
            'total_words': text_analysis['total_words'],
            'questions_count': text_analysis['content_features']['questions_detected'],
            'average_words_per_segment': text_analysis['total_words'] / text_analysis['successful_transcriptions'] if
            text_analysis['successful_transcriptions'] > 0 else 0
        },
        'speaker_contributions': {},
        'conversation_flow': []
    }

    # [EMOJI]
    for speaker, stats in text_analysis['speaker_text_analysis'].items():
        success_rate = (stats['successful_count'] / stats['segment_count']) * 100 if stats['segment_count'] > 0 else 0
        summary['speaker_contributions'][speaker] = {
            'segment_count': stats['segment_count'],
            'successful_count': stats['successful_count'],
            'success_rate': success_rate,
            'word_count': stats['total_words'],
            'word_ratio': (stats['total_words'] / text_analysis['total_words']) * 100 if text_analysis[
                                                                                             'total_words'] > 0 else 0,
            'questions_asked': stats['content_types']['questions'],
            'average_segment_length': stats['average_words_per_segment']
        }

    # [EMOJI]
    successful_segments = [seg for seg in transcribed_segments if seg.get('confidence') == 'high']
    for i, segment in enumerate(successful_segments[:10]):  # [EMOJI]10[EMOJI]
        summary['conversation_flow'].append({
            'order': i + 1,
            'speaker': segment['speaker'],
            'time': segment['start_formatted'],
            'text_preview': segment['text'][:50] + "..." if len(segment['text']) > 50 else segment['text'],
            'word_count': segment['word_count'],
            'is_question': is_question(segment['text'])
        })

    return summary


def display_comprehensive_analysis(transcribed_segments, text_analysis, enhanced_slices, conversation_summary):
    """
    [EMOJI]
    """
    print("\n" + "=" * 70)
    print("[TARGET] [EMOJI]API[EMOJI]")
    print("=" * 70)

    # [EMOJI]
    overview = conversation_summary['conversation_overview']
    print(f"[STATS] [EMOJI]:")
    print(f"  • [EMOJI]: {overview['total_speakers']} [EMOJI]")
    print(f"  • [EMOJI]: {overview['total_segments']} [EMOJI]")
    print(f"  • [EMOJI]: {overview['successful_segments']} [EMOJI]")
    print(f"  • [EMOJI]: {overview['success_rate']:.1f}%")
    print(f"  • [EMOJI]: {overview['total_words']} [EMOJI]")
    print(f"  • [EMOJI]: {overview['questions_count']} [EMOJI]")
    print(f"  • [EMOJI]: {overview['average_words_per_segment']:.1f} [EMOJI]")

    # [EMOJI]
    print(f"\n[USERS] [EMOJI]:")
    for speaker, stats in conversation_summary['speaker_contributions'].items():
        print(f"  • {speaker}:")
        print(f"     [EMOJI]: {stats['segment_count']} [EMOJI]")
        print(f"     [EMOJI]: {stats['successful_count']} [EMOJI]")
        print(f"     [EMOJI]: {stats['success_rate']:.1f}%")
        print(f"     [EMOJI]: {stats['word_count']} [EMOJI]")
        print(f"     [EMOJI]: {stats['word_ratio']:.1f}%")
        print(f"     [EMOJI]: {stats['questions_asked']} [EMOJI]")
        print(f"     [EMOJI]: {stats['average_segment_length']:.1f} [EMOJI]")

    # [EMOJI]
    features = text_analysis['content_features']
    print(f"\n[UP] [EMOJI]:")
    print(f"  • [EMOJI]: {features['statements_detected']} [EMOJI]")
    print(f"  • [EMOJI]: {features['questions_detected']} [EMOJI]")
    print(f"  • [EMOJI](>50[EMOJI]): {features['long_segments']} [EMOJI]")
    print(f"  • [EMOJI](<10[EMOJI]): {features['short_segments']} [EMOJI]")

    # [EMOJI]
    print(f"\n[PROCESS] [EMOJI]:")
    for turn in conversation_summary['conversation_flow'][:6]:
        marker = "[Q]" if turn['is_question'] else "[MSG]"
        print(f"  {turn['order']:2d}. {turn['speaker']} {turn['time']} {marker}")
        print(f"      {turn['text_preview']}")

    # [EMOJI]
    print(f"\n[NOTE] [EMOJI] ([EMOJI]5[EMOJI]):")
    successful_segments = [seg for seg in transcribed_segments if seg.get('confidence') == 'high']
    for i, segment in enumerate(successful_segments[:5], 1):
        print(f"  {i}. {segment['speaker']} ({segment['start_formatted']}-{segment['end_formatted']}):")
        print(f"      {segment['text']}")

    # [EMOJI]
    print(f"\n[TARGET] [EMOJI]: {len(enhanced_slices)} [EMOJI]")
    for i, slice_point in enumerate(enhanced_slices[:8], 1):
        base_info = f" | [EMOJI]: {slice_point.get('based_on', '[EMOJI]')}" if 'based_on' in slice_point else ""
        print(f"  {i}. {format_time(slice_point['time'])} - {slice_point['type']}")
        print(f"      [EMOJI]: {slice_point['reason']}{base_info}")
        print(f"      [EMOJI]: {slice_point['confidence']}")


def save_final_analysis(audio_path, transcribed_segments, text_analysis, enhanced_slices, conversation_summary):
    """
    [EMOJI]
    """
    final_report = {
        'metadata': {
            'analysis_step': '[EMOJI]API[EMOJI]',
            'audio_file': os.path.basename(audio_path),
            'analysis_timestamp': '[EMOJI]',
            'recognition_engine': '[EMOJI]'
        },
        'conversation_summary': conversation_summary,
        'detailed_transcription': transcribed_segments,
        'text_analysis': text_analysis,
        'enhanced_slice_recommendations': enhanced_slices
    }

    output_file = audio_path.replace('.wav', '_complete_analysis.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)

    print(f"\n[SAVE] [EMOJI]: {output_file}")
    return output_file


def main():
    """[EMOJI]"""
    print("=" * 70)
    print("[TARGET] [EMOJI]API[EMOJI]")
    print("=" * 70)

    # [EMOJI] - [EMOJI]
    ALIYUN_CONFIG = {
        'ALIYUN_ACCESS_KEY_ID': os.getenv("ALIYUN_ACCESS_KEY_ID", ""),  # [EMOJI]AccessKey ID
        'ALIYUN_ACCESS_KEY_SECRET': os.getenv("ALIYUN_ACCESS_KEY_SECRET", ""),  # [EMOJI]AccessKey Secret
        'ALIYUN_APP_KEY': os.getenv("ALIYUN_APP_KEY", "")  # [EMOJI]AppKey
    }

    # [EMOJI]
    if (ALIYUN_CONFIG['ALIYUN_ACCESS_KEY_ID'].startswith('YOUR_') or
            ALIYUN_CONFIG['ALIYUN_ACCESS_KEY_SECRET'].startswith('YOUR_') or
            ALIYUN_CONFIG['ALIYUN_APP_KEY'].startswith('YOUR_')):
        print("[ERROR] [EMOJI]API[EMOJI]:")
        print("1. [EMOJI] https://ram.console.aliyun.com/users [EMOJI]AccessKey")
        print("2. [EMOJI] https://nls-portal.console.aliyun.com/ [EMOJI]AppKey")
        print("3. [EMOJI] ALIYUN_CONFIG [EMOJI]")
        return

    # [EMOJI]
    audio_path = r"../domo_professional.wav"

    if not os.path.exists(audio_path):
        print(f"[ERROR] [EMOJI]: {audio_path}")
        return

    print(f"[FILE] [EMOJI]: {audio_path}")

    # 1. [EMOJI]
    speaker_analysis = load_speaker_analysis(audio_path)
    if not speaker_analysis:
        return

    print("[OK] [EMOJI]")

    # 2. [EMOJI]API[EMOJI]
    transcribed_segments = professional_speech_transcription(audio_path, speaker_analysis, ALIYUN_CONFIG)

    if not transcribed_segments:
        print("[ERROR] [EMOJI]")
        return

    # 3. [EMOJI]
    text_analysis = analyze_text_content(transcribed_segments)

    # 4. [EMOJI]
    original_slices = speaker_analysis.get('slice_recommendations', [])
    enhanced_slices = enhance_slice_recommendations(original_slices, transcribed_segments, text_analysis)

    # 5. [EMOJI]
    conversation_summary = generate_conversation_summary(transcribed_segments, text_analysis)

    # 6. [EMOJI]
    display_comprehensive_analysis(transcribed_segments, text_analysis, enhanced_slices, conversation_summary)

    # 7. [EMOJI]
    output_file = save_final_analysis(audio_path, transcribed_segments, text_analysis, enhanced_slices,
                                      conversation_summary)

    print("\n" + "=" * 70)
    print("[DONE] [EMOJI]")
    print("[OK] [EMOJI]API[EMOJI]")
    print("[STATS] [EMOJI]")
    print("[TARGET] [EMOJI]")
    print(f"[SAVE] [EMOJI]: {output_file}")
    print("\n[GO] [EMOJI]")
    print("=" * 70)


if __name__ == "__main__":
    main()