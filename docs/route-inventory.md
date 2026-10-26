# 路由清单与基线覆盖

> 生成方式：从运行中的 FastAPI app 枚举 `app.routes`（**不是**阅读源码手抄），
> 再按处理器源码的外部依赖标记 + socket 层实测结果分类。
> 复现命令见文末。

## 一、分类口径

| 分类 | 含义 | 是否可纳入基线 |
|---|---|---|
| `只读本地` | 只读本库、不出网、不改状态 | **候选** |
| `写操作` | 改变库或文件状态 | 否——顺序耦合会让基线不稳 |
| `写操作（有副作用）` | GET 但会落盘 | 视情况，见下文 |
| `外部服务` | 依赖 LLM / OSS / Agora / pymssql 直连 | 否——不可复现、且可能夹带凭据 |
| `本地模型推理` | 本地跑声纹/ASR 模型 | 否——耗时长，输出依赖模型权重与环境 |
| `WebSocket` | 长连接 | 否——TestClient 基线不覆盖 |

**关键**：分类只作提示。是否纳入基线，最终由**实测**决定——把候选路由在
socket 兜底开启的情况下真跑一遍，看它是否尝试外连（见文末复现命令）。
纯静态扫描会漏判（例：`/summary` 处理器里写的是 `llm.analyze_...`，不是
`llm_service.`，正则匹配不到）。

## 二、全部路由

| 方法 | 路径 | 分类 | 入基线 |
|---|---|---|---|
| WS | `/ws-asr/{username}/{meeting_id}` | WebSocket |  |
| WS | `/ws-signal/{username}/{meeting_id}` | WebSocket |  |
| WS | `/ws/{username}/{meeting_id}` | WebSocket |  |
| POST | `/api/browser-asr-final` | 写操作 |  |
| POST | `/api/cast-vote` | 写操作 |  |
| DELETE | `/api/delete-template/{template_id}` | 写操作 |  |
| POST | `/api/end-class` | 写操作 |  |
| POST | `/api/generate-pdf-report` | 写操作 |  |
| POST | `/api/research-runtime/config` | 写操作 |  |
| POST | `/api/research-runtime/prepare-layout` | 写操作 |  |
| POST | `/api/start-class` | 写操作 |  |
| POST | `/api/submit-answer` | 写操作 |  |
| GET | `/api/download-exercises/{report_id}` | 写操作（有副作用） | ✅ |
| GET | `/` | 只读本地 | ✅ |
| GET | `/api/active-groups/{teacher_id}` | 只读本地 | ✅ |
| GET | `/api/all-student-reports/{teacher_id}` | 只读本地 | ✅ |
| GET | `/api/class-groups/{meeting_id}` | 只读本地 | ✅ |
| GET | `/api/class-history/{user_id}` | 只读本地 | ✅ |
| GET | `/api/emotion-details/{meeting_id}` | 只读本地 | ✅ |
| GET | `/api/exercises/{report_id}` | 只读本地 | ✅ |
| GET | `/api/get-video-context` | 只读本地 | ✅ |
| GET | `/api/knowledge-graph/{meeting_id}` | 只读本地 | ✅ |
| GET | `/api/meeting-reports/{meeting_id}` | 只读本地 | ✅ |
| GET | `/api/meeting/{meeting_id}` | 只读本地 | ✅ |
| GET | `/api/realtime-stats/{meeting_id}` | 只读本地 | ✅ |
| GET | `/api/reports/{user_id}` | 只读本地 | ✅ |
| GET | `/api/research-runtime` | 只读本地 | ✅ |
| GET | `/api/snapshot/{meeting_id}` | 只读本地 | ✅ |
| GET | `/api/student-home-stats/{user_id}` | 只读本地 | ✅ |
| GET | `/api/student-quiz-history/{user_id}` | 只读本地 | ✅ |
| GET | `/api/teacher-classes/{teacher_id}` | 只读本地 | ✅ |
| GET | `/api/teacher-stats/{teacher_id}` | 只读本地 | ✅ |
| GET | `/api/teacher-templates/{teacher_id}` | 只读本地 | ✅ |
| GET | `/api/transcripts/{meeting_id}` | 只读本地 | ✅ |
| GET | `/pcm-processor.js` | 只读本地 | ✅ |
| GET | `/voiceprint_register` | 只读本地 |  |
| GET | `/api/agora-token` | 外部服务：Agora |  |
| POST | `/api/ai-tutor` | 外部服务：LLM |  |
| POST | `/api/ai-tutor-stream` | 外部服务：LLM |  |
| POST | `/api/check-quiet-members` | 外部服务：LLM |  |
| POST | `/api/check-silence` | 外部服务：LLM |  |
| POST | `/api/close-vote` | 外部服务：LLM |  |
| POST | `/api/cluster-viewpoints` | 外部服务：LLM |  |
| POST | `/api/confirm-vote` | 外部服务：LLM |  |
| POST | `/api/generate-report` | 外部服务：LLM |  |
| POST | `/api/generate-report-stream` | 外部服务：LLM |  |
| POST | `/api/grade-short-answer` | 外部服务：LLM |  |
| POST | `/api/quick-decompose` | 外部服务：LLM |  |
| POST | `/api/quiz-error-analysis` | 外部服务：LLM |  |
| POST | `/api/suggest-topic` | 外部服务：LLM |  |
| POST | `/login` | 外部服务：LLM |  |
| GET | `/summary` | 外部服务：LLM、实测外连 |  |
| POST | `/api/login` | 外部服务：pymssql直连 |  |
| POST | `/api/register` | 外部服务：pymssql直连 |  |
| POST | `/api/voiceprint/identify` | 本地模型推理 |  |
| POST | `/api/voiceprint/register` | 本地模型推理 |  |
| GET | `/api/voiceprint/status/{username}` | 本地模型推理 | ✅ |
| DELETE | `/api/voiceprint/unregister/{username}` | 本地模型推理 |  |
| GET | `/api/voiceprint/users` | 本地模型推理 | ✅ |
| POST | `/api/voiceprint/verify` | 本地模型推理 |  |

总计 60 条：{'WebSocket': 3, '写操作': 9, '写操作（有副作用）': 1, '只读本地': 23, '外部服务': 18, '本地模型推理': 6}
入基线 25 条

## 三、基线实际覆盖

基线 = `tests_safe/baselines/routes.json`，由 `tests_safe/test_route_baseline.py` 录制与比对。

**纳入 25 条**（上表 ✅）。其中两条的分类是「提示与实际不符」，均已实测确认可纳入：

- `/api/download-exercises/{report_id}`——分类为「写操作（有副作用）」，因为它会把
  练习题写成一个临时 txt 再回传。该文件落在测试临时目录，**不累积状态**，响应内容
  完全由库中数据决定，因此可纳入。
- `/api/voiceprint/status/{username}`、`/api/voiceprint/users`——分类为「本地模型推理」，
  但它们只读进程内的注册表，**不加载模型也不出网**（实测无外连），故可纳入。

## 四、已知盲区（不纳入，且短期内无法纳入）

| 路由 | 原因 |
|---|---|
| `/api/register`、`/api/login` | **绕过 ORM 直连 MSSQL**（`server.py:1935`/`:1985`）。本地 sqlite 无法承接，pymssql 只讲 MSSQL。 |
| `/api/agora-token` | 响应取自 `.env` 的 `AGORA_*`。凭据配齐的机器上会返回**带时效的真实 Token**——既不可复现，也会把凭据写进随仓库提交的基线文件。本机只是恰好缺 `AGORA_APP_CERTIFICATE` 才显得"确定"，不能依赖。`test_responses_do_not_leak_env_secrets` 即为防止同类路由被误加 |
| `/summary` | 处理器内调用 LLM，实测外连 `116.196.150.245:443`（被 socket 兜底拦下 8 次） |
| `POST /login` | 调用 `llm.init_meeting_goals()`，且为写操作 |
| 全部 `POST`/`DELETE`（26 条） | 改变状态；两次运行结果不可比 |
| 3 条 WebSocket | 长连接，非请求-响应语义 |
| `/voiceprint_register` | **死路由**：`FileResponse` 指向的 `voiceprint_register.html` 全仓不存在，任何调用抛 `RuntimeError` |

**覆盖率：25 / 60 ≈ 42%**。

但这个分母没有意义——60 条里有 27 条 `POST`/`DELETE` 写操作、3 条 WebSocket、
20 条外部服务依赖，它们本来就不可纳入。按"可纳入"的口径算：

- `只读本地` 共 **23** 条，已纳入 **22** 条，唯一未纳入的是 `/voiceprint_register`
  （死路由，必然抛错，纳入也锁不住任何东西）
- 另纳入 3 条分类提示与实际不符、但实测确认合格的路由
  （`/api/download-exercises`、`/api/voiceprint/status`、`/api/voiceprint/users`）
- 合计 25 条

即：**所有能本地只读跑通的路由都已覆盖**，未覆盖的全部有明确且已记录的原因。

## 五、复现命令

```bash
# 枚举全部路由
./venv/Scripts/python.exe -c "import os; os.environ['DATABASE_URL']='sqlite://';   import server; print([r.path for r in server.app.routes])"

# 录制 / 比对基线
./venv/Scripts/python.exe -m pytest tests_safe/test_route_baseline.py --record-baseline
./venv/Scripts/python.exe -m pytest tests_safe/test_route_baseline.py
```

分类脚本与实测探针是一次性工具，未纳入交付物；如需重跑，按上文口径重建即可。
