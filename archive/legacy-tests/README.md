# 遗留测试（归档）

本目录收原仓库中**三个位置**的测试/检查脚本，按原位置分三个子目录：

```
legacy-tests/
├── conftest.py     # 闸门：拒绝任何形式的收集，见下
├── root/           # 原先散在仓库根的 test_*.py 与 run_all_tests.py
├── test-dir/       # 原先的 test/ 目录
└── tests-dir/      # 原先的 tests/ 目录
```

---

## ⚠️ 先读这一段：这些文件**不能跑**

`tests-dir/test_api_endpoints.py:2` 等文件顶部写着：

```python
from server import app
```

而 `server.py` → `database.py` 的**模块导入期**会执行
`_ensure_transcripts_columns()`（`database.py:243`），必要时对 `DATABASE_URL`
指向的库发出：

```sql
ALTER TABLE transcripts ADD ...   -- 对本仓库工作区而言 = 生产阿里云 RDS
```

**所以「收集」这些文件不是无害的读操作，而是对生产库的 DDL 尝试。**

这不是理论推演——**已经真实发生过一次**，见本文末「事故记录」。

### 哪些文件踩在这条路径上（已逐个核过 `import`）

判据有两条，**任意一条成立即触发**：`import server`（server 会 import database），
或直接 `import database`（`_ensure_transcripts_columns()` 在 database 的模块级运行）。

| 目录 | 在 DDL 路径上的文件 | 依据 |
|---|---|---|
| `root/` | `test_db.py`、`test_imports.py`、`test_login.py`、`test_reports.py`、`test_server_imports.py` | `from database import ...` |
| `test-dir/` | `check_video_logs.py`、`test_imports.py`、`test_login.py`、`test_reports.py`、`test_server_imports.py` | `from database import ...` |
| `tests-dir/` | `regression_test.py`、`test_api_endpoints.py`、`test_llm_endpoints.py` | `from server import app` / `from database import ...` |

**共 13 个**。其余 26 个文件不 import `server`/`database`，不会触发模块级 DDL——
但它们仍会外连（OSS、Agora、HTTP 接口），同样不建议运行。

### 三道闸门

| # | 位置 | 作用范围 | 说明 |
|---|---|---|---|
| 1 | 仓库根 `conftest.py` | **所有** pytest 调用 | 把 `DATABASE_URL` 换成临时 sqlite、`DB_*` 换成不可达值。安全网 |
| 2 | 本目录 `conftest.py` 的 `pytest_configure` | 参数指向本目录时 | 直接检查命令行参数，命中即 `UsageError` **中止会话**（退出码 4） |
| 3 | 本目录 `conftest.py` 的 `collect_ignore` | 按目录收集时 | 兜底，边界最窄 |

**为什么"显式点名"需要单独一道闸门**：原先只靠 `pytest.ini` 的
`testpaths = tests_safe`。但 `testpaths` 只管**默认收集范围**，显式路径参数会
完全覆盖它——`pytest archive/legacy-tests/xxx.py` 这种写法下，所有基于收集钩子的
机制（`collect_ignore`、`pytest_ignore_collect`）**全部失效**：pytest 把显式参数
登记为 *init path*，有意豁免它们的 ignore 检查。

这两种做法都是**实测否定**的，过程记在 `conftest.py` 的文件头里——那里同时写了
`pytest_ignore_collect` 为何反直觉地无效，以免后来者重试。

---

## 清单

### `root/` —— 原先散在仓库根的脚本（11 个）

| 文件 | 行数 | 在 DDL 路径 | 内容 |
|---|---|---|---|
| `test_concurrent_users.py` | 478 | | 并发用户压测 |
| `run_all_tests.py` | 228 | | 串行跑本目录这批脚本并汇总 |
| `test_login.py` | 96 | ✅ | 经 `requests` 打 HTTP 登录接口，再用 `database` 的 `SessionLocal` 核对落库 |
| `test_aliyun_expression.py` | 72 | | 阿里云表情识别 |
| `test_db.py` | 70 | ✅ | 数据库连通性（`SessionLocal` + `User`） |
| `test_oss.py` | 59 | | 阿里云 OSS |
| `test_imports.py` | 51 | ✅ | 第三方依赖与内部模块的导入自检 |
| `test_asr.py` | 44 | | 语音识别 |
| `test_server_imports.py` | 33 | ✅ | 用 `get_db`/`User`/`Meeting` 拼最小 FastAPI 应用 |
| `test_reports.py` | 32 | ✅ | 报表接口（`LearningReport`/`Exercise`） |
| `test_minimal_server.py` | 14 | | 最小可启动服务 |

### `test-dir/` —— 原先的 `test/`（21 个）

其中 **13 个是 `root/` 同名文件的逐字节副本**（已用 git 逐一比对），
**4 个与 `root/` 同名文件差 2 行**，**4 个只在 `test/` 中存在**。

那 2 行的差异是一条路径自举：

```python
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

因为 `test/` 比仓库根**深一层**，得先把仓库根挂上 `sys.path` 才能 `import config`。
差这 2 行的是 `check_all_tables.py`、`check_users.py`、`check_users_quick.py`、
`fix_db_final.py`（`check_video_logs.py` 当时尚未分化，逐字节相同）。

> 结论：**`test/` 是 `root/` 的一份快照副本**，其差异只来自「住在更深一层」，
> 不是业务逻辑的演进。

只在 `test/` 中存在的 4 个：

| 文件 | 行数 | 在 DDL 路径 | 内容 |
|---|---|---|---|
| `test_voiceprint.py` | 261 | | 声纹链路（对应 `../speech-stages/` 那批模块） |
| `test_gemma_emotion.py` | 127 | | Gemma 情绪模型 |
| `test_gemma_simple.py` | 66 | | Gemma 简化验证 |
| `check_enhanced_runtime.ps1` | 36 | | PowerShell：用 `importlib.util.find_spec` 探依赖是否装齐 |

> ⚠️ 上表最后一行的情况**已经变了**：该脚本已另补一份**在仓库根**（本文档只记归档物，
> 不描述那一份）。起因是 `/api/research-runtime` 的 `setup_scripts.check_runtime`
> 一直承诺着「仓库根/check_enhanced_runtime.ps1」这个路径，而 `setup_enhanced_runtime.ps1`
> 末尾也叫用户去跑它——两边都指着一个不存在的文件。
> **本目录这一份是原样留档的旧物，不要拿去用**：它末尾还是过期的
> `from research_runtime import ...`（模块早已搬进 `app/services/`）。
>
> 另需注意：`test-dir/` 里的 `check_*.py` / `fix_db_final.py` / `debug_emotion_data.py`
> / `detect_oss_region.py` 与 `../ops-scripts/` 中的同名脚本是**两份不同的东西**。
> `ops-scripts/` 收的是 `root/` 那一支（较新，且已加生产目标防护）；
> `test-dir/` 这里是 `test/` 那一支的快照。两者关系已用 git 核对：
> 4 个差上述那 2 行，其余逐字节相同。

### `tests-dir/` —— 原先的 `tests/`（7 个）

| 文件 | 行数 | 在 DDL 路径 | 内容 |
|---|---|---|---|
| `regression_test.py` | 459 | ✅ | 回归测试 |
| `test_llm_endpoints.py` | 352 | ✅ | LLM 接口 |
| `load_test.py` | 331 | | 负载测试 |
| `test_llm_adapter.py` | 269 | | LLM 适配层 |
| `test_llm_core.py` | 27 | | LLM 核心 |
| `test_api_endpoints.py` | 18 | ✅ | 三个接口的冒烟 |

**这一批是唯一被 pytest 按默认命名规则识别的**（`test_*.py`），
也因此唯一有"被自动收集"的风险——事故就出在这里。

---

## 事故记录（2026-10-01）

归档完成后验证闸门时，执行了：

```bash
pytest archive/legacy-tests/tests-dir/test_api_endpoints.py --collect-only
```

结果：`3 tests collected in 3.59s`——**收集过程真实 `import server` → `import database`**，
即一次对生产库的 DDL 尝试。当时 `collect_ignore` 已就位，但**对显式文件路径无效**。

留下的物证：`tests-dir/__pycache__/test_api_endpoints.cpython-312-pytest-9.1.1.pyc`
（已删除）。

**未能确认的一点，如实记录**：那条命令的输出当时被 `tail -4` 截断，
因此**无法确认 `ALTER TABLE` 是否真的执行过**。
判断「很可能没有执行」的理由是：`_ensure_transcripts_columns()` 只在列缺失时才发 DDL，
而生产应用已长期运行、该功能早已上线，那五列（`binding_source`、`binding_confidence`、
`identity_review_status`、`identity_review_note`、`cross_modal_consistency`）
极可能早已存在，`ddl_list` 因而为空。
但这是推断，不是证据。

---

## 查阅指引

- 闸门为什么这么写、哪些做法被实测否定 → 本目录 `conftest.py`
- 同一批脚本的较新一支 → `../ops-scripts/README.md`
- 声纹相关的模块与验证 → `../speech-stages/`
