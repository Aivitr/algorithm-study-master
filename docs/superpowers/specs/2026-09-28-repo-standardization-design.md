# 仓库规范化重构 · 技术设计

**日期**：2026-09-28
**状态**：待评审
**关联文档**：`docs/仓库规范化重构-申请报告.md`（管理层报批用）

---

## 0. 文档定位

本文是**技术设计**，面向实施者。`docs/仓库规范化重构-申请报告.md` 是面向管理层的报批文档。两者共享同一套实测事实，但本文包含实施细节、目录结构、验证方式与回退策略。

---

## 1. 硬约束（不可协商）

以下约束来自需求方，任何设计决策都不得违反：

| # | 约束 |
|---|---|
| C1 | **业务逻辑不做任何修改** |
| C2 | **全量保留所有代码，不删除任何文件** |
| C3 | 不影响线上服务的正常运行 |
| C4 | 不改动数据库表结构与数据 |
| C5 | 对外接口的地址、入参、出参保持不变 |
| C6 | **禁止以 ORM 为依据重建、迁移生产数据库**——生产库结构与 ORM 存在实质差异（见 §3.8），`Base.metadata.create_all()` 会丢失 3 张表与 6 列 |

**推论一**：分类与归档只改变文件的**物理位置**，不改变任何一行的内容。确需修改内容的地方（见 §3.5 的注释污染、§4.4 的配置改造）必须单独列出并取得确认。

**推论二**：C6 意味着容器（阶段 5）**只能连接既有数据库，不得建库**。

---

## 2. 已确认决策

| # | 议题 | 决策 |
|---|---|---|
| D1 | 后端架构 | 按 FastAPI 社区惯例分层：`routers/` + `services/` + `repositories/` + `schemas/` + `models/` + `core/`。**不采用 MVC** |
| D2 | 相对路径 | 重构前先完成路径锚点统一（阶段 0） |
| D3 | 函数内导入 | 用 lint 规则禁止，不依赖测试发现 |
| D4 | 前端 | 引入 Vite，拆分为 ②a 工程化、②b 组件拆分两步 |
| D5 | 容器化 | **延后至阶段 5**。理由：环境隔离的价值在代码稳定后兑现；与代码搬迁同时进行会导致故障无法归因 |
| D6 | 依赖管理工具 | **不引入 uv**。仅做「版本固化」，用现有 pip 完成 |
| D7 | 运行时改配置 | 查实为 3 个 `RESEARCH_*` 键（代码层功能开关）。容器化时需专门处理 |
| D8 | 结构化范围 | 仅重构与运行直接相关的代码 |
| D9 | 非相关文件 | 保持原样，只做物理搬迁 |
| D10 | 测试 | 先建测试基线，再动代码 |
| D11 | 测试数据库 | **B 方案**：本地库 + 合成数据 + 只读 schema 校验（详见 §8.3） |
| D12 | 归档 | **做结构化分类**，不堆在单一目录。依据是「来源」而非「价值」（详见 §5.3） |
| D13 | 依赖固化 | **降级为「待校验」**。无生产机访问，先固化本机已验证版本并**显式标注为待校准**；不声称等价于线上版本 |
| D14 | 配置改造范围 | **先做开发环境**，生产侧（真实键值、线上键名核对）列为待办 |
| D15 | 容器化范围 | **仅本地开发容器化**；线上部署编排与部署指令列为待办 |
| D16 | 空目录 | `steploc/` `templates/` `static/` `assets/` **四者均确认为空**（`assets/` 的 css/img/js 亦为空子目录），**直接移除** |
| D17 | 冒烟基线选址 | **基线不需要连生产库**。生产与 ORM 的差异（§3.8）全部为 0 代码引用，对代码可达路径行为等价；本地按 ORM 建库即可（订正 §8.1 原先的阻塞判断） |
| D18 | `users` 异常记录 | 2026-09-28 那条 `users` 记录**经需求方确认，为需求方本人使用系统新建用户所致**，非异常写入，无需处置。**同时该事实证明系统在 2026-09-28 仍可正常访问与使用**（见 §3.9） |

---

## 3. 实测事实（设计依据）

以下均为实测结果，是各设计决策的直接依据。

### 3.1 路径锚点

**扫描范围**：15 个运行时模块全量 + 全仓 `os.getcwd()` 检索。**结论：路径问题全部集中在 `server.py`，其余 14 个运行时模块干净。**

锚点分四类。**C 与 D 在文本上不可区分，D 是误伤点。**

**A 类 — 正确的锚（`__file__` 相对）**

| 位置 | 状态 |
|---|---|
| `server.py:21` `BASE_DIR = os.path.dirname(os.path.abspath(__file__))` | **安全**，但目前仅用于 `1/`、`2/`、`_tmp_agora_token_builder/` 三处 |
| `config.py:7` `BASE_DIR = Path(__file__).resolve().parent` | **安全**（配置侧本就正确，此前的"危险"标注有误） |

**B 类 — 12 处 `ROOT_DIR` 引用，锚在 cwd**

`server.py:71` `ROOT_DIR = os.getcwd()`，被 12 处引用（`:73 :595 :620 :727 :1367 :1380 :1546 :1841 :1859 :2963 :6272 :6273`）。

> 此前文档记为"13 处"，是把定义行一并计入；**实际引用为 12 处**。

**C 类 — 9 处裸相对字面量，同样锚在 cwd，且此前完全未计数**

这些不调用 `os.getcwd()`，因此**按 `os.getcwd()` 检索时全部漏检**：

| 行 | 代码 | 读/写 |
|---|---|---|
| 92 | `StaticFiles(directory="storage")` | 读（静态文件挂载点） |
| 1911 | `open("index.html")` | 读（首页） |
| 1916 | `FileResponse("pcm-processor.js")` | 读（前端 JS） |
| 5598 | `pdf_dir = "storage/reports"` | 写（PDF 报告） |
| 5690 | `exercise_dir = "storage/exercises"` | 写（练习题集） |
| 5903 | `template_dir = "storage/templates"` | 写（模板上传） |
| 6305 | `FileResponse("voiceprint_register.html")` | 读（**该文件不存在，见下**） |
| 6513 | `temp_audio_path = f"storage/temp_identify_{...}"` | 写（临时音频） |
| 6514 | `os.makedirs("storage")` | 写 |

**D 类 — 形似路径、实为 URL 或入库值（7 处）**：**禁止修改**

| 行 | 代码 | 后果 |
|---|---|---|
| 721 / 729 / 1540 / 1548 / 1854 / 1861 | `video_url = f"storage/video_chunks/..."`、`snapshot_url = ...` | 改动即破坏前端取媒体 |
| 1626 | `audio_file_path=f"storage/audio_chunks/{a_name}"` | **写入 `transcripts` 表**；改动即改写已入库数据（违反 C4） |

> **这是本次路径统一中最危险的一点**：`audio_file_path` 名为路径、实为存库的 URL 字符串。任何"把相对路径批量改成绝对路径"的做法都会同时命中 D 类，后果是**改写已入库数据 + 前端取不到音频**。**必须逐处判断，禁止批量替换。**

**合计**：真实 cwd 依赖点 **12 + 9 = 21 处**（此前文档为 13 处，缺 8 处 C 类）。

**附带发现**：`/voiceprint_register` 路由（`server.py:6302-6305`）所指向的 `voiceprint_register.html` **全仓不存在**，该路由**必然抛 `FileNotFoundError`**。属既有故障，与声纹模块整体未接入同源。**本次仅做锚点统一，不修复该文件缺失**（C1）。

**已实测复现的静默失效**：将 `config.py` 移入子目录后，`BASE_DIR` 由仓库根变为该子目录；`_load_dotenv()` 找不到 `.env`，**静默 return**；`database.py:11` 的 `os.getenv("DATABASE_URL", "sqlite:///./storage/app.db")` 兜底生效。服务正常启动、页面正常打开，但读写的是空 SQLite 库，**无任何报错**。

### 3.2 模块可达性

- 顶层 `.py` 模块：**57 个**
- 从 `server.py` 经 import 可达：**15 个**

```
ai_core  config  database  gemma_emotion_client  knowledge_graph_service
llm_service  oss_config  oss_utils  research_algorithm_fusion
research_enhanced_adapters  research_registry  research_runtime
server  video_processor  voiceprint_manager
```

- 不可达：**42 个**

**方法论修正**：可达性分析将「工具脚本」与「死代码」混为一谈。工具脚本按设计就不应被 import，因此不可达 ≠ 无用。`download_enhanced_open_models.py` 即属此类（它是手动执行的模型下载工具）。

### 3.3 接口与依赖

- 路由总数：**59**（51 个在 `/api/` 下，其余 8 个为 `/`、`/login`、`/summary`、`/pcm-processor.js`、`/voiceprint_register` 及 3 个 WebSocket）
- WebSocket 路由：`/ws/{username}/{meeting_id}`、`/ws-signal/{username}/{meeting_id}`、`/ws-asr/{username}/{meeting_id}`
- 依赖项：**40 项，其中仅 1 项有版本约束**
- 配置字段：42 个（`AppSettings` 4 / `LLMSettings` 11 / `DatabaseSettings` 1 / `ASRSettings` 3 / `OSSSettings` 7 / `ResearchSettings` 16）

### 3.4 测试资产

- 测试函数：**约 70 个**（`tests/` 59 个 pytest 用例 + `test/` 若干 + 自建回归框架 `regression_test.py`）
- **可运行数量：0** —— pytest 未安装、未在依赖中声明、无任何配置文件
- 测试中直接发起写操作：**38 处**，且读取的数据库配置指向**生产库**
- 断言普遍过弱（`assert status_code in [200,400,422]`、`assert True`）；`test_api_endpoints.py:18` 在缺必填字段的请求上断言 200，**必然失败** → 该套件从未通过

### 3.5 注释污染

**40 个 `.py` 文件**的注释/文档字符串/错误消息中含 `[EMOJI]` 字面量，中文内容被替换：

| 文件 | 处数 | 位置 |
|---|---|---|
| `database.py` | 45 | 注释 |
| `oss_utils.py` | 47 | 注释、文档字符串、异常消息 |
| `video_processor.py` | 11 | 注释、文档字符串 |
| `server.py` | **3** | 仅 print 串，中文完好 |

已核实**不影响运行逻辑**（无占位符被用作数据值）。但 `database.py` 的列注释（如「学号/账号」→`[EMOJI]/[EMOJI]`）承载语义，正是重构所需信息。

来源：`remove_all_emojis.py` 声称修复 GBK 编码错误，但其映射表为恒等映射（`'[X]': '[X]'`），**当前是空操作**——污染发生在此之前。

### 3.6 部署层（nginx）

`deploy/nginx-smartclass1.conf` 为完整生产配置（HTTPS、Let's Encrypt、安全头、gzip）。其中三项**只存在于 nginx、代码中无对应物**：

| nginx 设置 | 缺失后果 |
|---|---|
| `client_max_body_size 200M` | 默认 1MB，音视频上传失败 |
| WebSocket `proxy_read_timeout 3600s` | 默认 60s，长连接被掐断 |
| HTTPS 终结 + 证书 | 丢失 HTTPS |

**潜在故障**：nginx 仅对 `location /ws/` 配置 WebSocket 升级头。`/ws-asr/` 不匹配该前缀（`/ws/` 要求 `ws` 后紧跟斜杠），会落入 `location /` —— 该处无 `Upgrade`/`Connection` 头且默认 HTTP/1.0 反代，**WebSocket 握手将失败**。而 `/ws-asr/` 是前端实际使用的路径（ASR 语音识别）。

`/ws-signal/` 同样不匹配，但**无任何调用方**，为死路由，无影响。

> **待核实**：无法从外部确认该配置是否正在线上运行。`https://smartclass1.top/` 返回连接重置，`http://smartclass1.top/` 返回 `HTTP/1.1 403 Forbidden`（`Server: Beaver`，非 nginx 标识）。需由需求方核实实际部署形态。

### 3.7 敏感信息

`D:\algorithm-study-master\.env` 含明文生产凭据：数据库口令 1 项、云服务密钥 4 组、大模型 API Key 1 项。

**已核实**：该文件**未被 git 跟踪**（`.gitignore:2` 已忽略），历史提交中**从未出现**。因此不存在已泄漏至版本历史的情况。暴露面是「任何取得项目目录的人可直接获得生产数据库完整访问凭据」。

另有第二处：`1/aliyun.py:606-609`（硬编码密钥）、`1/service_speaker.py:14`（硬编码 `HF_TOKEN`）。

### 3.8 生产库结构与 ORM 的差异（已实测确认）

**采集日期**：2026-10-01。**方式**：只读 `INFORMATION_SCHEMA.COLUMNS`，未读取任何一行数据。详细存档见 `docs/production-schema-drift.md`。

| | 数量 |
|---|---|
| 生产库实际表数 | **18** |
| ORM 定义表数 | **15** |
| 仅存在于生产库的表 | **3** |
| `transcripts` 表多出的列 | **6** |

**仅存在于生产库的表**（均被 0 个 `.py` 文件引用）：

- `collaboration_intervention_logs`（13 列）
- `evaluation_logs`（10 列）
- `rag_chunks`（7 列）

**`transcripts` 多出的列**（均被 0 个 `.py` 文件引用）：
`ptt_mode`、`corrected_by`、`correction_time`、`evaluation_evidence`、`evaluation_version`、`quality_dimensions`

> `quality_dimensions` 在代码检索中会命中 `server.py:1062` 与 `server.py:1778`，但那是 API 响应字典中的同名键，与数据库列无关。

**三点含义**：

1. **§7.3 原先标注的盲区被证实真实存在**——不再是"是否一致未知"，而是"不一致，且已查明具体内容"
2. **`Base.metadata.create_all()` 会产出少 3 张表、少 6 列的数据库**——这是数据丢失，因此列为硬约束 C6
3. **`ptt_mode` 的存在表明 Stage 5 曾在数据库层动过工**，但代码从未跟上。这与 Stage 1/3「写了模块与测试、未接入服务」是同一模式，只是痕迹留在了数据库里

**一个对称性**：代码库有 42 个从 `server.py` 不可达的模块；数据库有 3 张无任何代码引用的表。二者是同一件事——**走过但未接上的开发痕迹**。

### 3.9 服务活动时间线（已实测）

**采集日期**：2026-10-01。**方式**：对 7 张业务表执行 `MAX(时间列)`，**只读聚合值，未读取任何一行内容**。

| 表 | 最新活动 |
|---|---|
| `meetings` | 2026-04-30 20:41 |
| `transcripts` | 2026-05-01 00:31 |
| `learning_reports` | 2026-05-01 00:28 |
| `ai_insights` | 2026-05-01 00:31 |
| `emotion_logs` | 2026-04-30 22:54 |
| `student_answers` | 2026-04-20 18:37 |
| `users` | **2026-09-28 16:53** |

**读法**：

1. **业务数据在 2026-05-01 前后停止产生**，距采集日约 **5 个月**
2. 除 `users` 外，6 张业务表**全部**停在 4 月底至 5 月初
3. `users` 表存在一条 **2026-09-28** 的记录——该日期正是本次重构工作首次启动服务的日期（见 §8.3 待核实项）

**关于 2026-09-28 那条记录**：经需求方确认，为**需求方本人使用系统新建用户**所致（D18）。这排除了异常写入的可能，并且**反过来证明系统在该日仍可正常访问与使用**——服务本身并未停机。

**因此正确的读法是**：**系统仍在运行，但自 2026 年 5 月起没有新的教学活动数据**。这不同于「服务已停止」，也不同于「系统正常运行中」——是一个介于两者之间、需要需求方按教学安排来解释的状态（学期结束 / 停用 / 待迁移）。

**对管理层报告的影响**：原文「已上线运行并承载真实教学活动」的问题是**时态**，不是真伪——系统确实在运行。建议加限定为「已上线运行并承载过真实教学活动（数据至 2026 年 5 月）」。**这不改变任何技术方案**，但避免报告读者按「系统正在高频使用中」理解重构的优先级。

> 另需注意：**无法登录生产服务器**（本轮前提）与**服务可能仍在运行**这两件事同时成立，意味着当前对线上状态**既不能观测、也不能干预**。这一风险已记入 §5。

### 3.10 配置加载机制（已实测 · `config.py` 全文复核）

| 事实 | 位置 | 意义 |
|---|---|---|
| `_load_dotenv()` 在文件缺失时**静默 `return`** | `config.py:12-13` | **§1.2 静默失败的根因**。找不到配置不报错、不告警 |
| `DATABASE_URL` 缺省值 `sqlite:///./storage/app.db` | `config.py:177` | 上一条的**帮凶**——默认值让"连错库"表现为"正常启动" |
| 真实环境变量优先（`os.environ.setdefault`） | `config.py:22` | **有利事实**：容器/CI 注入天然生效，无需改造 |
| `APP_ENV` **已存在**（默认 `"dev"`） | `config.py:158` | 分环境的**开关已就位，但当前无任何逻辑消费它** |
| `_write_env_updates()` **改写 `.env` 文件** | `config.py:229-256` | 应用可写自身配置。多环境后须限定写入目标 |
| `BASE_DIR` 锚点**已然正确** | `config.py:7` | 配置侧无 §3.1 问题，问题仅在 `server.py` |

**现状**：**不存在开发/生产之分**。唯一一份 `.env`（17 个键，仅含数据库、云服务、LLM、Agora 四类凭据）**直接指向生产 RDS**。即：本机开发与线上生产**共用同一套生产凭据**。

**结论**：分环境所需的机制**已具备大半**（锚点正确、`APP_ENV` 已存在、环境变量优先级正确），缺的是**选择逻辑**与**失败时的可见性**。

---

## 4. 目标结构

### 4.1 后端

```
app/
├── main.py                 # 应用装配、中间件、生命周期（原 server.py 尾部）
├── core/
│   ├── paths.py            # 【新增】唯一的路径解析来源
│   ├── config.py           # 原 config.py
│   └── database.py         # 原 database.py（引擎与会话）
├── models/                 # SQLAlchemy 模型（从 database.py 拆出）
├── schemas/                # Pydantic 请求/响应模型（从 server.py 内联定义拆出）
├── routers/                # 按业务域切分，不按 URL 前缀
├── services/               # 业务逻辑
├── repositories/           # 数据访问
└── realtime/               # WebSocket 管理器与连接状态
    ├── connection.py       # 原 ConnectionManager
    ├── signaling.py        # 原 SignalConnectionManager
    └── asr_session.py      # 原 ASRSessionManager
```

**路由切分原则**：`/api/` 下 51 个路由中 41 个是扁平的（单段），因此**不能按 URL 前缀切分**，必须按业务域。初步划分：

| 路由模块 | 覆盖的端点（示例） |
|---|---|
| `auth.py` | `/api/login`、`/api/register` |
| `classroom.py` | `/api/meeting/*`、`/api/end-class`、`/api/active-groups`、`/api/class-groups`、`/api/realtime-stats`、`/api/check-silence`、`/api/check-quiet-members` |
| `transcripts.py` | `/api/transcripts/*`、`/api/snapshot` |
| `reports.py` | `/api/generate-report*`、`/api/reports/*`、`/api/meeting-reports/*`、`/api/generate-pdf-report`、`/api/all-student-reports/*` |
| `exercises.py` | `/api/exercises/*`、`/api/download-exercises/*`、`/api/quiz-error-analysis`、`/api/grade-short-answer`、`/api/submit-answer`、`/api/student-quiz-history/*` |
| `tutor.py` | `/api/ai-tutor*`、`/api/suggest-topic`、`/api/quick-decompose`、`/api/cluster-viewpoints` |
| `voting.py` | `/api/cast-vote`、`/api/close-vote`、`/api/confirm-vote` |
| `emotion.py` | `/api/emotion-details/*`、`/api/get-video-context` |
| `materials.py` | `/api/knowledge-graph/*`、`/api/browser-asr-final` |
| `teacher.py` | `/api/teacher-templates/*`、`/api/delete-template/*`、`/api/teacher-stats/*`、`/api/teacher-classes/*` |
| `voiceprint.py` | `/api/voiceprint/*`（6 个） |
| `research.py` | `/api/research-runtime/*`（3 个） |
| `realtime.py` | `/api/agora-token`、`/ws/*`、`/ws-asr/*`、`/ws-signal/*` |
| `pages.py` | `/`、`/login`、`/summary`、`/pcm-processor.js`、`/voiceprint_register` |

> 扁平路由的归属（如 `/api/class-history` 属 `classroom` 还是 `auth`）在阶段 3 依据实际实现确定。

**路由前缀契约**：nginx 硬编码了 `/ws/`、`/api/`、`/storage/` 三个前缀。重构后这些前缀**必须保持不变**，并在测试中断言。

### 4.2 前端

| 步骤 | 内容 | 前置 |
|---|---|---|
| ②a 工程化 | 接入 Vite；22 个 CDN 依赖本地化；`index.html` 转为模板 + 入口 | 阶段 6 |
| ②b 组件拆分 | 拆分 `new Vue({...})`（`index.html:5278`）下的单实例根组件 | ②a 完成 |

**现状**：`index.html` 11,299 行；HTML 模板占 1–5228 行；`<script>` 自 5229 行起；**零 `Vue.component` 定义**——全部逻辑在单个根实例中。

**风险**：Vue 2.6.14 已于 2023-12 EOL，`@vitejs/plugin-vue2` 为社区维护。此为长期维护风险，需在开工前确认可接受。

### 4.3 归档结构

归档遵循**三条规则**：

1. **有互相引用的文件成组搬迁，不拆散** —— 优先保持引用关系，其次才是主题归类
2. **无引用关系的，按来源归类** —— 不按「重要性」归类（重要性不可从代码推导）
3. **归不进去的进 `unsorted/`** —— 宁可显式留空，不硬塞

```
archive/
├── README.md                 # 索引 + 归档规则 + 查阅指引
│
├── speech-stages/            # 语音识别分阶段计划（Stage 1–4 产物 + Stage 5 计划）
│   ├── README.md             # 记录该计划走到哪一步停止
│   ├── modules/              # 9 个声纹/说话人模块
│   ├── tests/                # test_speaker_lock / test_cross_user_dedup /
│   │                         #   test_speaker_volume_arbitration
│   ├── verification/         # check_project_status / verify_stage4 / verify_p4_completion
│   └── docs/                 # STAGE1–5 全套 + P4_* 三份
│
├── prototypes/               # 早期原型（已被现方案替代）
│   ├── legacy-1/             # 原 1/ 目录（含现成的 README1.md，内含 9 个脚本）
│   └── legacy-3/             # 原 3/ 目录（仅 c_realtime_integration.py）
│
├── ops-scripts/              # 手动执行的运维/维护脚本
│   ├── codemods/             # modify_backend / update_backend / update_frontend /
│   │                         #   remove_all_emojis / temp_fix(0 字节)
│   ├── db-maintenance/       # fix_db_final / init_db / check_all_tables /
│   │                         #   check_db_structure / check_users*
│   └── diagnostics/          # debug_emotion_data / detect_oss_region /
│                             #   diagnose_agora / check_video_logs
│
├── legacy-tests/             # 顶层散落的 11 个 test_*.py + run_all_tests
├── dev-docs/                 # BUGFIX_* / DATABASE_AUDIT / GEMMA_* / UI_UPGRADE /
│                             #   COMPLETE_SOLUTION / README_OPTIMIZATION / *.json
├── vendors/                  # _tmp_agora_token_builder（手动解包的 pip 包）
└── unsorted/                 # 留空备用
```

**每个归档子目录配一个 `README.md`**，记录三件事：

1. 这些文件原本是干什么的
2. 为什么在这里（属于哪个计划 / 哪个阶段）
3. 已知的引用关系与注意事项

> **命名说明**：原 `1/`、`3/` 两个目录的命名含义无文档记载。`1/README1.md` 仅描述其为「独立示例/旧版脚本」，未说明是否为编号方案。因此归档时**不沿用编号命名**，改为 `legacy-1`、`legacy-3`，避免暗示未经证实的含义。

> 该要求在本项目中权重高于常规——因为 §3.5 的注释污染已使 40 个文件的内容可读性受损，**「位置」承载的信息比平时更重要**。

**不进归档的**：

- 15 个运行时模块 → 进 `app/`
- `enhanced_bridge_templates/` **+** `download_enhanced_open_models.py` → **成对**放入研究模块资产区。理由：研究模块是活的（仅被配置关闭），模板不是死文件；且两者存在路径引用关系（规则 1）
- `index.html`、`pcm-processor.js` 等前端运行文件

**空目录处理**：`steploc/`、`templates/`、`static/` 为空目录。git 不跟踪空目录，它们不会出现在任何一次 clone 中，「保留」对其无意义。建议从工作区移除。`diagnose_agora.py:120` 引用的 `static/favicon.ico` 本就不存在，属已损坏引用。

### 4.4 配置

| 项 | 现状 | 目标 |
|---|---|---|
| 格式 | `.env`（单一文件） | 分环境：`config/env/.env.development` + `.env.production`，由 `APP_ENV` 选择 |
| 模板 | 无 | `.env.example`（**仅键名，无值**，纳入版本控制） |
| 密钥 | 开发与生产**共用生产凭据**（§3.10） | **开发环境不得持有生产凭据** |
| 失败行为 | 缺文件**静默回退默认值** | **缺失即拒绝启动**，报错指明期望路径 |
| 运行时可变 | 3 个 `RESEARCH_*` 键写入 `.env` | 见下 |
| `APP_HOST`/`APP_PORT` | 已定义但**未被使用**（`server.py:6554` 写死 `0.0.0.0:8000`） | 改为实际生效 |

**三项具体改造**（针对 §3.10 实测）：

1. **删除静默 `return`**（`config.py:12-13`）→ 选择的环境文件不存在时**抛错退出**，并打印期望路径与当前 `APP_ENV`
2. **删除 `DATABASE_URL` 的 sqlite 默认值**（`config.py:177`）→ 未配置即拒绝启动。**这一条是让 1.2 类故障从"不可见"变为"不可能"的关键**
3. **`_write_env_updates()` 写入目标限定为当前环境文件**，且在 `APP_ENV=production` 时拒绝写入

**范围（D14）**：

| | 本次做 | 留待办 |
|---|---|---|
| 开发环境 | ✅ 完整实现：本地库配置、`.env.development`、模板、失败即报错 | |
| 切换机制 | ✅ 完整实现：`APP_ENV` 选择逻辑 + 校验 | |
| 生产环境 | | ⏳ `.env.production` 的**真实键值**（无生产机访问）<br>⏳ 线上实际在用键名的**核对**（§8.1） |

> **开发环境改造完成后将获得一项可验证的安全属性**：本机开发**在物理上无法触及生产库**——不是因为自律，而是因为凭据根本不在开发配置里。这直接消除了 §3.9 记录的那类风险。

**运行时改配置的处理**：`POST /api/research-runtime/config` 在 `persist=true` 时经 `persist_research_runtime_config()` → `_write_env_updates()` **改写 `.env` 文件**。仅涉及 3 个键，且当前为惰性状态（`standard` / `enabled=false` / 模型槽位为空）。容器化时需三选一：

- (a) 改写入可写卷
- (b) 只读环境下禁用该端点
- (c) 保留为开发环境专用

> 该决策延至阶段 5，需在容器化设计时确定。

### 4.5 部署

```
deploy/
├── docker-compose.dev.yml     # 本地开发
├── docker-compose.prod.yml    # 生产
├── Dockerfile
├── nginx/                     # 【纳入版本控制】原 /etc/nginx/ 手工配置
└── README.md                  # 替换现有陈旧文档
```

**nginx 必须纳入**：§3.6 的三项生产关键设置只存在于 nginx。容器化时若不纳入编排，将出现「容器正常启动、上传失败、长连接掉线」。

**数据库禁止初始化**：容器**只能连接既有数据库，不得建库、不得迁移**。依据是 C6 与 §3.8——生产库有 3 张表、6 个列不在 ORM 中，任何以 ORM 为依据的建库或迁移都会造成结构丢失。容器编排中**不得出现** `create_all`、迁移脚本或数据库初始化步骤。

**现有 `deploy/` 与 `DEPLOYMENT.md` 为陈旧资料**：`DEPLOYMENT.md` 内容完整重复两遍（1–676 行 == 677–1234 行），描述 MySQL/pymysql/3308，与实际实现（SQL Server/pymssql/3433）不符。不可作为容器化基线。

---

## 5. 关键风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 文件移动触发 §3.1 静默失效 | **高** | 高 | **阶段 0 先行**统一锚点，并加入启动自检断言数据源 |
| 重构改变行为且未被发现 | 中 | 高 | 阶段 1 建立测试基线，此后每次改动自动验证 |
| 路由前缀被改动导致 nginx 断裂 | 中 | 高 | 建立「路由前缀契约」并在测试中断言 |
| 容器化遗漏 nginx 能力 | **高** | 中 | §4.5 明确纳入；阶段 5 验收含上传与长连接 |
| `[EMOJI]` 污染导致语义误读 | 中 | 中 | 阶段 0 先补齐 `database.py` 等关键文件的注释 |
| 重构期间并行开发冲突 | 中 | 中 | 建议冻结业务功能开发，或先在独立分支完成阶段 0–2 |
| 阶段 3–7 工期估算偏差 | 中 | 中 | 阶段 1 完成后基于实测重新精算 |

---

## 6. 分阶段设计

| 阶段 | 内容 | 验收标准 | 预计人日 |
|:---:|---|---|---|
| 0 | 路径锚点统一 + 冒烟基线 | 从任意目录启动均指向同一数据源；基线可稳定复现 | 1–2 |
| 1 | 测试体系建立 | 一条命令跑通；确认无任何写生产库路径 | 3–5 |
| 2 | 依赖版本固化 | 全新环境可一次性复现启动 | 0.5–1 |
| 3 | 后端结构重构 | 阶段 1 测试全绿；接口契约不变 | 8–15 |
| 4 | 配置改造 | 密钥不再出现于仓库；切换环境无需改代码 | 3–5 |
| 5 | 容器化（含 nginx） | 一条命令起本地环境；远程部署可复现 | 3–5 |
| 6 | 前端 ②a 工程化 | 构建产物与现网行为逐项一致 | 4–7 |
| 7 | 前端 ②b 组件拆分 | 功能逐项对照通过 | 8–15 |

### 6.1 实施计划的粒度

**本文是整体架构设计，不是实施计划。** 8 个阶段跨度约 30–55 人日，不适合纳入单个实施计划。实施计划**按阶段分批制定**：

- **第一批：阶段 0–2**（约 5–8 人日）——范围小、边界清晰、估算可靠。完成即已建立重构的安全性
- **第二批：阶段 3–7**——在**阶段 1 完成后**，基于实测的测试覆盖率与代码依赖关系重新精算，再制定实施计划

理由：阶段 0–2 的产出（路径统一、测试基线、版本固化）会显著改变后续阶段的风险画像与工作量估算。在获得这些实测数据前制定阶段 3–7 的详细计划，其精度不可靠。

### 阶段 0：路径锚点统一 + 冒烟基线 · **锚点部分已完成（2026-10-01）**

**这是后续全部工作的前置。**

**1. 路径锚点统一 —— ✅ 已完成**

实现方式**与原设计有偏差**：

| | 原设计 | 实际采用 | 理由 |
|---|---|---|---|
| 方式 | 新增 `core/paths.py` 作为唯一路径来源 | `ROOT_DIR = BASE_DIR` 一行别名 + C 类逐处显式锚定 | `core/paths.py` 需先建立包结构，属阶段 3 的工作；阶段 0 只需**消除 cwd 依赖**这一安全属性，用最小改动先拿到它 |

改动共 **9 处 hunk / 21 行**（全部在 `server.py`）：

- **B 类**：`server.py:71` `ROOT_DIR = os.getcwd()` → `ROOT_DIR = BASE_DIR`，一行覆盖全部 12 处引用
- **C 类**：9 处裸相对字面量逐处改为 `os.path.join(BASE_DIR, ...)`
- **D 类 7 处一律未动**（§3.1）
- **未删除任何文件**；四个空目录按 D16 移除

**验收证据（实测）**：

| 检查项 | 结果 |
|---|---|
| 从项目根启动时 7 个路径的解析 | **全部同一路径（差异 0/7）** → 行为不变 |
| 从其他目录启动时 7 个路径的解析 | **全部由错误目录修正为项目目录（差异 7/7）** → 缺陷消除 |
| `py_compile server.py` | 通过 |
| D 类 URL 字符串计数 | 仍为 7，未被误伤 |

> **附带发现**：`/voiceprint_register`（`server.py:6302`）指向的 `voiceprint_register.html` **全仓不存在**，该路由必然抛 `FileNotFoundError`。**本次仅锚定，未修复**（C1）。列入阶段 3 待查。

> **遗留风险**：本次改动使 `server.py` 在 git 中触发 `LF will be replaced by CRLF` 警告。属既有仓库配置缺失，若不加处理，未来某次检出可能重写整个文件的行尾符、污染全部 diff。**须在阶段 3 大规模搬迁前以 `.gitattributes` 处理**。

**2. `core/paths.py`（含环境变量覆盖）—— 顺延至阶段 3 / 阶段 5**

环境变量覆盖是容器化（阶段 5）的需要，包结构是阶段 3 的产物。锚点安全属性已由上述最小改动**提前取得**，无需等待。

**3. 启动自检 —— 并入阶段 4**

原设计为「回退到默认 SQLite 则报错退出」。该逻辑与 §4.4 删除 `DATABASE_URL` 默认值是**同一处改动**，合并实施更自然。

**4. 冒烟基线 —— 待做**

59 个路由的基线响应记录。**按 D17，不需要连生产库**：本地按 ORM 建库即可，见 §7.3。

**为什么最先做**：不统一锚点，任何文件移动都在触发 §3.1 的静默失效。

### 阶段 1：测试体系

见 §7。

### 阶段 2：依赖版本固化 · **降级为待校验**（D13）

```bash
pip freeze > requirements.lock.txt    # 本机执行；生产机校准为待办
```

**原定目标**：锁定到**线上正在运行的版本**。
**实际执行**：无生产机访问，只能固化**本机已验证可启动**的版本组合。

**降级方式**：产物文件名与首行注释均**显式标注**——

```
# 待校准：本文件固化自开发机，非线上升级版本。
# 待生产机可访问后，须以生产机 pip freeze 输出替换并复核。
```

> 关键区别：固化本机版本**仍能解决**「每次重建环境结果不同」这一实际问题（§1.1 的故障就此不再复现）；但它**不能主张**与线上一致。故降级为待校验，而非取消。

### 阶段 3：后端结构重构

按 §4.1 结构搬迁。**约束**：路由前缀不变；接口契约不变；函数内导入一并消除（D3）。

### 阶段 4：配置改造 · **开发环境先行**（D14）

按 §4.4 实施。**本次范围：开发环境完整落地 + 环境切换机制**。生产侧键值与线上键名核对列为待办。

### 阶段 5：容器化 · **仅本地开发**（D15）

按 §4.5 实施，**必须包含 nginx 服务**。验收需覆盖：大于 1MB 的文件上传、长时 WebSocket 连接（>60s）、HTTPS。

**本次范围**：本地开发环境容器化（`docker-compose.dev.yml` + `Dockerfile`）。
**留待办**：`docker-compose.prod.yml` 与线上部署指令——其内容依赖生产机实况（Python 版本、依赖版本、配置键名、nginx 落点），**现阶段只能写模板，不能声称可复现**。

### 阶段 6 / 7：前端

按 §4.2 实施。阶段 7 在阶段 6 完成后启动。

---

## 7. 测试策略

### 7.1 工具栈

| 工具 | 用途 |
|---|---|
| `pytest` | 测试框架（当前未安装，需加入依赖） |
| `httpx.ASGITransport` | FastAPI 官方测试方式，不需启动真实服务 |
| `pytest-asyncio` | WebSocket 测试 |
| `syrupy` | 快照断言（适合「行为不变」类断言） |

### 7.2 两个必做动作

1. **抢救已有测试**：`tests/` 下 59 个 pytest 用例可复用，但需逐条审查——弱断言需收紧（`assert status_code in [200,400,422]` 无意义），与端点实际契约不符的需修正
2. **生产库隔离**：**这是安全前置，不可选**。当前 38 处写操作直连生产库，必须改为指向本地测试库，并加入断言确保任何测试路径都不会命中生产库

### 7.3 测试数据库（B 方案）

| 来源 | 内容 | 含 PII |
|---|---|---|
| 生产库**只读** | schema（列名、类型、长度、可空） | 否 |
| 本地生成 | 合成中文 fixture | 否 |

**基准在本地库上录制**，不在生产库录制——若基准来自生产而测试跑在本地，二者永不匹配。

**为何仍需只读 schema**：`init_db.py` 只建 15 张表中的 5 张，且其 DDL 与 ORM 有出入。**该盲区已实测确认存在**（见 §3.8）：生产库 18 表、ORM 15 表，`transcripts` 另多 6 列。若本地按 ORM 建库、测试全绿而生产不一致，则测试反而会掩盖问题。

**状态：已完成**（2026-10-01）。采集结果与差异清单一并存档于 `docs/production-schema-drift.md`，采用只读 `INFORMATION_SCHEMA.COLUMNS`，未读取任何一行数据。

**由此确立的约束**：本地测试库按 ORM 建立是安全的，**但必须记录：它与生产库结构不一致**，因此结构层面的测试结论不能直接外推到生产。生产库**禁止**以 ORM 重建（C6）。

### 7.4 部署形态验证

测试直连 uvicorn，**不经过 nginx**，因此反代层问题（如 §3.6 的 WebSocket 前缀不匹配）测试永远发现不了。需单独加一层部署形态验证，覆盖：

- 通过 nginx 的 WebSocket 握手（`/ws/` 与 `/ws-asr/` 两个路径）
- 大于 1MB 的上传
- 长时连接（>60s）

### 7.5 测试无法覆盖的部分

- 外部依赖（阿里云 NLS、DeepSeek、Agora）的真实行为，只能 mock，而 mock 的契约可能与现实不符
- 11299 行的前端：自动化验证成本可能高于重构本身

---

## 8. 前置条件与待确认事项

### 8.1 需需求方提供（阻塞阶段 2）

- 生产机 `pip freeze` 输出
- 生产机 Python 版本
- 生产机 `.env` 键名清单（**不含值**）

### 8.2 需需求方批准（已办结）

- ~~生产库只读 schema 查询授权（§7.3）~~ —— **已授权并执行**（2026-10-01），结果见 §3.8
- ~~业务表时间戳存活探测授权~~ —— **已授权并执行**（2026-10-01），结果见 §3.9

### 8.3 需需求方核实

- **nginx 是否实际在线上运行**（§3.6）。确认方法：
  ```bash
  nginx -T | grep -n 'location'
  ```
  或 WebSocket 握手探测：
  ```bash
  curl -i -N --max-time 10 \
    -H "Connection: Upgrade" -H "Upgrade: websocket" \
    -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
    https://<实际域名>/ws-asr/test/1
  ```
  `101` = 正常；`403`/`400` = 确认故障
- ~~**`assets/` 目录的用途**~~ —— **已查明**：`assets/css`、`assets/img`、`assets/js` 三个子目录**均为空**，`assets/` 下**共 0 个文件**。确认为 CDN 化之前的残留骨架，已按 D16 移除
- **部署入口域名**：`smartclass1.top` 当前返回 403（`Server: Beaver`），需确认现用入口

### 8.4 需需求方决策

- ~~`steploc/`、`templates/`、`static/` 三个空目录是否移除~~ —— **已决策：移除**，并追加确认 `assets/` 同为空的第四个（D16）
- ~~§4.4 运行时改配置的处理方式~~ —— 本地开发容器化采用 **(a) 写入可写卷**；生产侧随阶段 5 待办一并确定

### 8.5 本轮新增待办事项（因无生产机访问而挂起）

| # | 待办 | 阻塞 | 恢复条件 |
|---|---|---|---|
| T1 | 生产机 `pip freeze` 校准依赖版本 | 阶段 2 的最终验收 | 可登录生产机 |
| T2 | 生产环境配置的键名清单核对 | 阶段 4 生产侧 | 同上 |
| T3 | `docker-compose.prod.yml` 与线上部署指令 | 阶段 5 生产侧 | 同上 |
| T4 | 前端 CDN 资源本地化可行性确认 | 阶段 6 | 需确认是否允许改动前端资源来源 |
| T5 | 域名 `smartclass1.top` 当前状态与现用入口 | §3.6 结论 | 可访问或可登录服务器 |

> 上述待办**不阻塞阶段 0、1、3、6、7**。设计原则：**凡需要线上实况的校验一律挂起，凡可在本地闭环的一律推进。**

---

## 9. 非目标

以下事项**不在本次范围内**：

- 更换依赖管理工具（uv）——已决策跳过（D6）
- 删除任何文件（C2）
- 判断哪些功能是「未完成」或「已弃用」——不可从代码推导，且有权属风险
- 修复已发现的线上故障（如 `/ws-asr/` 的 nginx 前缀问题）——**应单独定位、单独修复**，不与结构重构混合
- 业务逻辑优化、性能优化、功能新增

---

## 10. 最终验收标准

1. 全部测试通过，且确认测试过程**不触碰生产数据**
2. 从任意目录、任意机器可一次性复现完整运行环境
3. 生产密钥不再出现于项目目录
4. 59 个对外接口的输入输出与重构前**完全一致**（快照比对）
5. 重启后可复现 §3.1 的故障场景而不出现数据错位
6. 容器化后可完成：大于 1MB 上传、超过 60s 的 WebSocket 连接、HTTPS 访问
7. 全部文件已归档或纳入新结构，**无文件丢失**（搬迁前后文件清单比对）
8. 重构前后**生产库结构未发生任何变化**——以 `docs/production-schema-drift.md` 的清单为准复核，表数仍为 18、`transcripts` 列数不变（C6）
