# tests_safe —— 活跃测试套件

## 一条命令

```bash
./venv/Scripts/python.exe -m pytest
```

在仓库根目录执行。`pytest.ini` 里 `testpaths = tests_safe`，因此这一条就是全部。

> **不要用裸 `pytest`。** 本机默认 `python` 是 3.14 且缺依赖；`venv/Scripts/python.exe`
> 才是已验证可用的 3.12.10。用错解释器会报导入错误，而不是报版本错误，容易误判方向。
>
> **不要加 `tests/` 参数。** 那个目录是遗留套件，见下方「为什么叫 safe」。

重录基线（仅在**确认**路由行为应当变化时）：

```bash
./venv/Scripts/python.exe -m pytest --record-baseline
```

## 为什么叫 safe

`tests/` 下的 6 个遗留文件都写着 `from server import app`。这条导入链是：

```
tests/test_api_endpoints.py:2   from server import app
  → server.py:43                from database import ...
    → database.py:19            engine = create_engine(SQLALCHEMY_DATABASE_URL)
    → database.py:246           _ensure_transcripts_columns()   ← 模块级，导入即执行
```

最后一步会对 `DATABASE_URL` 指向的库执行 inspect，缺列时发
`ALTER TABLE transcripts ADD ...`。而工作区的 `.env` 指向**生产 RDS**。
也就是说：**仅仅"收集" `tests/`，就可能对生产库尝试 DDL。**

所以 `testpaths = tests_safe` 不是风格偏好，是安全闸门。它由
`test_legacy_isolation.py` 用断言钉死——配置会被误改，断言不会。

完整审计见 `docs/legacy-assets-audit.md`。

## 四层隔离

`conftest.py` 在**测试模块导入之前**生效（pytest 最先加载它，这是唯一可靠的插入点）：

| # | 挡的是什么 | 做法 |
|---|---|---|
| 1 | ORM 路径 | `DATABASE_URL` 在导入前改写为会话级临时 sqlite |
| 2 | 绕过 ORM 的 pymssql 直连（`/api/register`、`/api/login`） | `DB_*` **显式赋成无害值** |
| 3 | 尚未发现的路径 | 会话期间阻断一切非回环 `socket.connect` |
| 4 | 凭据被写进基线文件 | 断言 `.env` 中的凭据不出现在任何基线响应里 |

第 2 层为什么是"显式赋值"而不是 `del os.environ[...]`：`config._load_dotenv()` 用
`os.environ.setdefault`，键一旦不存在就会被 `.env` 的生产值重新填回来。

## 文件分布

| 文件 | 覆盖 |
|---|---|
| `test_route_baseline.py` | 25 条只读路由的冒烟基线（含 Form 契约、凭据扫描） |
| `test_endpoints_mocked.py` | 3 个 LLM 端点的 Form 契约 + 打桩 |
| `test_llm_pure_logic.py` | JSON 清洗、LRU 缓存等纯逻辑 |
| `test_websocket_and_manager.py` | WS 握手、房间隔离、`ConnectionManager` 判定分支 |
| `test_fixture_determinism.py` | 合成数据的结构性守卫 |
| `test_legacy_isolation.py` | 安全闸门本身 |
| `test_local_db.py` / `test_server_import.py` | 本地库与导入期探针 |
| `fixtures.py` | 零 PII 的合成数据，时间基准 `BASE_TIME = 2026-01-01 09:00` |

## 基线怎么比

`baselines/routes.json` 记录每条路由的 `status` / `content_type` / `length` /
结构形状 / 摘要，**不逐字节比对**——原始响应里含 HTML 大页面与时间戳，逐字节
比对既脆弱又不可读。形状用于保证字段集合没变，摘要用于保证取值没变。

**基线是在本地 ORM 库上录的，不是在生产的库上**。本库与生产库结构本就不
一致（18 表 vs 15 表，`transcripts` 另多 6 列，见 `docs/production-schema-drift.md`），
因此**结构层面的结论不能外推到生产**。

## 已知盲区

- `/api/register`、`/api/login` 绕过 ORM 直连 pymssql，**无法在本地库上测试**，
  永久排除在自动化之外
- `/voiceprint_register` 是死路由，指向的文件全仓不存在
- 外部服务（阿里云 NLS / DeepSeek / Agora）只能 mock，mock 的契约未必等于现实
- 测试直连 ASGI，**不经过 nginx**，因此反代层问题（如 `/ws/` 前缀不匹配）
  测试永远发现不了，需另加部署形态验证

## 命名陷阱（写新测试时最容易踩的两个）

1. **`client` 只建表，不播种。** 需要数据请显式依赖 `seeded_ids`（见
   `test_endpoints_mocked.py::seeded_client`）。漏掉会以"业务错误"的形式失败，
   看起来像路由行为不对，实为数据缺失。
2. **`_reimport_database` 一类操作会摘换 `sys.modules`。** 摘掉不还原会污染后续
   每一个测试，且**不报错，只静默比对错东西**。这类测试必须请求 `module_surgery`
   夹具，它会在退出时自动复原。
