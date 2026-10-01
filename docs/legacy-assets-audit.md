# 遗留资产审计：测试与运维脚本

> **审计时点**：2026-10-01 · **阶段**：阶段 1（测试体系）
> **方法**：逐个文件通读源码定性；所有结论均给出文件与行号。
> **本审计未运行任何遗留测试或脚本**——理由见 §1.1。

本文件回答设计文档 §7.2 的第一个必做动作：「抢救已有测试」。
结论是：**只有一小部分值得抢救，且抢救方式不是"让它们跑起来"**。

---

## 1. 先说三个决定全局的事实

### 1.1 仅仅"收集" `tests/` 就会尝试对生产库执行 DDL

传导链（逐跳可验证）：

```
tests/test_api_endpoints.py:2   from server import app
  → server.py:43                from database import ...
    → database.py:19            engine = create_engine(SQLALCHEMY_DATABASE_URL)
    → database.py:246           _ensure_transcripts_columns()   ← 模块级，导入即执行
```

实测（不连库，仅读配置）：未隔离时 `config.settings.db.url` 解析为

```
mssql+pymssql://<生产库用户>:***@<生产 RDS 主机名>:3433/cscl_db
```

`_ensure_transcripts_columns()` 会对 `transcripts` 执行 inspect，缺列时发
`ALTER TABLE transcripts ADD ...`（异常被吞掉，见设计文档 §3.11）。

**因此 `pytest.ini` 的 `testpaths = tests_safe` 不是风格偏好，是安全闸门。**
本审计全程未运行 `tests/` 下任何文件，也未用 `--collect-only` 绕过它。

### 1.2 端点契约是 Form，不是 JSON

`/api/ai-tutor`（`server.py:3798`）、`/api/suggest-topic`（`:4335`）、
`/api/quiz-error-analysis`（`:5738`）、`/api/generate-report`（`:2367`）等
均声明 `param: str = Form(...)`。

遗留用例里清一色 `client.post(..., json={...})` —— **在到达 handler 之前就被
FastAPI 以 422 拒绝**，既不会调 LLM，也不会碰数据库。

**这既是好消息也是坏消息**：好消息是这些用例当前并未造成生产副作用；坏消息是
它们的"能跑"是假象——一旦有人把 payload 改成 `data=`，约 12 条会立刻真实调用
DeepSeek 生产 API。

### 1.3 大量 mock 目标根本不存在

`llm_service.py` 中**没有**以下定义（已逐个 grep 确认为 0 处）：

`_chat_once`、`_fallback_chat`、`_chat_with_fallback`、`_chat_json_with_fallback`

`llm` 也没有 `model` 属性（`llm_service.py:188/351/1004` 的 `model="deepseek-chat"`
是 API 调用的关键字参数，不是实例属性）。因此 `patch.object(llm, "_chat_once")`
之类会直接抛 `AttributeError`，用例 error。

另外 `_clean_json()` 解析失败时**返回 `None`，不是空 dict**（`llm_service.py:84-108`，
末行 `return None`）。多条断言 `isinstance(result, dict)` 的用例**与实际契约相反**。

---

## 2. `tests/` 逐文件审计

| 文件 | pytest 用例数 | 弱断言 | 真实外部调用 | 真实读写生产库 | 可移植性 |
|---|---:|---:|---:|---:|---|
| `load_test.py` | **0**（脚本） | — | 3（压测场景） | 2 | 难 |
| `regression_test.py` | **0**（脚本，12 个 `_test_*` 方法） | **7** | 0 | **1** | 难 |
| `test_api_endpoints.py` | 3 | 0（断言过强、与契约冲突） | 0 | 0 | **易** |
| `test_llm_adapter.py` | 25 | **12** | 0 | 0 | 中 |
| `test_llm_core.py` | 3 | 1 | 0 | 0 | 中 |
| `test_llm_endpoints.py` | 28 | **10** | 0 | 0 | 中→难 |
| **合计** | **59** | **30** | 0 | **1** | — |

### 2.1 唯一的真实生产库触点

`regression_test.py` 的 `_test_transcript_operations` 打 `GET /api/transcripts/1`，
该路由真实存在且带 `Depends(get_db)`（`server.py:2251-2252`）——**这一条会实连
阿里云 RDS 读数据**。其余 `get_db` 端点都被 422 挡在门外。

### 2.2 两根"永远绿"的假保险

- `regression_test.py`：12 条里 7 条把 404 / 401 / **异常**判为通过。
  最极端的是 `_test_emotion_analysis`——连抛异常都 `add_pass`，
  而它测的 `/api/analyze-emotion` **根本不存在**。即使端点被删除，它也永远显示绿色。
- `test_llm_endpoints.py`：10 条宽集合断言，如
  `assert status in [400, 422, 200]`，几乎不可能失败。

### 2.3 逐文件定性

**`load_test.py`** —— 性能压测 harness，非断言测试。无 `test_` 前缀函数，
pytest 收集为 0。打 `http://127.0.0.1:8000`（需先起服务），20 个并发请求，
结果靠 print 与导出 JSON。发的是 JSON payload 而端点是 Form，**注定全部 422 判失败**。
→ 不移植为断言测试；其"压测"用途归入阶段 5 的部署形态验证。

**`regression_test.py`** —— 同上为脚本，4 个自定义类、12 个 `_test_*` 方法。
→ 不移植。其"通过"逻辑本身有缺陷，保留只会制造虚假信心。

**`test_api_endpoints.py`** —— 3 条，断言直白（`== 200`），只是 payload 用错。
→ **可移植**：改成 Form + mock 掉 LLM 即可。

**`test_llm_adapter.py`** —— 25 条。纯逻辑部分（JSON 清洗、LRU 缓存、线程安全）
质量很好、无需外部依赖；但 8 条针对不存在的 API，3 条空断言（`assert True`）。
→ **部分移植**：移植纯逻辑用例；fallback 类用例须按真实接口重写。

**`test_llm_core.py`** —— 3 条。`test_json_clean` 正确；
`test_json_invalid_fallback` 期望 dict 而实际返回 None（**契约写反了**）；
`test_fallback_trigger` 针对不存在的 API。
→ **部分移植**：移植第 1 条，第 2 条按实际行为重写，第 3 条丢弃。

**`test_llm_endpoints.py`** —— 28 条，与 Form 契约全面不符，mock 目标错误。
→ 暂不移植。价值密度低（28 条里 10 条弱断言），重写成本高于按新体系重写。

---

## 3. 会直连生产库的运维脚本（16 个）

这批脚本**运行即连接 `.env` 指向的数据库**，其中 `init_db.py` 含建表语句。

| 位置 | 文件 |
|---|---|
| 根目录（9） | `init_db.py`、`check_all_tables.py`、`check_users.py`、`check_users_quick.py`、`check_video_logs.py`、`fix_db_final.py`、`test_db.py`、`test_login.py`、`test_reports.py` |
| `test/`（7） | `check_all_tables.py`、`check_users.py`、`check_users_quick.py`、`check_video_logs.py`、`fix_db_final.py`、`test_login.py`、`test_reports.py` |

典型形态（`check_users.py` 全文 23 行）：`import config` 加载 `.env` →
`pymssql.connect(server=os.getenv("DB_HOST"), ...)` → 立即查询。

**处置**（对应待验收事项 A7 第 3 项）：**阶段 3 归档时统一加非阻塞警示**，
现在不动——逐个插入是 16 次机械改动，而阶段 3 本就要把这批文件整体搬入归档区，
届时一处 README + 一次统一处理即可覆盖全部。

---

## 4. 对阶段 1 的结论

1. **"抢救已有测试"的正确形态不是让它们重新跑起来。** 59 条里可用的不足两成，
   且两条最"完整"的文件（`load_test.py`、`regression_test.py`）根本不是测试。
2. **安全闸门必须固化为测试。** `testpaths` 是配置，配置会被误改。已补
   `tests_safe/test_legacy_isolation.py`，用断言钉死"遗留目录不可被收集、
   隔离在 `database` 导入前生效"。
3. **移植策略**：按新体系重写，而非逐条搬运。优先移植纯逻辑用例
   （无需外部依赖、价值密度高），端点类用例以「隔离环境 + mock 外部服务」重写。
