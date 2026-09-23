"""
FunASR [EMOJI]
[EMOJI] aliyun.py[EMOJI]

[EMOJI]
1. Docker[EMOJI]
2. [EMOJI]
"""

import os
import json
import subprocess
import shutil
from datetime import timedelta


class FunASRRecognizer:
    """FunASR[EMOJI]"""
    
    def __init__(self, mode="docker"):
        """
        [EMOJI]
        mode: "docker" [EMOJI]Docker[EMOJI], "local" [EMOJI]
        """
        self.mode = mode
        self.model = None
        self.host = "localhost"
        self.port = 10095
        
        if mode == "local":
            self._init_local_model()
    
    def _init_local_model(self):
        """[EMOJI]"""
        try:
            from funasr import AutoModel
            print("[PROCESS] [EMOJI]FunASR[EMOJI]...")
            self.model = AutoModel(
                model="paraformer-zh",
                vad_model="fsmn-vad",
                punc_model="ct-punc",
            )
            print("[OK] FunASR[EMOJI]")
        except ImportError:
            print("[ERROR] [EMOJI]funasr: pip install funasr modelscope torch torchaudio")
            raise
    
    def check_docker_service(self):
        """[EMOJI]Docker[EMOJI]"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((self.host, self.port))
            sock.close()
            return result == 0
        except:
            return False
    
    def recognize_audio_file(self, audio_file_path, sample_rate=16000):
        """[EMOJI]"""
        if self.mode == "local":
            return self._recognize_local(audio_file_path)
        else:
            return self._recognize_docker(audio_file_path)
    
    def _recognize_local(self, audio_path):
        """[EMOJI]"""
        try:
            if not self.model:
                self._init_local_model()
            
            result = self.model.generate(input=audio_path)
            if result and len(result) > 0:
                text = result[0].get('text', '')
                if text:
                    print(f"[OK] [EMOJI]: {text}")
                    return text
            return None
        except Exception as e:
            print(f"[ERROR] [EMOJI]: {e}")
            return None
    
    def _recognize_docker(self, audio_path):
        """[EMOJI]Docker[EMOJI]"""
        try:
            import websocket
            import wave
            import threading
            
            # [EMOJI]
            with wave.open(audio_path, 'rb') as wf:
                audio_data = wf.readframes(wf.getnframes())
            
            result_text = []
            is_final = threading.Event()
            
            def on_message(ws, message):
                try:
                    msg = json.loads(message)
                    if msg.get('text'):
                        result_text.append(msg['text'])
                    if msg.get('is_final', False):
                        is_final.set()
                except:
                    pass
            
            def on_error(ws, error):
                is_final.set()
            
            def on_close(ws, close_status, close_msg):
                is_final.set()
            
            def on_open(ws):
                config = {
                    "mode": "offline",
                    "chunk_size": [5, 10, 5],
                    "wav_name": os.path.basename(audio_path),
                    "is_speaking": True,
                    "itn": True,
                }
                ws.send(json.dumps(config))
                
                chunk_size = 9600
                for i in range(0, len(audio_data), chunk_size):
                    ws.send(audio_data[i:i+chunk_size], opcode=0x2)
                
                ws.send(json.dumps({"is_speaking": False}))
            
            ws = websocket.WebSocketApp(
                f"ws://{self.host}:{self.port}",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            ws_thread = threading.Thread(target=ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()
            
            is_final.wait(timeout=30)
            ws.close()
            
            text = ''.join(result_text).strip()
            if text:
                print(f"[OK] [EMOJI]: {text}")
                return text
            return None
            
        except Exception as e:
            print(f"[ERROR] Docker[EMOJI]: {e}")
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
    """[EMOJI]"""
    analysis_file = audio_path.replace('.wav', '_professional_diarization.json')
    
    if not os.path.exists(analysis_file):
        print(f"[ERROR] [EMOJI]: {analysis_file}")
        return None
    
    with open(analysis_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_audio_segment(audio_path, start_time, end_time, output_path):
    """[EMOJI]"""
    duration = end_time - start_time
    
    if duration < 0.5:
        print(f"⏩ [EMOJI]: {start_time:.2f}-{end_time:.2f} ({duration:.2f}s)")
        return False
    
    cmd = [
        'ffmpeg', '-i', audio_path,
        '-ss', str(start_time), '-t', str(duration),
        '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
        '-af', 'highpass=f=300,lowpass=f=3400',
        '-y', output_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"[OK] [EMOJI]: {format_time(start_time)}-{format_time(end_time)} ({file_size} bytes)")
            return True
        return False
    except Exception as e:
        print(f"[ERROR] [EMOJI]: {e}")
        return False


def professional_speech_transcription(audio_path, speaker_analysis, config=None):
    """[EMOJI]FunASR[EMOJI]"""
    print("[TARGET] [EMOJI]FunASR[EMOJI]...")
    
    if 'detailed_timeline' in speaker_analysis:
        speaker_segments = speaker_analysis['detailed_timeline']
    else:
        speaker_segments = speaker_analysis.get('segments', [])
    
    # [EMOJI]FunASR[EMOJI]
    recognizer = FunASRRecognizer(mode="local")
    
    transcribed_segments = []
    temp_dir = os.path.join(os.path.dirname(audio_path), "temp_segments")
    os.makedirs(temp_dir, exist_ok=True)
    
    total_segments = len(speaker_segments)
    success_count = 0
    
    print(f"[STATS] [EMOJI] {total_segments} [EMOJI]...")
    
    for i, speaker_seg in enumerate(speaker_segments, 1):
        start_time = speaker_seg['start']
        end_time = speaker_seg['end']
        duration = speaker_seg['duration']
        
        print(f"\n[ZOOM] [EMOJI] {i}/{total_segments}:")
        print(f"   [EMOJI]: {speaker_seg['speaker']}")
        print(f"   [EMOJI]: {speaker_seg['start_formatted']} - {speaker_seg['end_formatted']}")
        print(f"   [EMOJI]: {duration:.1f}[EMOJI]")
        
        temp_audio_path = os.path.join(temp_dir, f"segment_{i:04d}.wav")
        
        if extract_audio_segment(audio_path, start_time, end_time, temp_audio_path):
            recognized_text = recognizer.recognize_audio_file(temp_audio_path)
            
            if recognized_text and recognized_text.strip():
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
                    'recognition_source': 'funasr_local'
                }
                transcribed_segments.append(transcribed_segment)
                success_count += 1
                print(f"   [OK] [EMOJI]: {recognized_text}")
            else:
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
                    'recognition_source': 'funasr_failed'
                }
                transcribed_segments.append(transcribed_segment)
                print(f"   [ERROR] [EMOJI]")
        else:
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
    
    try:
        shutil.rmtree(temp_dir)
        print(f"[CLEAN] [EMOJI]")
    except:
        pass
    
    print(f"\n[STATS] [EMOJI]: {success_count}/{total_segments} [EMOJI]")
    
    return transcribed_segments


def analyze_text_content(transcribed_segments):
    """[EMOJI]"""
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
    
    for segment in transcribed_segments:
        speaker = segment['speaker']
        text = segment['text']
        word_count = segment['word_count']
        
        is_successful = (segment.get('confidence') == 'high' and
                        text not in ['[[EMOJI]]', '[[EMOJI]]'] and
                        word_count > 0)
        
        if is_successful:
            analysis['total_words'] += word_count
            analysis['successful_transcriptions'] += 1
        
        analysis['speaker_text_analysis'][speaker]['segment_count'] += 1
        if is_successful:
            analysis['speaker_text_analysis'][speaker]['total_words'] += word_count
            analysis['speaker_text_analysis'][speaker]['successful_count'] += 1
        analysis['speaker_text_analysis'][speaker]['segments'].append(segment)
        
        if is_successful:
            if is_question(text):
                analysis['content_features']['questions_detected'] += 1
                analysis['speaker_text_analysis'][speaker]['content_types']['questions'] += 1
            else:
                analysis['content_features']['statements_detected'] += 1
                analysis['speaker_text_analysis'][speaker]['content_types']['statements'] += 1
            
            if word_count > 50:
                analysis['content_features']['long_segments'] += 1
            elif word_count < 10:
                analysis['content_features']['short_segments'] += 1
    
    for speaker in speakers:
        stats = analysis['speaker_text_analysis'][speaker]
        if stats['successful_count'] > 0:
            stats['average_words_per_segment'] = stats['total_words'] / stats['successful_count']
    
    return analysis


def is_question(text):
    """[EMOJI]"""
    if not text or text in ['[[EMOJI]]', '[[EMOJI]]']:
        return False
    
    question_indicators = ['[EMOJI]', '?', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', 
                          '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]', '[EMOJI]']
    return any(indicator in text for indicator in question_indicators)


def save_final_analysis(audio_path, transcribed_segments, text_analysis, conversation_summary):
    """[EMOJI]"""
    final_report = {
        'metadata': {
            'analysis_step': '[EMOJI]FunASR[EMOJI]',
            'audio_file': os.path.basename(audio_path),
            'recognition_engine': 'FunASR (Paraformer)'
        },
        'conversation_summary': conversation_summary,
        'detailed_transcription': transcribed_segments,
        'text_analysis': text_analysis
    }
    
    output_file = audio_path.replace('.wav', '_complete_analysis.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)
    
    print(f"\n[SAVE] [EMOJI]: {output_file}")
    return output_file


def main():
    """[EMOJI]"""
    print("=" * 70)
    print("[TARGET] [EMOJI]FunASR[EMOJI]")
    print("=" * 70)
    
    audio_path = r"../domo_professional.wav"
    
    if not os.path.exists(audio_path):
        print(f"[ERROR] [EMOJI]: {audio_path}")
        return
    
    print(f"[FILE] [EMOJI]: {audio_path}")
    
    speaker_analysis = load_speaker_analysis(audio_path)
    if not speaker_analysis:
        return
    
    print("[OK] [EMOJI]")
    
    transcribed_segments = professional_speech_transcription(audio_path, speaker_analysis)
    
    if not transcribed_segments:
        print("[ERROR] [EMOJI]")
        return
    
    text_analysis = analyze_text_content(transcribed_segments)
    
    # [EMOJI]
    conversation_summary = {
        'total_segments': text_analysis['total_segments'],
        'successful_segments': text_analysis['successful_transcriptions'],
        'total_words': text_analysis['total_words']
    }
    
    save_final_analysis(audio_path, transcribed_segments, text_analysis, conversation_summary)
    
    print("\n" + "=" * 70)
    print("[DONE] [EMOJI]FunASR[EMOJI]")
    print("=" * 70)


if __name__ == "__main__":
    main()
