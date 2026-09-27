# 智能协作学习系统（Smart Collaborative Learning System）

一个面向课堂的实时协作学习平台：教师建课生成教学设计 → 学生用班级码加入 → 课堂内实时字幕 / 表情 / 声纹分析 → 课后 AI 生成学习报告与练习。

后端是**单文件 FastAPI 应用**（`server.py`，6500+ 行），前端是**单文件 SPA**（`index.html`，约 1.1 万行），数据落在 **SQL Server（MSSQL）**。

> **本文档的定位**
> 本文件是**唯一以当前代码为准**的项目说明，其中的版本号、路径、连接串、行为都已在本机实测。
> 仓库根目录的 `README.md`、`DEPLOYMENT.md`、`功能介绍文档.md` 描述的是**早期的 MySQL 版本**，与现有代码不符 —— 详见 [§10 文档现状](#10-文档现状哪些旧文档不可信)。

---

## 目录

1. [技术栈](#1-技术栈实测版本)
2. [目录结构](#2-目录结构)
3. [快速开始](#3-快速开始本地)
4. [数据库](#4-数据库重点)
5. [配置项](#5-配置项)
6. [接口概览](#6-接口概览)
7. [前端](#7-前端)
8. [部署](#8-部署)
9. [已知限制与安全](#9-已知限制与安全默认值不等于安全)
10. [文档现状](#10-文档现状哪些旧文档不可信)
11. [故障排查](#11-故障排查)
12. [维护约定](#12-维护约定)

---

## 1. 技术栈（实测版本）

| 组件 | 版本 / 说明 |
| --- | --- |
| Python | **>= 3.11**（下限来自 SQLAlchemy）。本机实测 3.12.10 |
| FastAPI | 0.141.1 |
| Uvicorn | 0.54.0 |
| SQLAlchemy | 2.1.1（`NullPool`，无连接池） |
| pymssql | 2.4.2（MSSQL 驱动，经 FreeTDS） |
| openai | 3.19.2（用于调用 DeepSeek 的 OpenAI 兼容接口） |
| setuptools | **< 81**（硬约束，见 [§11](#11-故障排查)） |
| 数据库 | **SQL Server / MSSQL (T-SQL)** —— 本地 Docker `smartclass-mssql`（3433），线上阿里云 RDS SQL Server |
| 实时音视频 | Agora RTC（`appid` 模式，服务端不签发 token） |
| 语音识别 | 阿里云 NLS 一句话识别 |
| 大模型 | DeepSeek（`deepseek-chat`） |
| 对象存储 | 阿里云 OSS（媒体证据上传；未配置时上传线程报错并保留本地路径，见 [§5](#5-配置项)） |
| 前端 | 原生 JS 单页应用，无构建步骤 |

研究增强模块（说话人分离 / 声纹 / 跨模态融合等）在 `research_*.py` 中，**默认关闭**，需要额外 6 份模型权重，见 `deploy/smartclass1.env.example` 的 `RESEARCH_*` 段。

---

## 2. 目录结构

```
.
├── server.py                 # 全部后端：56 个 HTTP 路由 + 3 个 WebSocket + 业务逻辑
├── index.html                # 全部前端：登录/教师工作台/学生学习中心/课堂，单文件 SPA
├── pcm-processor.js          # AudioWorklet，把麦克风 PCM 送给 WebSocket
├── database.py               # ORM 模型（15 张表）+ engine/session，唯一的建表依据
├── config.py                 # 读取 .env 与环境变量，构造 settings 对象
├── init_db.py                # 建表入口：只调用 Base.metadata.create_all()
├── llm_service.py            # DeepSeek 调用封装（含流式）
├── ai_core.py                # 教学设计与知识图谱的提示词/解析
├── knowledge_graph_service.py
├── voiceprint_*.py           # 声纹注册/识别
├── aliyun_*.py               # NLS 语音识别、表情识别、说话人分离
├── oss_utils.py / oss_config.py
├── video_processor.py        # 视频抽帧、音频提取（依赖 ffmpeg）
├── research_*.py             # 研究增强模块（默认关闭）
├── storage/                  # 运行时数据（.gitignore 已忽略，通过 /storage 静态挂载）
├── deploy/                   # 生产部署：nginx / systemd / env 模板 / 一键脚本
├── tests/  test/             # pytest 用例 与 手工诊断脚本（两套并存，见 §10）
└── .env                      # 本地密钥（.gitignore 已忽略，切勿提交）
```

启动脚本与一次性诊断脚本（`check_*.py`、`fix_db_final.py`、`update_backend.py`、`remove_all_emojis.py` 等）散落在根目录，属于历史产物，不要当成主流程入口。

---

## 3. 快速开始（本地）

### 3.1 安装依赖

```bash
python -m venv venv

# Windows
venv/Scripts/python.exe -m pip install -r requirements.txt
# Linux / macOS
venv/bin/python -m pip install -r requirements.txt
```

`requirements.txt` 里包含 `torch` / `transformers` / `pyannote.audio` 等重型依赖，完整安装体积很大。**只做后端联调**时可以只装最小集：

```bash
pip install fastapi "uvicorn[standard]" sqlalchemy pymssql python-multipart \
            openai requests aiohttp websockets websocket-client "setuptools<81"
```

国内网络建议追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

### 3.2 配置 `.env`

```bash
cp .env.example .env
```

至少要填 `DATABASE_URL`（见 [§4](#4-数据库重点)）。`LLM_API_KEY` 留空时 AI 相关功能会降级/报错，但注册、登录、建课、加入课堂不受影响。

### 3.3 建表

```bash
venv/Scripts/python.exe init_db.py      # Windows
venv/bin/python init_db.py              # Linux
```

`init_db.py` 是幂等的（`create_all` 不会改动已存在的表），可以反复执行。表结构的唯一来源是 `database.py` 中的 ORM 模型。

### 3.4 启动

```bash
venv/Scripts/python.exe server.py       # Windows
venv/bin/python server.py               # Linux
```

访问 <http://127.0.0.1:8000>。

> **必须从项目根目录启动。** `index.html`（`open("index.html")`）、`pcm-processor.js`（`FileResponse`）和 `storage/`（`app.mount("/storage", StaticFiles(directory="storage"))`）都是**相对当前工作目录**的路径，换目录启动会 404 / 500。

生产环境用 `uvicorn` 直接托管在 8000 端口，前面由 nginx 反代（见 [§8](#8-部署)）。

### 3.5 没有 MSSQL 时用 SQLite

`DATABASE_URL` 留空即回退到 `sqlite:///./storage/app.db`。**这条回退路径已在本次修复中实测可用**（建表 15 张 → 注册 → 登录 → 中文用户名原样取回）。

SQLite 只适合本机跑通流程，不要用于生产：代码里有 `IDENTITY` / `GETDATE` / `TOP` 等 T-SQL 专有写法与 MSSQL 专有的补列 DDL（`database.py::_ensure_transcripts_columns`，非 MSSQL 方言下会跳过）。

### 3.6 最小可跑通链路

不配置任何第三方 key 也能走到这一步：

```
教师注册 → 教师登录 → 教师工作台 → 建课（填中文主题，生成班级码）
        → 学生注册 → 学生登录 → 学生学习中心 → 输入班级码加入 → 进入同一课堂
```

需要 Agora App ID 才有音视频，需要阿里云 NLS 才有实时字幕。

---

## 4. 数据库（重点）

### 4.1 为什么是 MSSQL 而不是 MySQL

旧文档写的是 MySQL，这是**错的**，照抄会连不上：

- 全仓库没有任何一处 `import pymysql`（`grep -rn pymysql --include=*.py` 结果为空）。
- `database.py` 显式 `from sqlalchemy.dialects.mssql import NVARCHAR`，并对 `transcripts` / `exercises` 使用该类型。
- 代码里有 `IDENTITY` / `GETDATE()` / `SELECT TOP 1` 等 T-SQL 专有写法。
- 本地开发库是 Docker 容器 `smartclass-mssql`，线上是阿里云 RDS SQL Server（默认端口 **3433**，不是 1433）。

`pymssql` 只是 SQLAlchemy 的 MSSQL 驱动，它**不是** MySQL 驱动。

### 4.2 连接串格式

```
mssql+pymssql://<user>:<password>@<host>:3433/<database>?charset=utf8
```

- 应用（`server.py` / `init_db.py` / `database.py`）**只读 `DATABASE_URL` 这一个变量**。
- `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` 那 5 个变量只被历史诊断脚本（`check_*.py`）读取。**不要**只配 `DB_*` 而不配 `DATABASE_URL` —— 那正是旧部署模板里"服务能起、注册登录全废"的原因（本次已把两个鉴权接口改为走 ORM，这个坑已消除）。

### 4.3 `charset` 必须是 `utf8` —— 中文乱码的根因

`pymssql` 底层是 FreeTDS，**FreeTDS 不对 `varchar` 列做代码页转换**，而 `varchar` 的编码由数据库排序规则决定（`Chinese_PRC_CI_AS` 即 GBK 代码页）。两种 `charset` 的实测结果：

| 列类型 | `charset=utf8` | `charset=cp936` |
| --- | --- | --- |
| `varchar` | 写入正确，**读出来是乱码** | 读取正常，**写入被二次编码，不可逆损坏**（中文变 `?`） |
| `nvarchar` | **读、写全部正确** | 读、写均不正确 |

结论：**唯一正确的组合是 `charset=utf8` + `NVARCHAR`**。

因此：

- `.env` / 部署 env 里的 `charset` **永远保持 `utf8`**。曾有人为了"修乱码"改成 `cp936`，结果是写入侧被静默破坏 —— 不可逆，且故障延后到读取时才暴露。
- `database.py` 中所有存放中文的列使用 SQLAlchemy 的 `Unicode` / `UnicodeText`：在 MSSQL 上生成 `NVARCHAR` / `NVARCHAR(MAX)`，在 SQLite 上生成 `TEXT`，两种方言都能正确存取中文。**不要改回 `String` / `Text`**（那会在 MSSQL 上生成 `varchar`）。
- 存量库中 26 个 `varchar` / `text` 中文列已迁移为 `NVARCHAR`；`transcripts` / `exercises` 用显式的 `NVARCHAR(n)` 是为了控制长度上限。

### 4.4 建库时的排序规则

新建库必须指定中文排序规则，否则 `varchar` 列存不了中文（即使有上述 `NVARCHAR` 约定，历史脚本仍可能建出 `varchar`）：

```sql
CREATE DATABASE smartclass COLLATE Chinese_PRC_CI_AS;
```

### 4.5 表结构

15 张表，全部由 `database.py` 的 ORM 定义：

`users`、`meetings`、`transcripts`、`emotion_logs`、`ai_insights`、`knowledge_graphs`、`graph_nodes`、`graph_edges`、`learning_reports`、`exercises`、`student_answers`、`mental_health_assessments`、`viewpoint_votes`、`member_connections`、`report_templates`

约定：

- 时间戳由 `Column(default=datetime.now)` 在 Python 侧生成，**不依赖 `GETDATE()`**，因此 SQLite 回退同样可用。
- 项目**没有使用 Alembic**。结构变更靠 `create_all`（只建不改）+ 手工 `ALTER TABLE` 补丁，例如 `database.py::_ensure_transcripts_columns()` 会为老库补上 5 个研究字段列。

---

## 5. 配置项

完整清单见 `.env.example`（本地）与 `deploy/smartclass1.env.example`（生产）。

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | **是** | 见 §4.2；留空回退 SQLite |
| `LLM_API_KEY` | AI 功能必填 | DeepSeek key。留空时建课、报告、AI 助教不可用 |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` | 否 | 默认 `deepseek` / `deepseek-chat` / `https://api.deepseek.com`；`LLM_PROVIDER=ollama` 时默认走本地 11434 |
| `ALIYUN_ACCESS_KEY_ID` / `_SECRET` / `ALIYUN_APP_KEY` | 实时字幕必填 | 不配则课堂内没有转写 |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 否 | 只有这两个被真正读取。不配时情绪/视频证据的 OSS 上传线程会报错（仅日志），库中该行仍保留本地 `/storage/...` 路径 |
| `AGORA_APP_ID` | 音视频必填 | `appid` 模式下服务端不签发 token；`server.py` 另有内置兜底 App ID |
| `RESEARCH_*` | 否 | 研究增强模块，默认关闭 |

三个容易踩的点：

1. **`APP_HOST` / `APP_PORT` 是无效的。** `config.py` 会解析它们，但 `server.py` 的 `__main__` 里写死了 `uvicorn.run(app, host="0.0.0.0", port=8000)`。要换端口得用 `uvicorn server:app --port N` 或改代码。
2. **系统环境变量优先于 `.env`。** `config.py` 用 `os.environ.setdefault` 读取 `.env`，所以 systemd 的 `EnvironmentFile=` 会覆盖项目目录下的 `.env`。生产改配置请改 `/etc/smartclass1/smartclass1.env`。
3. **OSS 的 bucket / endpoint / domain 不是环境变量。** `config.py` 与部署 env 模板里虽然有 `OSS_BUCKET_NAME` / `OSS_ENDPOINT` / `OSS_DOMAIN`，但真正取值的 `oss_config.py` 把这三项**硬编码**为 `collaborative-learning-videos` / `oss-cn-hangzhou.aliyuncs.com` / 由此拼出的域名（只从 env 读 `OSS_ACCESS_KEY_ID` 和 `OSS_ACCESS_KEY_SECRET`）。要换 bucket 或换地域，必须改 `oss_config.py`，改 env 无效。

---

## 6. 接口概览

共 **56 个 HTTP 路由 + 3 个 WebSocket**（`grep -c '@app\.' server.py`）。

**页面与静态**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 返回 `index.html`（带 no-cache 头） |
| GET | `/pcm-processor.js` | AudioWorklet 脚本 |
| GET | `/storage/*` | 静态挂载 `storage/` |

**鉴权**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/register` | 学号+用户名+密码+角色，form 表单 |
| POST | `/api/login` | 学号+密码，返回 `{status, user:{id,student_id,username,role}}` |
| POST | `/login` | 统一入口：教师建课 / 学生按班级码加入 |

**WebSocket**

| 路径 | 用途 |
| --- | --- |
| `/ws/{username}/{meeting_id}` | 课堂主通道（消息、状态同步） |
| `/ws-asr/{username}/{meeting_id}` | 推流音频 → 返回识别文本 |
| `/ws-signal/{username}/{meeting_id}` | Agora 信令 |

**课堂与转写**：`GET /api/meeting/{id}`、`GET /api/transcripts/{id}`、`GET /summary`、`POST /api/browser-asr-final`、`POST /api/check-silence`、`POST /api/check-quiet-members`、`POST /api/end-class`、`GET /api/realtime-stats/{id}`、`GET /api/snapshot/{id}`、`GET /api/get-video-context`、`GET /api/emotion-details/{id}`

**AI**：`POST /api/ai-tutor`、`POST /api/ai-tutor-stream`（SSE）、`POST /api/generate-report`、`POST /api/generate-report-stream`（SSE）、`POST /api/suggest-topic`、`POST /api/quick-decompose`、`GET /api/knowledge-graph/{id}`、`POST /api/generate-pdf-report`

**练习与答题**：`GET /api/exercises/{report_id}`、`GET /api/download-exercises/{report_id}`、`POST /api/submit-answer`、`POST /api/grade-short-answer`、`POST /api/quiz-error-analysis`、`GET /api/student-quiz-history/{user_id}`

**观点投票**：`POST /api/cluster-viewpoints`、`POST /api/cast-vote`、`POST /api/close-vote`、`POST /api/confirm-vote`

**教师端**：`GET /api/teacher-stats/{id}`、`GET /api/teacher-classes/{id}`、`GET /api/teacher-templates/{id}`、`DELETE /api/delete-template/{id}`、`GET /api/active-groups/{id}`、`GET /api/class-groups/{id}`、`GET /api/all-student-reports/{id}`、`GET /api/class-history/{id}`

**学生端**：`GET /api/student-home-stats/{id}`、`GET /api/reports/{user_id}`、`GET /api/meeting-reports/{id}`

**声纹**：`GET /voiceprint_register`、`POST /api/voiceprint/register`、`POST /api/voiceprint/verify`、`POST /api/voiceprint/identify`、`GET /api/voiceprint/status/{username}`、`GET /api/voiceprint/users`、`DELETE /api/voiceprint/unregister/{username}`

**研究模块 / 其他**：`GET /api/research-runtime`、`POST /api/research-runtime/config`、`POST /api/research-runtime/prepare-layout`、`GET /api/agora-token`

两个 SSE 接口（`/api/ai-tutor-stream`、`/api/generate-report-stream`）返回 `text/event-stream`，**经 nginx 反代时必须关闭缓冲**（`proxy_buffering off`），否则前端会一直等不到增量内容，直到整段生成完才一次性吐出 —— `deploy/nginx-smartclass1.conf` 已处理。

---

## 7. 前端

- 全部 UI 在 `index.html` 一个文件里（原生 JS，无框架、无构建）。视图包括：登录/注册、教师工作台、学生学习中心、课堂页。
- 麦克风音频经 `pcm-processor.js`（AudioWorklet）编码后通过 `/ws-asr/...` 推给后端。
- 与后端同源访问即可，无需跨域配置。

---

## 8. 部署

`deploy/` 内容：

| 文件 | 作用 |
| --- | --- |
| `deploy.sh` | 一键部署（Debian 系 / RHEL 系） |
| `nginx-smartclass1.conf` | nginx 站点模板（HTTP→HTTPS、反代 8000、WebSocket、SSE） |
| `smartclass1.service` | systemd 单元（`User`/`Group` 由 `deploy.sh` 按发行版注入） |
| `smartclass1.env.example` | 生产 env 模板（装到 `/etc/smartclass1/smartclass1.env`，权限 600） |
| `README.md` | 部署说明（历史文档，部分内容已过时） |

一键部署：

```bash
sudo bash deploy/deploy.sh
```

脚本的执行顺序（本次修复后）：

```
check_root → check_system → install_dependencies → check_python
  → create_directories → upload_project → create_venv → configure_env
  → configure_systemd → bootstrap_http_nginx → configure_ssl
  → configure_nginx → configure_firewall → set_permissions → start_services → show_info
```

几个关键点：

- **先 HTTP 再 HTTPS。** 首次部署时证书还不存在，若直接装载引用 `/etc/letsencrypt/live/...` 的正式配置，`nginx -t` 必然失败，于是永远走不到申请证书那一步。脚本改为先写一份临时 HTTP 配置供 `certbot --webroot` 校验，拿到证书后再 `sed` 替换模板里的域名并装载正式配置；申请失败则保留 HTTP-only 并给出警告。
- **Python 版本闸门。** 脚本在装依赖后会校验 `python3 >= 3.11`（SQLAlchemy 2.1 的下限）。Ubuntu 22.04 自带 3.10、CentOS 7 自带 3.6 都不满足，需先装 python3.12 再 `PYTHON_BIN=python3.12` 重跑。
- **`setuptools<81` 在依赖之后单独安装。** 见 §11。
- **RHEL 系差异**：Web 用户是 `nginx`（非 `www-data`），站点放 `/etc/nginx/conf.d`（没有 `sites-available`），`epel-release` 必须先装，`ffmpeg` 要走 RPM Fusion，systemd < 240 时 `StandardOutput=append:` 会被降级为仅 journald。

nginx 模板本次修掉的三个缺陷：

1. WebSocket 的 `location` 原先只覆盖 `/ws/`，**匹配不到** `/ws-asr/` 与 `/ws-signal/`（nginx 前缀匹配不做跨段模糊）。改为正则 `^/ws(-asr|-signal)?/`，并补上 `Upgrade`/`Connection` 与 3600s 超时。
2. SSE 接口未关闭缓冲。已为两个 stream 接口单独加 `proxy_buffering off`。
3. `add_header` **不会**继承进"自身也定义了 `add_header` 的 location"。`/api/` 块原先只加了 `Cache-Control`，导致 server 级的安全响应头在这一块全部丢失。已在 `/api/` 内重复声明安全头；`/storage/` 块则改为不定义任何 `add_header`，从而继续继承 server 级安全头。

---

## 9. 已知限制与安全（默认值不等于安全）

以下都是**当前代码的真实状态**，上生产前必须处理：

| 项 | 现状 | 影响 |
| --- | --- | --- |
| 密码存储 | `users.password` **明文**存储、明文比较（`/api/login` 里 `user.password != password`） | 库一旦泄露即全量密码泄露 |
| 接口鉴权 | **没有任何鉴权**。全仓库只有 `Depends(get_db)`，无 JWT / Bearer / API Key 校验 | 任何人可调用任意 `/api/*`，包括 `DELETE /api/delete-template/{id}`、`POST /api/end-class`、`GET /api/all-student-reports/{teacher_id}` |
| CORS | `allow_origins=["*"]` 且 `allow_credentials=True` | 浏览器对"`*` + credentials"的组合会拒绝；本项目没有 cookie 鉴权，同源部署不受影响 |
| 在线人数 | `MemberConnection` 表在 `server.py` 中**只被导入、从未写入** | 学生端"在线人数"恒为 0（死代码） |
| 研究模块 | `RESEARCH_MODULES_ENABLED=false`，需要额外 6 份模型权重 | 相关接口是占位实现 |
| 数据库迁移 | 未使用 Alembic | 结构变更需手工 `ALTER TABLE`，容易与 ORM 漂移 |
| 代码组织 | `server.py` 单文件 6500+ 行；根目录散落大量一次性脚本 | 维护成本高 |

---

## 10. 文档现状（哪些旧文档不可信）

| 文件 | 状态 |
| --- | --- |
| **`docs/README.md`（本文）** | 以当前代码为准，已实测 |
| `README.md`（根目录） | **数据库部分错误**：正文写 "MySQL (远程数据库)"、"MySQL 5.7+"，示例连接串为 `mysql+pymysql://...`。其余功能描述大体可用 |
| `DEPLOYMENT.md` | **数据库部分错误**：连接串为 `mysql+pymysql://...`，备份命令是 `mysqldump`。按它操作会失败 |
| `功能介绍文档.md` | 功能清单可用；涉及数据库类型处同样写成了 MySQL |
| `PROJECT_SCAN_AND_STARTUP_REPORT.md` | 项目扫描与启动问题报告，含编码缺陷的完整取证 |
| `deploy/README.md` | 其"手动部署步骤"里 **7. 配置 Nginx → 8. 配置 SSL 证书** 的顺序是错的（首次部署时证书还不存在，`nginx -t` 必然失败）。以本文 §8 与 `deploy.sh` 的顺序为准 |
| `STAGE*.md` / `BUGFIX_*.md` / `P4_*.md` 等 | 开发过程记录，非使用文档 |
| `tests/` 与 `test/` | 两套并存且功能重叠：`tests/` 用 `TestClient(app)` 进程内测试，可直接 `pytest tests/`；`test/` 是 `requests` 打 `http://localhost:8000` 的联调脚本，**需要先起服务**，属于手工执行 |

---

## 11. 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| `ModuleNotFoundError: No module named 'pkg_resources'` | `setuptools >= 81` 删除了该模块，而 `webrtcvad`（经 `resemblyzer` 引入）仍在导入它。执行 `pip install "setuptools<81"`。`requirements.txt` 已固定该上限 |
| 中文读出来是乱码 | 连接串 `charset` 不是 `utf8`，或该列是 `varchar`。见 [§4.3](#43-charset-必须是-utf8--中文乱码的根因) |
| 中文写入后再读变成 `?` | `charset=cp936` 造成的**不可逆**写入损坏。改回 `utf8` 后，已损坏的数据无法恢复，需重新写入 |
| `TypeError: 'login_timeout' is an invalid keyword argument for Connection()` | 旧版 `database.py` 把 pymssql 专有的 `login_timeout` 无条件传给所有方言，SQLite 会直接抛错。现已按方言区分（`_connect_args`） |
| `(5074, "The index '...' is dependent on column '...'")` | 改列类型前需先 `DROP INDEX`，改完再建回 |
| 服务能起但注册/登录失败 | 旧版这两个接口绕过 ORM 直连 pymssql 且只认 `DB_*`。本次已改为走 `DATABASE_URL` + ORM |
| nginx 下 SSE 不出增量内容 | `proxy_buffering` 未关闭。见 [§8](#8-部署) |
| 启动后接口 500、静态资源 404 | 不是从项目根目录启动 |
| `nginx -t` 报 `cannot load certificate` | 首次部署时装了引用证书的配置。见 [§8](#8-部署) 的顺序说明 |

---

## 12. 维护约定

1. **中文列一律用 `Unicode` / `UnicodeText`**（或显式 `NVARCHAR(n)`），不要用 `String` / `Text`。原因见 §4.3。
2. **`charset` 永远保持 `utf8`**，不要为了"修乱码"改成 `cp936`。
3. **新增环境变量时同步更新两处模板**：`.env.example` 与 `deploy/smartclass1.env.example`。
4. **新代码只读 `DATABASE_URL`**，不要引入 `DB_*` 这类第二套数据库配置。
5. **表结构变更**：改 `database.py` 的模型，再为存量库补一条 `ALTER TABLE` 补丁（没有 Alembic）。
6. **新增前端资源**：放在项目根目录并用相对路径引用；换端口/换工作目录都要先想清楚路径。
7. `.env`、`storage/`、`voiceprints.json` 含真实密钥与用户数据，`.gitignore` 已忽略，**不要提交**。

---

*本文件由 `fix/startup-and-docs` 分支建立。文中版本号、路由数量、连接串格式与行为均已在本机对照代码核实。*
