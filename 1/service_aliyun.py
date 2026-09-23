import sys
import os
import json
import time
import uuid
import base64
import hmac
import hashlib
import requests
import websocket
import threading

sys.stdout.reconfigure(encoding='utf-8')

ALIYUN_CONFIG = {
    'ACCESS_KEY_ID': os.getenv("ALIYUN_ACCESS_KEY_ID", ""),
    'ACCESS_KEY_SECRET': os.getenv("ALIYUN_ACCESS_KEY_SECRET", ""),
    'APP_KEY': os.getenv("ALIYUN_APP_KEY", "")
}


class AliyunService:
    def __init__(self):
        self.token = None
        self.expire = 0

    def refresh_token(self):
        # [EMOJI]
        if self.token and time.time() < self.expire - 60: return

        try:
            # print(">> [Aliyun] [EMOJI] Token...", flush=True)
            client_id = ALIYUN_CONFIG['ACCESS_KEY_ID']
            client_secret = ALIYUN_CONFIG['ACCESS_KEY_SECRET']
            params = {
                "Action": "CreateToken", "Format": "JSON", "Version": "2019-02-28",
                "AccessKeyId": client_id, "SignatureMethod": "HMAC-SHA1",
                "SignatureVersion": "1.0", "SignatureNonce": str(uuid.uuid4()),
                "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            import urllib.parse
            sorted_params = sorted(params.items())
            qs = "&".join(
                [f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}" for k, v in sorted_params])
            string_to_sign = 'GET&%2F&' + urllib.parse.quote(qs, safe='')
            key = client_secret + '&'
            sign = base64.b64encode(hmac.new(key.encode(), string_to_sign.encode(), hashlib.sha1).digest()).decode()
            params['Signature'] = sign

            resp = requests.get("https://nls-meta.cn-shanghai.aliyuncs.com/", params=params, timeout=5)
            d = resp.json()
            if 'Token' in d:
                self.token = d['Token']['Id']
                self.expire = d['Token']['ExpireTime']
        except Exception as e:
            print(f"SYSTEM_ERROR|{e}", flush=True)

    def run(self, audio_path):
        self.refresh_token()
        if not self.token: return None

        # [EMOJI]WebSocket URL
        ws_url = f"wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1?token={self.token}"

        result_text = []
        is_complete = threading.Event()

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                # [EMOJI]
                if msg.get('header', {}).get('name') == 'SentenceEnd':
                    text = msg.get('payload', {}).get('result')
                    if text:
                        result_text.append(text)
                # [EMOJI]
                elif msg.get('header', {}).get('name') == 'TranscriptionResultChanged':
                    pass  # [EMOJI]
            except:
                pass

        def on_error(ws, error):
            is_complete.set()

        def on_close(ws, close_status, close_msg):
            is_complete.set()

        def on_open(ws):
            try:
                # [EMOJI]
                start_msg = {
                    "header": {
                        "message_id": str(uuid.uuid4()),
                        "task_id": str(uuid.uuid4()),
                        "namespace": "SpeechTranscriber",
                        "name": "StartTranscription",
                        "appkey": ALIYUN_CONFIG['APP_KEY']
                    },
                    "payload": {
                        "format": "pcm",
                        "sample_rate": 16000,
                        "enable_intermediate_result": False,
                        "enable_punctuation_prediction": True,
                        "enable_inverse_text_normalization": True
                    }
                }
                ws.send(json.dumps(start_msg))

                # [EMOJI]
                with open(audio_path, 'rb') as f:
                    audio_data = f.read()

                chunk_size = 3200  # 200ms[EMOJI]
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i+chunk_size]
                    ws.send(chunk, opcode=websocket.ABNF.OPCODE_BINARY)
                    time.sleep(0.01)

                # [EMOJI]
                stop_msg = {
                    "header": {
                        "message_id": str(uuid.uuid4()),
                        "task_id": start_msg["header"]["task_id"],
                        "namespace": "SpeechTranscriber",
                        "name": "StopTranscription",
                        "appkey": ALIYUN_CONFIG['APP_KEY']
                    }
                }
                ws.send(json.dumps(stop_msg))
            except Exception as e:
                is_complete.set()

        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws_thread = threading.Thread(target=ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()

            # [EMOJI]20[EMOJI]
            is_complete.wait(timeout=20)
            ws.close()

            return ''.join(result_text) if result_text else None
        except:
            return None


def main():
    service = AliyunService()
    # [EMOJI] Token [EMOJI]
    service.refresh_token()
    if service.token:
        print("SYSTEM_READY", flush=True)
    else:
        print("SYSTEM_ERROR|[EMOJI]", flush=True)
        return

    while True:
        line = sys.stdin.readline()
        if not line: break

        audio_path = line.strip()
        if not audio_path: continue

        try:
            text = service.run(audio_path)
            # [EMOJI]: TEXT|[EMOJI]
            if text:
                print(f"TEXT|{text}", flush=True)
            else:
                print("TEXT|", flush=True)  # [EMOJI]
        except Exception as e:
            print(f"TASK_ERROR|{e}", flush=True)
            print("TEXT|", flush=True)


if __name__ == "__main__":
    main()