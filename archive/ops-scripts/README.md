# 手动执行的运维/维护脚本

本目录收三类**手动运行**的脚本，都不被应用导入、也不被任何测试引用。
（实测：57 个根级 `.py` 中用 AST 求 `server.py` 的导入传递闭包，得到 15 个运行期
模块，本目录一个都不在其中。）

```
ops-scripts/
├── _prod_guard.py          # 共享的生产目标防护（见下）
├── codemods/               # 一次性批量改写脚本
├── db-maintenance/         # 数据库检查与维护
├── diagnostics/            # 外部服务与数据诊断
└── install_voiceprint.py   # 声纹依赖安装（一次性）
```

---

## ⚠️ 先读这一段：这些脚本会连到**生产库**

本仓库工作区的 `.env` 指向**生产阿里云 RDS**。这些脚本绕开应用直连数据库，
不经 ORM 的校验、也没有事务保护。在工作区敲一句 `python init_db.py`
就会对生产库执行 `CREATE TABLE` / `CREATE INDEX`。

这不是假想的风险，同类路径已有实证：`import database` **这一个动作本身**就会在
模块导入期执行 `database.py:243` 的 `_ensure_transcripts_columns()`，必要时对
`DATABASE_URL` 指向的库执行 `ALTER TABLE`。

### `_prod_guard.py`：「非阻塞警示」

归档时的约定是给 `check_*.py` / `init_db.py` 加非阻塞警示。
实现见 `_prod_guard.py`，行为是：

| 目标 | 行为 |
|---|---|
| 本机回环 / sqlite 文件 | **只打印警示，照常继续**——对本地开发零摩擦 |
| 远程（如 `*.rds.aliyuncs.com`） | **要求显式确认**，否则以退出码 2 终止 |

确认方式：命令行加 `--yes`，或设环境变量 `OPS_SCRIPT_CONFIRM=1`。

> **这是对原约定的一处强化，记录在此以免误以为是原约定的全部**：原约定说的是
> 「非阻塞警示」。纯粹打印的警示在这里几乎无用——脚本打印完下一行就开始执行
> DDL，操作者看到时事情已经发生。因此**仅对远程目标**加了一道确认，
> 本地目标仍是非阻塞的。

**一处必须守住的细节**：`DATABASE_URL` 形如
`mssql+pymssql://user:password@host:port/db`，**整串里含明文口令**。
`_prod_guard` 打印前一律脱敏（`user:***@host`）。这与另一处已暴露的问题同源——
那次是「响应里夹带 `.env` 凭据」，这里是「日志里夹带」。

已实测：远程+无确认 → 退出码 2 且输出不含口令原文；远程+确认 → 继续；
`127.0.0.1` 与 `sqlite://` → 直接继续。

---

## `db-maintenance/`

### 原本是干什么的

| 脚本 | 作用 | 写操作 | 防护 |
|---|---|---|---|
| `init_db.py` | 建表 DDL（11 条 `CREATE TABLE` / `CREATE INDEX`） | **是** | ✅ |
| `fix_db_final.py` | `ALTER TABLE ... MODIFY COLUMN` 放宽列宽度 | **是** | ✅ |
| `check_all_tables.py` | 列表清单 + `transcripts` / `emotion_logs` 列结构 | 否 | ✅ |
| `check_users.py` | 读 `users` 表 | 否 | ✅ |
| `check_users_quick.py` | 读 `users` 表（精简版） | 否 | ✅ |
| `check_db_structure.py` | 读 **`storage/classroom.db`（本地 sqlite）** | 否 | 不需要 |

### 为什么在这里

一次性建库/修库工具。库结构既已由生产库承载，这些脚本不该再被随手运行。

### 已知的引用关系与注意事项

- **`fix_db_final.py` 本来就是坏的**：它用的是 MySQL 语法
  （`ALTER TABLE ... MODIFY COLUMN`），而实际数据库是 **SQL Server**（`pymssql`）。
  也就是说这条语句在归档**之前**就会报错。归档不修复它——修复会改变原文，
  而它作为「曾按 MySQL 写、后迁到 SQL Server」的证据，原样才有意义。
- `check_db_structure.py` 读的是 `storage/classroom.db`，**该文件在本仓库中不存在**
  （`storage/` 被 gitignore）。它必然打印 `[ERROR]`。
- 所有脚本都会在 `_prod_guard` 导入时把**仓库根挂上 `sys.path`**，因此从
  仓库根直接 `python archive/ops-scripts/db-maintenance/init_db.py` 仍可运行
  （否则连 `import config` 都会失败）。

---

## `diagnostics/`

| 脚本 | 作用 | 防护 |
|---|---|---|
| `check_video_logs.py` | 经 ORM 读 `emotion_logs` 中的 `video_url`，并检查本地文件是否存在 | ✅ |
| `debug_emotion_data.py` | 读 **`storage/classroom.db`（本地 sqlite）** 的 `emotion_logs` | 不需要 |
| `detect_oss_region.py` | 逐个试 OSS endpoint，探测 Bucket 在哪个区域 | 不需要 |
| `diagnose_agora.py` | Agora 网关连通性诊断 | 不需要 |

**注意事项**：`detect_oss_region.py` 会**真实外连**多个阿里云 OSS endpoint，
`diagnose_agora.py` 会连 Agora 网关。二者都读取 `.env` 中的真实密钥。
源码含大量 `[EMOJI]` 占位（注释污染），逐行读会难以理解——
`detect_oss_region.py` 的 `ENDPOINTS` 列表是少数不受影响的部分。

---

## `codemods/`

| 脚本 | 作用 |
|---|---|
| `modify_backend.py` | 按模式批量改写 `server.py` |
| `update_backend.py` | 同上，另一套规则 |
| `update_frontend.py` | 批量改写前端 |
| `remove_all_emojis.py` | 清理 `[EMOJI]` 占位（污染清理工具） |
| `temp_fix.py` | **0 字节空文件** |

### 为什么在这里

**这些脚本会原地改写 `server.py` 等源文件**——它们正是那批
注释污染的**来源**。保留它们有明确价值：它们是「这些文件为什么变成这样」的
唯一证据。**不要运行它们。**

`temp_fix.py` 是 0 字节文件。保留原样（不删除文件）；它证明了曾经有过一个
「临时修复」，但内容已丢失。

---

## `install_voiceprint.py`

声纹功能的依赖安装脚本。原本只在打印里提到 `voiceprint_api.py`（该文件本身是
坏的——在 FastAPI 项目里 `from flask import app`，且未定义 `ROOT_DIR`；
已随 `speech-stages/modules/` 归档）。

---

## 查阅指引

- 想知道**数据源锚点**为何重要 → `app/core/paths.py` 的模块文档，以及
  `tests_safe/test_paths_anchor.py`
- 想知道生产库上有哪些表/列**不在 ORM 里** → `DATABASE_AUDIT_REPORT.md`
  （已归档到 `../dev-docs/`）
