"""
FunASR [EMOJI]
[EMOJI]NLS API[EMOJI]
GitHub: https://github.com/modelscope/FunASR

[EMOJI]
1. Docker[EMOJI]:
   docker pull registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.10
   docker run -p 10095:10095 -it registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.10

2. GPU[EMOJI]:
   docker pull registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-gpu-0.1.10
   docker run --gpus all -p 10095:10095 -it registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-gpu-0.1.10
"""

import sys
import os
import json
import time
import wave
import websocket
import threading

sys.stdout.reconfigure(encoding='utf-8')

# FunASR[EMOJI]
FUNASR_CONFIG = {
    'HOST': 'localhost',      # FunASR[EMOJI]
    'PORT': 10095,            # FunASR[EMOJI]
    'MODE': 'offline',        # offline=[EMOJI]([EMOJI]), online=[EMOJI]([EMOJI])
    'CHUNK_SIZE': [5, 10, 5], # [EMOJI] [5,10,5] = 600ms
    'HOTWORDS': '',           # [EMOJI]
}


class FunASRService:
    """FunASR[EMOJI]"""
    
    def __init__(self):
        self.ws_url = f"ws://{FUNASR_CONFIG['HOST']}:{FUNASR_CONFIG['PORT']}"
        self.connected = False
        
    def check_service(self):
        """[EMOJI]FunASR[EMOJI]"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((FUNASR_CONFIG['HOST'], FUNASR_CONFIG['PORT']))
            sock.close()
            return result == 0
        except:
            return False
    
    def recognize_file(self, audio_path):
        """[EMOJI]"""
        if not os.path.exists(audio_path):
            return None
            
        try:
            # [EMOJI]
            with wave.open(audio_path, 'rb') as wf:
                audio_data = wf.readframes(wf.getnframes())
                sample_rate = wf.getframerate()
            
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
                print(f"WebSocket[EMOJI]: {error}", file=sys.stderr)
                is_final.set()
            
            def on_close(ws, close_status, close_msg):
                is_final.set()
            
            def on_open(ws):
                # [EMOJI]
                config = {
                    "mode": FUNASR_CONFIG['MODE'],
                    "chunk_size": FUNASR_CONFIG['CHUNK_SIZE'],
                    "wav_name": os.path.basename(audio_path),
                    "is_speaking": True,
                    "hotwords": FUNASR_CONFIG['HOTWORDS'],
                    "itn": True,  # [EMOJI]
                }
                ws.send(json.dumps(config))
                
                # [EMOJI]
                chunk_size = 9600  # [EMOJI]
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i+chunk_size]
                    ws.send(chunk, opcode=websocket.ABNF.OPCODE_BINARY)
                    time.sleep(0.01)  # [EMOJI]
                
                # [EMOJI]
                ws.send(json.dumps({"is_speaking": False}))
            
            # [EMOJI]WebSocket[EMOJI]
            ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            # [EMOJI]
            ws_thread = threading.Thread(target=ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()
            
            # [EMOJI]30[EMOJI]
            is_final.wait(timeout=30)
            ws.close()
            
            # [EMOJI]
            final_text = ''.join(result_text).strip()
            return final_text if final_text else None
            
        except Exception as e:
            print(f"[EMOJI]: {e}", file=sys.stderr)
            return None
    
    def recognize_file_simple(self, audio_path):
        """
        [EMOJI]funasr[EMOJI]
        [EMOJI]: pip install funasr modelscope
        """
        try:
            from funasr import AutoModel
            
            # [EMOJI]Paraformer[EMOJI]
            model = AutoModel(
                model="paraformer-zh",  # [EMOJI]
                vad_model="fsmn-vad",   # [EMOJI]
                punc_model="ct-punc",   # [EMOJI]
                spk_model="cam++",      # [EMOJI]
            )
            
            result = model.generate(input=audio_path)
            if result and len(result) > 0:
                return result[0].get('text', '')
            return None
            
        except ImportError:
            print("[EMOJI]funasr: pip install funasr modelscope", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[EMOJI]: {e}", file=sys.stderr)
            return None


def main():
    """[EMOJI] - [EMOJI]service_aliyun.py[EMOJI]"""
    service = FunASRService()
    
    # [EMOJI]
    if service.check_service():
        print("SYSTEM_READY", flush=True)
    else:
        print("SYSTEM_WARNING|FunASR[EMOJI]", flush=True)
        print("[EMOJI]: [EMOJI]FunASR Docker[EMOJI]", flush=True)
        print("SYSTEM_READY", flush=True)  # [EMOJI]
    
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        
        audio_path = line.strip()
        if not audio_path:
            continue
        
        try:
            # [EMOJI]WebSocket[EMOJI]
            if service.check_service():
                text = service.recognize_file(audio_path)
            else:
                # [EMOJI]
                text = service.recognize_file_simple(audio_path)
            
            if text:
                print(f"TEXT|{text}", flush=True)
            else:
                print("TEXT|", flush=True)
                
        except Exception as e:
            print(f"TASK_ERROR|{e}", flush=True)
            print("TEXT|", flush=True)


if __name__ == "__main__":
    main()
