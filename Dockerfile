# syntax=docker/dockerfile:1
#
# ============================================================================
# 本地开发镜像。
#
# 镜像里跑什么：
#   server.py  →  FastAPI app  →  uvicorn（默认 8000）
# ============================================================================

ARG UV_VERSION=0.13.8

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:3.12-slim AS dev

# 与开发机 venv 同一大版本（Python 3.12）；版本号写死，不要改。

# ---------------------------------------------------------------------------
# 0. 可调参数
# ---------------------------------------------------------------------------

# uv 索引，默认清华镜像。换个网络环境时覆盖：
#   docker build --build-arg UV_INDEX_URL=https://pypi.org/simple .
ARG UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG DEBIAN_MIRROR=http://deb.debian.org/debian

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_CONCURRENT_BUILDS=2 \
    UV_INDEX_URL=${UV_INDEX_URL} \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai

# uv 官方静态二进制；不在镜像里再装一遍 pip。
COPY --from=uv /uv /uvx /bin/

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
# 2. Python 依赖（uv + uv.lock）
# ---------------------------------------------------------------------------
#
# 先只拷依赖清单并同步，代码放在最后一层：改代码不会重装 torch。
# venv 放 /opt/venv 而**不是** /app/venv：docker-compose 会把仓库目录
# 挂载到 /app，那样一来 /app 下的任何东西都会被宿主目录盖掉。
#
# `--frozen` 禁止解析新版本，构建结果由 uv.lock 唯一决定。
# `--group dev` 安装 pytest/httpx（开发镜像需要）；运行镜像可去掉。
# `cython<4` 已在 pyproject 的运行时依赖里，insightface 构建期需要它。
#
# shortcut: GPU 构建仍依赖旧的 TORCH_INDEX_URL 流程；uv.lock 冻结的是 CPU
# 轮子，需要 GPU 时单独加 lock/index，不要直接改这里的 CPU index。

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-progress --no-install-project --group dev \
 && rm -rf /root/.cache/uv
ENV PATH="/opt/venv/bin:$PATH"

# ---------------------------------------------------------------------------
# 3. 应用代码
# ---------------------------------------------------------------------------

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
