# Gemma 接入重构执行文档（阿里云 ASR 保持不变）

版本：v1.0  
更新日期：2026-04-10  
适用项目：`algorithm-study-master`

---

## 1. 文档目标

这份文档用于指导团队在**不改动阿里云语音识别主链路**的前提下，将当前项目的 LLM 能力从“硬编码 DeepSeek”重构为“可配置多 Provider（优先接入 Gemma）”。

本次重构的核心目标：

1. ASR 保持现状：继续使用阿里云 API（文件识别 + 实时 WebSocket）。
2. LLM 接入 Gemma：通过 Ollama 本地模型 `gemma4:e2b` 承载文本分析能力。
3. 统一调用层：所有 LLM 调用统一走 `llm_service`，禁止在业务路由内直接写 `llm.client.chat.completions.create(...)`。
4. 配置与安全合规：移除明文密钥，统一改为环境变量读取。
5. 可灰度、可回滚：保留 DeepSeek 作为应急回退通道。

---

## 2. 现状盘点（当前代码基线）

### 2.1 ASR 现状（本次不替换）

1. 阿里云 Token 与识别逻辑：`ai_core.py`
2. 文件切片识别调用：`process_user_stream_generator` 中 `engine.transcribe_audio(a_path)`  
3. 实时 ASR 会话：`RealtimeTranscriber` + `ASRSessionManager`

关键代码位置：

- `ai_core.py:11`（阿里云配置）
- `ai_core.py:73`（`AIEngine.transcribe_audio`）
- `ai_core.py:185`（`RealtimeTranscriber`）
- `server.py:224`（切片流处理）
- `server.py:1402`（`ASRSessionManager`）
- `server.py:1525`（`/ws-asr`）

结论：ASR 主链路已经稳定，按你要求本次不切换到 FunASR。

### 2.2 LLM 现状（本次重点改造）

当前存在 3 类问题：

1. 配置硬编码  
- `llm_service.py:9`、`llm_service.py:10` 写死了 API Key 和 Base URL。

2. 模型硬编码  
- `llm_service.py` 多处硬编码 `model="deepseek-chat"`。

3. 调用路径不统一  
- 大多数功能走 `llm_service`，但仍有路由直接调底层 client：
  - `server.py:2103`（`/api/suggest-topic`）
  - `server.py:3433`（`/api/quiz-error-analysis`）

---

## 3. 重构范围与非范围

## 3.1 范围（In Scope）

1. LLM 配置治理（`.env` 化）。
2. LLM Provider 抽象（Ollama/Gemma + DeepSeek fallback）。
3. 业务路由的 LLM 调用收口至服务层。
4. 接入 Gemma 后的性能保护（超时、降级、缓存、回退）。
5. 文档、测试、运维脚本更新。

## 3.2 非范围（Out of Scope）

1. 替换阿里云 ASR 为 FunASR/Whisper。
2. 重写前端 ASR 协议（`asr_partial`/`asr_final` 保持现有协议）。
3. 改造数据库业务结构（仅做必要配置安全调整）。

---

## 4. 目标架构（重构后）

### 4.1 高层架构

1. 语音链路：
- 浏览器音频 -> `ws-asr` -> 阿里云 NLS -> `asr_partial`/`asr_final` -> 前端

2. 文本分析链路：
- 业务路由 -> `llm_service` -> `LLM Adapter` -> `Gemma (Ollama)`  
- 失败时：`Gemma` 超时/格式错误 -> fallback 到 `DeepSeek`（可开关）

### 4.2 配置驱动

新增环境变量（建议）：

```env
# 基础
APP_ENV=dev
LOG_LEVEL=INFO

# ASR（继续阿里云）
ALIYUN_ACCESS_KEY_ID=
ALIYUN_ACCESS_KEY_SECRET=
ALIYUN_APP_KEY=

# LLM Provider
LLM_PROVIDER=ollama          # ollama | deepseek
LLM_MODEL=gemma4:e2b
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama           # Ollama OpenAI 兼容模式可填占位符
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2

# Fallback
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_PROVIDER=deepseek
LLM_FALLBACK_MODEL=deepseek-chat
LLM_FALLBACK_BASE_URL=https://api.deepseek.com
LLM_FALLBACK_API_KEY=

# DB
DATABASE_URL=
```

---

## 5. 详细改造清单（按文件）

## 5.1 新增文件

1. `config.py`
- 负责读取环境变量、参数校验、默认值策略。
- 对外暴露：`settings.llm`, `settings.asr`, `settings.db`。

2. `.env.example`
- 提供所有必填和可选变量模板。
- 明确哪些变量可留空、哪些必须配置。

3. `tests/test_llm_adapter.py`
- 覆盖 provider 路由、fallback、异常兜底、JSON 清洗行为。

4. `tests/test_llm_endpoints.py`
- 覆盖 `/api/ai-tutor`、`/api/suggest-topic`、`/api/quiz-error-analysis`。

## 5.2 修改文件：`llm_service.py`

目标：从“DeepSeek 专用实现”升级为“可配置多 Provider 实现”。

具体改造项：

1. 移除硬编码常量  
- 删除（或废弃）`API_KEY`, `BASE_URL` 常量。  
- 改为从 `config.py` 读取。

2. 统一 client 初始化  
- `self.client = OpenAI(api_key=..., base_url=..., timeout=..., max_retries=...)`
- 增加 `self.fallback_client`（当 fallback 开启）。

3. 新增统一请求方法（建议）
- `_chat_once(messages, model, temperature, max_tokens, stream=False)`
- `_chat_with_fallback(...)`
- `_chat_json_with_fallback(...)`
- 作用：把重试、日志、fallback、耗时统计集中到一个入口。

4. 替换所有硬编码模型  
- 将全部 `model="deepseek-chat"` 改为 `model=self.model` 或调用参数注入。

5. 强化结构化输出兼容  
- `Gemma` 场景不强依赖 `response_format`。  
- 改为“提示词强约束 + `_clean_json` + `_validate_and_complement`”三层兜底。

6. 增加链路日志
- 记录 `provider/model/latency/success/fallback_used`。

7. 保持现有方法签名不变
- `analyze_speech_and_progress`
- `generate_course_report`
- `generate_exercises`
- `ai_tutor` / `ai_tutor_stream`
- 目标：尽量不改调用侧。

## 5.3 修改文件：`server.py`

目标：业务层只依赖 `llm_service`，不直接访问底层 client。

具体改造项：

1. 收口 `/api/suggest-topic` 的直接 client 调用  
- 当前：`server.py:2103` 直接 `llm.client.chat.completions.create`。  
- 改为：新增 `llm.suggest_topic_from_context(...)` 并调用该方法。

2. 收口 `/api/quiz-error-analysis` 的直接 client 调用  
- 当前：`server.py:3433` 直接调用。  
- 改为：新增 `llm.analyze_quiz_errors(...)`。

3. 保持 ASR 路径不动  
- `process_user_stream_generator` 中 `engine.transcribe_audio(a_path)` 不改。
- `/ws-asr` 不改协议。

4. 错误回包统一  
- 路由层只负责返回用户友好错误，技术错误写日志。

## 5.4 修改文件：`ai_core.py`

目标：仅做安全配置治理，不改识别逻辑。

具体改造项：

1. 阿里云 AK/SK/APP_KEY 改为环境变量读取。
2. 启动时校验关键配置缺失并打印明确告警。
3. 保持 `AIEngine` / `RealtimeTranscriber` 业务逻辑不变。

## 5.5 修改文件：`database.py`

目标：数据库连接串改为环境变量读取。

具体改造项：

1. 删除硬编码连接串。
2. 增加 `DATABASE_URL` 缺失时的明确错误信息。
3. 兼容开发环境默认值（如有）。

## 5.6 修改文件：文档与部署

1. `README.md`
- 增加 Gemma 接入说明。
- 增加 Ollama 安装与模型拉取命令。

2. `DEPLOYMENT.md`
- 增加环境变量清单。
- 增加服务启动顺序（先 Ollama，再后端）。

---

## 6. 5 人分工方案（可直接执行）

## 6.1 分工总览

1. P1（架构/配置负责人）  
范围：`config.py`、`.env.example`、`database.py`、`ai_core.py` 配置改造。  
输出：配置中心 + 密钥下沉 + 启动校验。

2. P2（LLM 内核负责人）  
范围：`llm_service.py`。  
输出：Provider 抽象、Gemma 主通道、fallback 机制、统一日志。

3. P3（业务路由负责人）  
范围：`server.py` 中全部 LLM 调用收口。  
输出：`/api/suggest-topic`、`/api/quiz-error-analysis` 改造 + 错误处理统一。

4. P4（测试与质量负责人）  
范围：`tests/*`、回归脚本。  
输出：单测 + 集成测试 + 回归报告（功能、性能、异常）。

5. P5（部署与文档负责人）  
范围：`README.md`、`DEPLOYMENT.md`、上线手册。  
输出：本地开发指南、灰度发布步骤、回滚手册。

## 6.2 每人详细任务（含验收标准）

### P1 任务

1. 新建 `config.py` 并完成环境变量读取。
2. `database.py` 改为读取 `DATABASE_URL`。
3. `ai_core.py` 改为读取阿里云变量。
4. 新建 `.env.example`。

验收标准：

1. 仓库源码不再包含真实密钥。
2. 缺少关键变量时，服务启动日志可定位问题。

### P2 任务

1. `llm_service.py` 接入 `LLM_PROVIDER=ollama`。
2. 将 `deepseek-chat` 硬编码替换为动态模型。
3. 增加 fallback。
4. 新增统一方法，减少重复调用代码。

验收标准：

1. 设置 `LLM_PROVIDER=ollama` 时，`/api/ai-tutor` 可返回正常内容。
2. Gemma 失败时可自动回退 DeepSeek（开关可控）。

### P3 任务

1. 把 `server.py:2103` 路由改为走 `llm_service`。
2. 把 `server.py:3433` 路由改为走 `llm_service`。
3. 全链路检查是否还有直调 `llm.client`。

验收标准：

1. `rg "llm.client.chat.completions.create" server.py` 结果应为 0。
2. 上述 2 个接口行为与原有协议兼容。

### P4 任务

1. 新增单元测试：JSON 解析、fallback、异常兜底。
2. 新增接口测试：`ai-tutor`、`suggest-topic`、`quiz-error-analysis`。
3. 压测：并发 10 用户，记录 P50/P95 延迟。

验收标准：

1. 核心测试全部通过。
2. 无阻断性回归（语音链路、报告链路、课堂交互链路）。

### P5 任务

1. 更新 `README.md`（本地 Gemma 使用步骤）。
2. 更新 `DEPLOYMENT.md`（生产变量、回滚步骤）。
3. 输出《上线检查清单》。

验收标准：

1. 新同学按文档可在 30 分钟内跑通本地开发环境。
2. 上线与回滚步骤可直接执行。

---

## 7. 分阶段实施计划（建议 7 天）

## Day 1：安全与配置基线

1. 完成 `config.py` 和 `.env.example`。
2. 密钥改造：`database.py`、`ai_core.py`、`llm_service.py`。
3. 本地启动验证（保持 ASR 正常）。

## Day 2：LLM Provider 内核改造

1. 完成 `llm_service.py` provider/fallback 改造。
2. 验证 `LLM_PROVIDER=deepseek` 不回归。
3. 验证 `LLM_PROVIDER=ollama` 可用。

## Day 3：业务路由收口

1. 改 `/api/suggest-topic`。
2. 改 `/api/quiz-error-analysis`。
3. 全量扫描直调 client。

## Day 4：Gemma 质量调优

1. 优化提示词长度与输出格式约束。
2. 缩短重型任务 `max_tokens`，控制延迟。
3. 调整缓存策略，减少重复请求。

## Day 5：测试与修复

1. 单测 + 接口测试。
2. 并发压测与异常场景测试。
3. 修复回归问题。

## Day 6：灰度发布

1. 先将 `ai-tutor` 切到 Gemma。
2. 观察日志与延迟。
3. 再逐步放量到其他文本接口。

## Day 7：全量与复盘

1. 全量启用或保持双通道。
2. 产出性能对比报告与后续优化清单。

---

## 8. 接口迁移优先级（Gemma 接入顺序）

优先接入（低风险）：

1. `/api/ai-tutor`
2. `/api/ai-tutor-stream`
3. `/api/suggest-topic`

中风险（结构化输出要求更高）：

1. `analyze_speech_and_progress`
2. `quick_decompose`
3. `cluster_viewpoints`

高风险（长文本、复杂结构）：

1. `generate_course_report`
2. `generate_exercises`
3. `quiz-error-analysis`

---

## 9. 性能与稳定性策略

1. 保护策略
- 每类任务设置不同 `max_tokens`。
- 关键接口设置超时（建议 45~60s）。
- 对结构化任务启用“失败兜底默认值”。

2. 缓存策略
- 保留现有 LRU 缓存。
- 对重复 prompt 做 key 归一化。

3. 回退策略
- `LLM_FALLBACK_ENABLED=true` 时，Gemma 失败自动回退 DeepSeek。
- 失败日志必须记录 provider 和错误类型。

4. 降级策略
- Gemini/Gemma 拥塞时，优先保证课堂主流程（ASR + 实时消息）。
- 可暂时关闭非关键生成任务（如材料推荐）。

---

## 10. 风险清单与应对

1. 风险：Gemma 结构化 JSON 不稳定  
应对：严格提示词 + `_clean_json` + `_validate_and_complement` + fallback。

2. 风险：本地推理延迟偏高（6GB 显存）  
应对：限制长任务并发、缩短上下文、将重任务保留 DeepSeek。

3. 风险：改造时引入接口行为变化  
应对：保持返回字段不变，先测后放量。

4. 风险：密钥迁移不完整导致启动失败  
应对：启动时做显式配置检查，提供 `.env.example`。

---

## 11. 回滚方案（必须预演）

1. 保留 `LLM_PROVIDER=deepseek` 一键回切能力。
2. 发布时先备份 `.env` 与上一个稳定版本。
3. 如出现大面积超时/错误，立即执行：

```bash
# 示例（按你们部署方式调整）
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
restart server
```

4. 回滚后保留日志用于问题定位，不做强制清表或破坏性操作。

---

## 12. 交付验收清单（DoD）

1. 功能
- 阿里云 ASR 全链路保持可用。
- Gemma 可稳定服务 `ai-tutor` 与至少 2 个业务文本接口。
- 所有路由不再直调 `llm.client`。

2. 安全
- 仓库中不再出现真实 AK/SK/API Key/DB URL。
- `.env.example` 完整。

3. 稳定性
- 并发课堂下接口无明显阻塞。
- fallback 生效可观测。

4. 文档
- `README.md`、`DEPLOYMENT.md`、本执行文档全部更新。

---

## 13. 推荐分支与 PR 计划

建议分支：

1. `refactor/config-env-hardening`（P1）
2. `refactor/llm-provider-gemma`（P2）
3. `refactor/server-llm-call-unify`（P3）
4. `refactor/tests-gemma-migration`（P4）
5. `refactor/docs-gemma-rollout`（P5）

建议 PR 标题：

1. `refactor(config): move secrets to env and add centralized settings`
2. `feat(llm): add provider abstraction with ollama gemma and fallback`
3. `refactor(api): remove direct llm client calls from routes`
4. `test(llm): add adapter and endpoint regression tests`
5. `docs: add gemma integration and deployment rollback guide`

---

## 14. 本地启动最小步骤（Gemma 方案）

1. 启动 Ollama 并拉模型：

```bash
ollama pull gemma4:e2b
```

2. 设置环境变量（Windows PowerShell 示例）：

```powershell
$env:LLM_PROVIDER="ollama"
$env:LLM_BASE_URL="http://127.0.0.1:11434/v1"
$env:LLM_API_KEY="ollama"
$env:LLM_MODEL="gemma4:e2b"
$env:LLM_FALLBACK_ENABLED="true"
$env:LLM_FALLBACK_PROVIDER="deepseek"
```

3. 启动后端：

```bash
python server.py
```

4. 快速验证：

1. 进入课堂，确认 `ws-asr` 转写正常（阿里云链路）。
2. 调用 `/api/ai-tutor`，确认返回来自 Gemma。
3. 模拟失败，确认 fallback 生效。

---

## 15. 追加建议（下一阶段）

1. 把 `llm_service.py` 继续拆分成 `adapter/prompt/task` 三层，降低单文件复杂度。
2. 引入指标埋点（Prometheus 或简单日志聚合）观察每个接口成功率和耗时。
3. 对“重型任务”引入队列化或异步化，避免挤占课堂实时链路资源。

