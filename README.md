# 智能协作学习系统

这是一个基于AI技术的智能协作学习平台,通过实时音视频分析、自然语言处理和情绪识别技术,为师生提供智能化的教学支持与学习评估。系统支持教师/学生多角色协作,实现教学过程的全程智能监控、即时反馈和数据分析。

---

## 快速开始（容器，一条命令）

```bash
cp .env.example .env              # 填入密钥，见下方"必填项"
cp .env.dev.example .env.dev      # 开发库指向，照抄即可，不用改
docker compose up --build
```

`up` 会按顺序拉起三个服务：`db`（SQL Server 2022，数据落命名卷）、
`db-init`（一次性跑 `db/schema.sql` 建库，跑完退出）、`app`。

打开 <http://127.0.0.1:8000>。


>首次构建或依赖变更后重建时，如果 Debian 软件包下载较慢，可切换到 USTC 镜像：
> ```powershell
> $env:DEBIAN_MIRROR='https://mirrors.ustc.edu.cn/debian'
> docker compose up --build
> ```
>这是可选的加速设置。日常启动已构建的项目运行 `docker compose up -d` 即可。


**必填项**——只有这两处，其余 50 个键都有默认值：

| 位置 | 键 | 不填会怎样 |
|---|---|---|
| `.env` | `LLM_API_KEY` | `import server` 直接抛 `OpenAIError`，容器起不来。只想看看页面可以给假值 |
| `.env.dev` | 整份 | compose 里是 `required: true`，缺了当场报错。`cp .env.dev.example .env.dev` 即可 |

数据库指向**按环境分层**：`.env.dev` 连本机容器（`dev`），`.env.prod` 连线上 RDS（`prod`），
由 `APP_ENV` 选择。

### 本地开发怎么干活

**仓库目录整份挂进了容器，改代码即时生效**——在宿主机上用你惯用的编辑器改
`app/` 或 `server.py`，容器里的 uvicorn 会自动重载（Windows 上靠
`WATCHFILES_FORCE_POLLING` 轮询，否则 `--reload` 收不到事件）。不用重建镜像，
也不用进容器编辑。

常用命令：

```bash
docker compose logs -f app                        # 看日志（含重载）
docker compose exec app bash                      # 进容器（建表、查数据、跑脚本）
docker compose exec app python -m pytest          # 在容器里跑测试
```

对着本地库查数据（`bash -c` 不能省——`$MSSQL_SA_PASSWORD` 只在**容器内**有值，
宿主 shell 里是空的，省掉就会拿着空口令去连）：

```bash
docker compose exec -T db bash -c \
  '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" \
   -C -b -d cscl_db -Q "SELECT COUNT(*) FROM users"'
```

### 测试

```bash
./venv/Scripts/python.exe -m pytest        # 宿主上跑，日常推荐
docker compose exec app python -m pytest   # 容器里跑
```

> ⚠️ **不要跑裸 `pytest`。** `pytest.ini` 里的 `testpaths = tests_safe` 是隔离闸门，
> 绕过它会让测试去连真实库。

只有 `tests_safe/` 会被收集，它是**唯一**的测试套件：其中相当一部分是重构期间钉住行为
等价性的守卫（路由契约、模块搬家、路径锚点、容器资产），不只是功能测试。
容器内跑法下按 `deploy/docker.md` 有 1 条既知基线失败，**不要重录基线**。
细节见 `tests_safe/README.md`。

## 可选依赖
- 阿里本地语音识别 `requirements_funasr.txt`
- 性能优化/GPU加速 `requirements_enhanced_runtime.txt`

## 增强版：把 GPU 直通给容器

增强版要 GPU，而主编排**故意不带**设备预留——那在 compose 里是硬要求，写进去会让
没有 NVIDIA 运行时的机器连标准版都起不来。所以另有一份叠加文件：

```bash
# 直通设备 + 把镜像里的 torch 换成 CUDA 版（镜像会大出好几 GB）
TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124 \
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

镜像默认装的是 **CPU 版 torch**，它的 `torch.cuda.is_available()` 永远是 `False`
——设备直通了也看不见，所以上面那条命令要把 `TORCH_INDEX_URL` 一起给（只想直通设备、
不换索引的话，去掉那个变量即可）。六个模型槽位与增强依赖由宿主上的
`setup_enhanced_runtime.ps1` / `download_enhanced_open_models.py` 准备，
核实用仓库根的 `check_enhanced_runtime.ps1`。细节见 `docs/安装及使用.md` 3.2。

## 核心功能

### 🎓 教师功能
- **智能教学设计生成**: 输入课题和参考资料,AI自动生成教学目标、分工策略和阶段性成就指标
- **实时监控看板**: 监控所有学生的情绪变化、参与积极性、话题关联度
- **学习报告生成**: 自动生成每个学生的学习报告,包含情绪分析、学习表现、不足点和改进建议
- **习题智能生成**: 根据学生薄弱点自动生成10-15道个性化练习题
- **心理健康评估**: 基于情绪波动和行为模式分析潜在心理问题
- **知识图谱可视化**: 自动构建课堂讨论的知识关系网络

### 👨‍🎓 学生功能
- **实时协作学习**: 视频音频实时采集,支持10-50人同时在线
- **智能提示反馈**: AI实时分析发言内容,提供学习引导和思维拓展建议
- **实时字幕显示**: 语音转文字内容直接显示在视频画面底部
- **知识点追踪**: 实时显示课堂知识点完成情况
- **专注度监测**: 实时计算并显示话题关联度和学习投入程度
- **个人学习报告**: 课后查看详细的学习报告和个性化习题

### 🤖 AI能力
- **LLM服务**: DeepSeek API驱动的教学设计、内容分析、习题生成
- **语音识别**: 阿里云语音识别服务,实时语音转文字
- **视觉分析**: OpenCV + Haar级联分类器实现人脸检测和情绪识别
- **知识图谱**: 自动从对话中提取概念和关系,构建可视化知识网络

## 使用示例

### 教师创建课堂
1. 选择"教师"角色
2. 输入课堂号和主题
3. AI自动生成教学设计
4. 学生使用课堂号加入

### 学生加入课堂
1. 选择"学生"角色
2. 输入课堂号
3. 授权摄像头和麦克风
4. 开始协作学习

### 课堂互动
- 学生发言自动转文字并显示在视频底部
- AI实时分析话题关联度并给出提示
- 知识点完成自动标记
- 情绪异常自动记录

### 课后分析
- 教师查看每个学生的学习报告
- 学生查看个人报告和习题
- 查看知识图谱了解讨论结构

## 技术架构

### 后端

| 项 | 实际用的 |
|---|---|
| 框架 | FastAPI + Starlette + Uvicorn（含 WebSocket） |
| 数据库 | **SQL Server 2022**（线上是远程实例），经 `pymssql` 走 **TDS** 协议 |
| ORM | SQLAlchemy 2.x，模型在 `app/models/` |
| 大模型 | DeepSeek API（走 `openai` SDK 的兼容接口） |
| 语音识别 | 阿里云 NLS 实时转写，Token 的签发与刷新在 `app/services/ai_core.py`；另有浏览器端 Web Speech 兜底，见 `POST /api/browser-asr-final` |
| 视觉处理 | OpenCV（Haar 级联），模型文件 `haarcascade_frontalface_default.xml` 在仓库根 |
| 音视频处理 | FFmpeg —— **装在容器镜像里**（`apt-get install ffmpeg`），不是宿主的前置依赖 |
| 运行环境 | Python **3.12**（`Dockerfile` 写死 `python:3.12-slim`，与开发机 venv 同大版本） |

### 前端

| 项 | 实际用的 |
|---|---|
| 框架 | Vue 2.6.14 + Tailwind 2.2.19 |
| 图表 | ECharts 5.4.0（知识图谱、统计图） |
| 通信 | Axios 1.20.0 + WebSocket |
| 实时音视频 | Agora RTC SDK 4.22.0（`static/vendor/agora/`） |
| 渲染 | marked 15.0.12（报告里的 Markdown） |
| 图标与字体 | Font Awesome 6.0.0、Inter |

上述前端库**全部本地化在 `static/vendor/` 下，页面不依赖公网 CDN**。
每个文件的来源、版本与 SHA256 在 `static/vendor/SOURCES.json`，由
`tools/vendor_frontend.py` 生成，**请勿手改**。

## 项目结构

```
algorithm-study-master/
├── server.py                      # 主服务器（FastAPI 入口）
├── index.html                     # 前端界面
├── pcm-processor.js               # 前端音频采集脚本（`GET /pcm-processor.js`）
├── haarcascade_frontalface_default.xml   # 人脸检测模型（video_processor 在仓库根找它）
├── conftest.py / pytest.ini       # 测试隔离闸门，只收集 tests_safe/
├── .env.example                   # 共享密钥模板（.env / .env.dev / .env.prod 都由它派生）
├── Dockerfile / docker-compose.yml / .dockerignore
├── requirements*.txt              # 基础 / dev / lock / 两套可选运行时
├── app/                           # 应用代码
│   ├── core/                      # 配置、数据库、路径锚点
│   ├── models/                    # ORM 模型
│   ├── routers/                   # HTTP 路由
│   ├── realtime/                  # WebSocket 与实时链路
│   └── services/                  # LLM / 语音 / 视频 / 知识图谱等服务
├── static/                        # 前端资源（css / js / img / vendor）
├── db/                            # schema.sql + init.sh（生产开发通用建库）
├── deploy/                        # 部署文档与配置模板
├── docs/                          # 文档与验收笔记
├── tests_safe/                    # 唯一被收集的测试套件
├── tools/                         # 一次性 / 运维脚本
├── enhanced_bridge_templates/     # 可选：说话人 / 音视频增强的桥接模板
├── _tmp_agora_token_builder/      # server.py 追加进 sys.path 的小工具
├── archive/                       # 已归档的代码与文档（不参与运行，未删除）
├── storage/ / uploads/            # 运行时数据（不进版本库）
└── venv/                          # 本地虚拟环境（不进版本库）
```

> 根目录那几样"看着该挪走"的东西**动不得**：`download_enhanced_open_models.py`、
> `requirements_enhanced_runtime.txt`、四个 `.ps1`、`enhanced_bridge_templates/`。
> `GET /api/research-runtime` 把其中 5 条路径**原样返回**给调用方（三个 `.ps1`：
> `prepare_enhanced_model_layout` / `setup_enhanced_runtime` / `check_enhanced_runtime`，
> 外加那个 `.py` 与 `.txt`），`tests_safe/test_research_assets.py` 断言它们就在仓库根。
> 剩下的 `install_enhanced_models_from_local.ps1` 与 `enhanced_bridge_templates/`
> 虽不进该接口，但后者被 `download_enhanced_open_models.py` 按**仓库根相对路径**引用
> （`repo_root / "enhanced_bridge_templates" / …`），同样挪不得。

## 数据库表结构

### 核心表
- **users**: 用户信息 (支持teacher/student角色)
- **meetings**: 课堂信息 (包含教学设计、知识点)
- **transcripts**: 对话记录 (实时语音转文字)
- **emotion_logs**: 情绪日志
- **ai_insights**: AI提示记录

### 扩展表
- **knowledge_graphs**: 知识图谱数据
- **graph_nodes**: 图谱节点
- **graph_edges**: 图谱边
- **learning_reports**: 学习报告
- **exercises**: 习题库
- **student_answers**: 学生作答记录
- **mental_health_assessments**: 心理健康评估

建表脚本是 `db/schema.sql`（生产开发通用、可重复执行）。它是**从生产导出的冻结快照**，
模型改了它不会跟着改；重新生成用 `python tools/export_prod_schema.py --yes`。

## 文档在哪

| 想看什么 | 去哪 |
|---|---|
| 为什么这么搭、怎么跑起来 | `deploy/docker.md` |
| 上线部署 | `deploy/README.md` |
| 接口清单 + 测试基线覆盖 | `docs/route-inventory.md` |
| 测试为什么这么写、边界在哪 | `tests_safe/README.md` |
| 功能层面（面向使用者） | `docs/功能介绍文档.md` |
| 安装与使用（含容器部署步骤） | `docs/安装及使用.md` |
| OSS 配置 | `docs/OSS配置指南.md` |

> `docs/DEPLOYMENT.md` 是**陈旧史料**：内容是 MySQL/pymysql/3308 时代的，与实际实现
> （SQL Server/pymssql）不符，照它部署得不到可用系统。保留只为留痕，不要照做。

## 部署指南

### 生产环境部署要点
1. 使用Nginx反向代理
2. 配置SSL证书(Let's Encrypt)
3. 使用Systemd管理服务
4. 配置日志轮转
5. 设置防火墙规则
6. 数据库定期备份

具体步骤见 `deploy/README.md`（`nginx-smartclass1.conf`、`smartclass1.service`、
`smartclass1.env.example` 三个模板也在那里）。建库用同一份 `db/schema.sql`：

```bash
sqlcmd -S <host> -U <user> -P <password> -d cscl_db -i db/schema.sql
```

## 许可证

MIT License

## 联系方式

如有问题或建议,请通过以下方式联系:
- 邮箱: dai13576381980@qq.com

## 致谢

- DeepSeek: LLM服务提供
- 阿里云: 语音识别服务
- OpenCV: 视觉处理库
- FastAPI: 高性能Web框架
- Vue.js: 前端框架
