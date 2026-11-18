# 三维投入与 Hint：Agent 侧补充契约

> 状态：v1.0 草案，配合 `docs/engagement_protocol.md`（GCA 组，feat/gca）使用。
> 适用范围：系统/Agent 侧接入 GCA 的三维投入结果与 Hint 候选。
> 本文只定接口与职责边界；表结构和接口在后续 PR 实现。

## 1. 采纳基线

- GCA 侧唯一入口：
  - `compute_hint_candidates(meeting_id, utterances, now_second, state, online_members)`
  - `HintCandidate` 字段以 `docs/engagement_protocol.md` 第 7 节为准。
- 三维结果结构以 `EngagementDimensionResult` / `EngagementResult` 为准，
  状态分层不变：整体 `AnalysisStatus` 7 值，维度 `ok / insufficient / unavailable`。
- 本轮不计算 E_e / E_b / E_c 综合分。`insufficient` / `unavailable`
  只表示数据可用程度，不解释为学习投入低，也不展示给学生。
- 时间基准：课堂开始后的相对秒数。课堂侧换算以 `meeting.started_at`
  为零点，缺失时退回最早一条转写（与 `app/services/gca_service.py` 一致）。
  情绪、转写、质量分必须使用同一零点，不得各自按最早记录换算。
- 指标名统一用 `quality_coverage`（认知模块实现）。协议样例中的
  `quality_score_coverage` 视为笔误，不再使用。

## 2. 四个待确认项的决定

### 2.1 旧 Hint 接口与新候选的关系

决定：**复用生成与发送流程，判断逻辑只保留一份。**

- 判断统一由 `compute_hint_candidates` 产出；旧接口里
  `is_group_silent` / `get_quiet_members` 的直接判断改为消费候选。
- `/api/check-silence`、`/api/check-quiet-members` 暂时保留，作为
  “立即检查一次”的兼容入口，返回结构不变；内部走同一个评估器。
- 前端 30 秒/60 秒轮询在服务端评估器上线后移除，避免两套定时器双触发。
- LLM 生成、教师确认、WebSocket 发送、`HintLog` 写入仍由 Agent 侧负责，
  GCA 不调 LLM、不发送消息。
- 同一条提示只能有一个来源：候选的 `dedupe_key` 作为发送级冷却键，
  旧接口与定时评估器共用。

### 2.2 在线成员名单

决定：**由 Agent 侧传入，格式 `list[str]`，元素为 `str(User.id)`。**

- 来源是 WebSocket 连接表 `manager.get_online_members(meeting_id)`
  （返回连接时使用的 username/student_id），再按 `User.username` 或
  `User.student_id` 映射到 `User.id`。
- 教师必须排除；映射不到的用户直接省略，不猜测、不补位。
- 一个都映射不到时传 `None`，退回 GCA 的“已知发言人”判断池，
  避免把从未发言的在线学生误判为低参与。
- 空列表表示确实无人在线，不产出候选。

### 2.3 评估周期由哪一侧驱动

决定：**Agent 侧驱动，GCA 不持有定时器。**

- 每个 `running` 课堂每 30 秒评估一次，与滑动窗口步长一致；
  收到新的最终转写时也可以顺带评估，但同一 `dedupe_key` 受冷却约束。
- `created` / `ended` 课堂不评估。
- 生产 `docker-compose.prod.yml` 固定 `--workers=1`，在线连接表只存在于
  该进程。评估器跟随 WebSocket 进程运行；若将来扩到多 worker，
  需先把在线名单与冷却状态移到共享存储，本次不做。

### 2.4 提示发送与冷却

- 候选级冷却由 GCA 的 `dedupe_key` 负责；发送级冷却由 Agent 记录，
  学生 120 秒、小组 300 秒，与协议配置一致。
- 教师确认后发送；未确认的候选默认不发送。是否开放“自动发送”由后续开关决定，
  本期不做。
- 发送失败要落 `HintLog.status=failed`，不静默吞掉。

## 3. 证据 ID

Agent 生成和落库时，把 GCA 的数值证据补成可回查的 ID 列表：

| 前缀 | 指向 | 示例 |
|---|---|---|
| `T#` | `transcripts.id` | `T#12345` |
| `M:` | `meetings.id` | `M:88` |
| `Q:` | 该发言的质量评分（`transcripts.id`） | `Q:12345` |
| `E:` | `emotion_logs.id` | `E:9001` |
| `H#` | `hint_logs.id` | `H#17` |

规则：

- 结论必须挂至少一个证据 ID；缺数据写进 `data_gaps`，不编造。
- 新旧模型结果不一致时并列展示，不取平均（计划 9.5）。
- GCA 候选自带的 `evidence` 数值原样保留，ID 列表另存，二者不互相替代。

## 4. 存储（后续迁移实现）

字段为本期最小集，实际类型以 SQL Server 迁移为准。

### `engagement_curves`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| meeting_id | 课堂 |
| user_id | 学生；小组行为空 |
| dimension | `emotional` / `behavioral` / `cognitive` |
| window_start_second / window_end_second | 相对秒数 |
| metrics | JSON，维度指标 |
| status | `ok` / `insufficient` / `unavailable` |
| protocol_version | 契约版本 |
| created_at | 写入时间 |

索引：`(meeting_id, dimension, window_start_second)`；
按 `meeting_id + user_id` 查询学生曲线。

### `hint_logs`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| meeting_id | 课堂 |
| dedupe_key | 冷却键，唯一索引 |
| hint_type | `low_participation` / `discussion_stall` |
| target_type / target_user_id | 学生级必填 `target_user_id` |
| trigger_reason | 人读原因 |
| evidence | JSON，GCA 数值证据 |
| evidence_ids | JSON，上文 ID 列表 |
| text | 最终文案 |
| model / prompt_version | 生成来源 |
| status | `candidate` / `approved` / `sent` / `ignored` / `failed` |
| created_by | 操作人 |
| sent_at / response | 发送与反馈 |
| created_at | 创建时间 |

### `analysis_runs`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| meeting_id | 课堂 |
| kind | `engagement` / `shadow` / `ab` |
| source / model / version | 数据来源与版本 |
| status | `success` / `insufficient_data` / `single_speaker` / `invalid_input` / `not_found` / `internal_error` |
| latency_ms / cost | 观测 |
| result | JSON 结果或摘要 |
| error | 失败原因 |
| created_at | 运行时间 |

## 5. 降级与隐私

- GCA 抛错、超时或返回空：跳过本次评估，记录日志，不影响课堂主链路。
- LLM 不可用：使用固定模板兜底，`model` 记为 `template`；仍写 `HintLog`。
- 课堂非 `running`：不评估、不发送。
- 本期不向 Qwen/Omni 发送音频或视频；提示生成只用转写文本与课堂元数据。
- 日志不写原始音频；密钥只在服务端环境变量中。

## 6. 版本与兼容

- 契约版本 `ENGAGEMENT_PROTOCOL_VERSION = "1.0"`。
- v1 内只允许新增可选字段；重命名指标、改状态语义、改时间基准都要升主版本。
- `engagement_curves` 与 `analysis_runs` 都要存版本，便于回溯。

## 7. 验收口径

本期可自动化验证的部分：

- 同一 `dedupe_key` 在冷却期内只产出一条候选、只发送一次。
- 教师不在在线名单中，也不会收到学生级提示。
- 映射不到在线成员时退回已知发言人，不误判从未发言者。
- 任一维度 `unavailable` 时，其余维度结果照常返回，整体不报 500。
- 每次发送都能在 `hint_logs` 中查到证据 ID。

准确率、覆盖率、学习效果需要真实课堂数据标定，本期不作结论；
数据量、缺失率与成本报告随 P4 数据底座一起补。

## 8. 不在本轮范围

- `windows.py` 自定义指标汇总扩展。
- Hint 自动发送、A/B 分组、模型影子对比。
- 多 worker 下的共享冷却与在线名单。
