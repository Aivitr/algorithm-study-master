1是独立示例/旧版脚本，未被 server.py 接线，只把该目录加入了 sys.path（server.py:22），并未 import 或 subprocess 启动其中任何脚本。

实时 ASR （边接收音频流，边持续输出文字）走的是阿里云 NLS ai_core.RealtimeTranscriber + server.ASRSessionManager + /ws-asr + 前端 这条完整链路；1/ 目录的 service_aliyun.py 等是未被引用的旧版/示例。

文件介绍：

1\aliyun.py	离线一次性识别。
AliyunSpeechRecognizer（14 行）用 REST 取 token + HTTP POST 到 .../stream/v1/asr（94 行）逐段识别音频；main()（599 行）里硬编码密钥（606-609 行）。另含 ffmpeg 切段、说话人分析、切片推荐等辅助函数

1\service_aliyun.py	流式识别子进程服务。
AliyunService（22 行）用 WebSocket SpeechTranscriber（StartTranscription/SentenceEnd/StopTranscription，95/124 行）；main()（155 行）实现 SYSTEM_READY/读路径/`TEXT

1\service_funasr.py	FunASR 版子进程服务（同协议），非阿里云 NLS，走本地 FunASR Docker

1\funasr_recognizer.py	FunASRRecognizer（17 行），Docker/本地两种模式，非阿里云 NLS

1\service_speaker.py	pyannote 说话人分离子进程服务，硬编码 HF_TOKEN（14 行），非阿里云 ASR

1\speaker.py	pyannote 说话人分离辅助函数，独立脚本

1\extract.py	ffmpeg 从视频提取音频，独立脚本

1\video.py	读取 _complete_analysis.json 生成最终视频，独立脚本

1\test.py	环境检查（torch/pyannote/whisper/moviepy），独立脚本