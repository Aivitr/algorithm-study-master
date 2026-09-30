# syntax=docker/dockerfile:1
#
# ============================================================================
# 本地开发镜像（阶段 5）。**生产镜像与线上部署指令尚未编写**，见 deploy/docker.md。
#
# 为什么是单阶段
# --------------
# 本阶段的目标只有一句话：本地开发环境可复现（消除"重建 venv 结果不同"）。
# 生产镜像要的是别的东西——多阶段构建，把 gcc/cmake 留在 builder 层、
# 运行时只带 venv。那件事得等线上部署方案定下来（见 A24 代办项），
# 所以这里刻意**不预埋**一个没人验证过的 prod 阶段：写着不跑的阶段，
# 比不写更危险，因为它看起来是能用的。
#
# 一句话回顾镜像里跑什么：
#   server.py  →  FastAPI app  →  uvicorn（默认 8000）
# ============================================================================

FROM python:3.12-slim AS dev

# 与开发机 venv（Python 3.12.10）同一大版本。版本号写死是故意的：
# 镜像标签一旦漂移，本地能跑而容器不能跑这类问题会重新出现，
# 而容器化的全部意义就是消除它。

# ---------------------------------------------------------------------------
# 0. 可调参数
# ---------------------------------------------------------------------------

# pip 索引。默认走清华镜像——本项目的开发机本来就用它（见 CLAUDE.md 记忆
# 「python-and-pip-setup」），直连 PyPI 在这里会慢到不像话。
# 换个网络环境时覆盖：  docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple .
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# PyTorch 单独一套索引：CPU-only 轮子只在 pytorch.org 上，PyPI 上是 CUDA 版。
# 见 tools/split_requirements.py 文件头。
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
# 逐条都有来历，不是"顺手装一堆"：
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
RUN apt-get update \
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
# 依赖清单的唯一来源是 requirements.txt。这里不抄一份 torch 名单，
# 而是用 tools/split_requirements.py 现算（理由见该文件头）。
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

COPY requirements.txt tools/split_requirements.py /tmp/build/

# 层 A：torch 三件套，走 CPU 索引。
#
# 两个索引的顺序是有讲究的：主索引必须是 pytorch.org，否则 torch 会被
# 镜像里的 CUDA 版抢先命中（正是要避免的那件事）；而 torch 自己的纯 Python
# 依赖（sympy / networkx / jinja2 / fsspec 之类）pytorch.org 上不全，
# 得靠 --extra-index-url 回落到镜像。反过来的写法（镜像当主索引）看似更稳，
# 实际会把 CUDA 版装进来。
RUN python /tmp/build/split_requirements.py \
        /tmp/build/requirements.txt /tmp/req-heavy.txt /tmp/req-light.txt \
 && pip install --index-url "$TORCH_INDEX_URL" --extra-index-url "$PIP_INDEX_URL" \
        -r /tmp/req-heavy.txt

# 层 B：其余全部。必须在层 A 之后——insightface / pyannote.audio / resemblyzer
# 在安装期就要 import torch 来构建或校验。
#
# 这里刻意**不**跑 `pip check`：这套栈（funasr / insightface / pyannote 各自
# 钉住不同版本的 numpy、protobuf、onnx）本来就存在版本重叠，`pip check`
# 几乎必然报一堆，把它放进构建只会让构建红掉而问题依旧。它的输出单独看，
# 结论记在 deploy/docker.md。
RUN pip install -r /tmp/req-light.txt

# ---------------------------------------------------------------------------
# 3. 应用代码
# ---------------------------------------------------------------------------

WORKDIR /app
COPY . .

# 构建期冒烟：整条导入链跑一遍。
#
# 这一条不是仪式感。`app/core/database.py` 的 _ensure_transcripts_columns()
# 在**导入期**执行（"导入即为 DDL"），所以"能不能 import 成功"直接等于
# "这个镜像起来时会不会对库发 ALTER TABLE"。构建期没有 .env
# （见 .dockerignore），DATABASE_URL 取默认的 sqlite，因此这次冒烟
# **碰不到生产库**——它正是来证明这件事的。
#
# 用 python 而不是 uvicorn：这里只要导入成功，不要它监听端口。
RUN python -c "import server; print('import ok:', server.app.title or 'FastAPI')"

# ---------------------------------------------------------------------------
# 4. 运行
# ---------------------------------------------------------------------------
#
# 以 root 运行。**这是开发镜像的取舍，不是疏忽**：
#   * 仓库目录由 docker-compose 从 Windows 宿主挂载进来，
#     非 root 用户在这些文件上的可写性取决于 Docker Desktop 的映射策略，
#     失败起来是"存储写入被拒"这种很难一眼看穿的错。
#   * 生产镜像必须换成非 root，且要落到 k8s/systemd 的 user 上——
#     已记进 deploy/docker.md 的代办项。
#
# 注意端口 8000 是 server.py 的 __main__ 里写死的，与 APP_PORT 无关
# （settings.app.port 目前无调用点）。要改端口请在命令里显式 --port。

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/ -o /dev/null || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
