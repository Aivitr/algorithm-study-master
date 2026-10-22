# syntax=docker/dockerfile:1
#
# ============================================================================
# 本地开发镜像。
#
# 镜像里跑什么：
#   server.py  →  FastAPI app  →  uvicorn（默认 8000）
# ============================================================================

FROM python:3.12-slim AS dev

# 与开发机 venv 同一大版本（Python 3.12）；版本号写死，不要改。

# ---------------------------------------------------------------------------
# 0. 可调参数
# ---------------------------------------------------------------------------

# pip 索引，默认清华镜像。换个网络环境时覆盖：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple .
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG DEBIAN_MIRROR=http://deb.debian.org/debian

# PyTorch 单独一套索引：CPU-only 轮子只在 pytorch.org 上，PyPI 上是 CUDA 版。
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai

# ---------------------------------------------------------------------------
# 1. 系统依赖
# ---------------------------------------------------------------------------
#
# 逐条都要，不是"顺手装一堆"：
#
#   ffmpeg                  视频分片与音频解码（scenedetect / librosa / funasr）
#   libgl1, libglib2.0-0    opencv-python 在导入期 dlopen 的 libGL.so.1 /
#                           libgthread-2.0.so.0。缺它是 `import cv2` 直接失败，
#                           而 cv2 在 server.py 顶上就导入了 —— 起不来。
#   libsm6 libxext6 libxrender1  opencv / mediapipe 的 X11 运行库
#   libsndfile1             soundfile 后端（librosa 读写 wav 走它）
#   libgomp1                torch 与 onnxruntime 的 OpenMP 运行时
#   build-essential cmake python3-dev
#                           insightface 2.0 与 webrtcvad 2.0.10 都**没有**
#                           Linux 轮子，必须现场编译；insightface 还要 cmake。
#                           cython 同理（下面单独装）。
#   git                     funasr / modelscope 的少数依赖从 git 拉取
#   curl                    healthcheck 与进容器排障
#   tzdata                  TZ=Asia/Shanghai 要它才有意义
#
# 用 `--no-install-recommends` 是常规操作，砍掉字体、文档之类几百 MB。
RUN sed -i "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libsndfile1 \
        libgomp1 \
        build-essential \
        cmake \
        python3-dev \
        git \
        curl \
        tzdata \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 2. Python 依赖（分三层，为的是让改代码不必重装依赖）
# ---------------------------------------------------------------------------
#
# 三层的顺序即缓存粒度，从"几乎不变"到"常变"：
#   层 A  torch 三件套  —— 几百 MB，几乎不动
#   层 B  其余依赖
#   层 C  代码          —— 每次改动都变，所以放最后
#
# 依赖清单的唯一来源是 requirements-dev.txt（开发镜像，测试工具也要有；
# 它的首行是 `-r requirements.txt`）。这里既不抄一份 torch 名单，也不抄一份
# pytest/httpx —— 都由 tools/split_requirements.py 现算，它会跟随 `-r` 引用
# 把被引用的清单展开进来。
#
# venv 放 /opt/venv 而**不是** /app/venv：docker-compose 会把仓库目录
# 挂载到 /app，那样一来 /app 下的任何东西都会被宿主目录盖掉，
# 包括刚装好的依赖。这是容器化里最常见的"装了却找不到"。

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# cython 先装：insightface 的 setup.py 在 build 期 import 它
RUN pip install --index-url "$PIP_INDEX_URL" "cython<4"

# ARG 的可见范围到 stage 末尾，但 ENV 会一直传到运行时；这里写进 ENV，
# 后续的 pip 就都不用再重复 --index-url。
ENV PIP_INDEX_URL="$PIP_INDEX_URL"

# 两份清单都要 COPY：requirements-dev.txt 靠 `-r requirements.txt` 引用后者，
# 只拷一份的话展开会失败（而它失败的方式是**警告后跳过**，于是 torch 静默消失）。
COPY requirements.txt requirements-dev.txt tools/split_requirements.py /tmp/build/

# 层 A：torch 三件套，走 CPU 索引。
#
# 主索引必须是 pytorch.org，否则 torch 会被镜像里的 CUDA 版抢先命中；
# torch 自己的纯 Python 依赖（sympy / networkx / jinja2 / fsspec 之类）
# pypi 镜像上不全，得靠 --extra-index-url 回落。
RUN python /tmp/build/split_requirements.py \
        /tmp/build/requirements-dev.txt /tmp/req-heavy.txt /tmp/req-light.txt \
 && test -s /tmp/req-heavy.txt \
 && pip install --index-url "$TORCH_INDEX_URL" --extra-index-url "$PIP_INDEX_URL" \
        -r /tmp/req-heavy.txt

# 层 B：其余全部。必须在层 A 之后——insightface / pyannote.audio / resemblyzer
# 在安装期就要 import torch 来构建或校验。
#
# 刻意**不**跑 `pip check`：这套栈存在版本重叠（funasr / insightface / pyannote
# 各自钉住不同版本的 numpy、protobuf、onnx），它会一直报一堆。
RUN pip install -r /tmp/req-light.txt

# ---------------------------------------------------------------------------
# 3. 应用代码
# ---------------------------------------------------------------------------

WORKDIR /app
COPY . .

# 构建期冒烟：整条导入链跑一遍。
#
# `app/core/database.py` 的 _ensure_transcripts_columns() 在**导入期**执行
# （"导入即为 DDL"），所以"能不能 import 成功"等于"这个镜像起来时会不会对库
# 发 ALTER TABLE"。构建期没有 .env（见 .dockerignore），DATABASE_URL 取默认的
# sqlite，因此这次冒烟**碰不到生产库**。
#
# LLM_API_KEY 给的是**假值**，这是必须的：app/services/llm_service.py 在模块级
# 构造 `llm = LLMService()`，而它的 __init__ 会 `OpenAI(api_key=...)`，空 key
# 直接抛 OpenAIError —— **服务没有 LLM 凭据连导入都过不去**。所以 `.env` 里必须
# 有非空的 LLM_API_KEY，否则容器起不来。
#
# 假值在这里是安全的：本步只 import，不发任何请求。
#
# 用 python 而不是 uvicorn：这里只要导入成功，不要它监听端口。
RUN LLM_API_KEY=build-smoke-not-a-real-key \
    python -c "import server; print('import ok:', server.app.title or 'FastAPI')"

# ---------------------------------------------------------------------------
# 4. 运行
# ---------------------------------------------------------------------------
#
# 以 root 运行：这是开发镜像的取舍。生产镜像必须换成非 root。
#
# 端口 8000 是 server.py 的 __main__ 里写死的，与 APP_PORT 无关
# （settings.app.port 目前无调用点）。要改端口请在命令里显式 --port。

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/ -o /dev/null || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
