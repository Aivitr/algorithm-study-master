# 生产库结构差异存档

**采集日期**：2026-10-01
**目标**：`cscl_db` @ `***REMOVED-HOST***:3433`
**采集方式**：只读 `INFORMATION_SCHEMA.COLUMNS`（列名、类型、长度、可空性），**未读取任何一行数据**
**服务端版本**：Microsoft SQL Server 2019 (RTM-CU32-GDR) 15.0.4455.2

---

## 为什么要有这份文件

生产库的实际结构**与代码中的 ORM 定义不一致**。这意味着：

> **任何以 ORM 为依据重建数据库的操作，都会丢失下述结构与数据。**

`Base.metadata.create_all(engine)` 会产出一个**少 3 张表、少 6 列**的数据库。该操作在本项目中**被禁止**。

这份文件是该事实的唯一书面证据。**在你确认本文件内容仍然有效之前，不要删除它。**

---

## 差异总览

| | 数量 |
|---|---|
| 生产库实际表数 | **18** |
| ORM 定义表数 | **15** |
| 仅存在于生产库的表 | **3** |
| 仅存在于 ORM 的表 | 0 |
| `transcripts` 表生产库多出的列 | **6** |

---

## 一、仅存在于生产库的表

这 3 张表在 ORM 中**没有任何对应定义**，且经检索**被 0 个 `.py` 文件引用**。

| 表名 | 列数 | 代码引用数 |
|---|---|---|
| `collaboration_intervention_logs` | 13 | 0 |
| `evaluation_logs` | 10 | 0 |
| `rag_chunks` | 7 | 0 |

三张表的命名分别指向三个功能方向——**协作干预、评估、RAG 检索**——均未进入主干代码。推测为开发过程中在数据库层动过工、但代码未合并或已被移除。

## 二、`transcripts` 表多出的列

| 列名 | 代码引用数 | 备注 |
|---|---|---|
| `ptt_mode` | 0 | **Push-To-Talk，即 `STAGE5_INTERACTIVE_FALLBACK_PLAN.md` 的核心功能之一** |
| `corrected_by` | 0 | 转录纠正 |
| `correction_time` | 0 | 转录纠正 |
| `evaluation_evidence` | 0 | 评估 |
| `evaluation_version` | 0 | 评估 |
| `quality_dimensions` | 0 | 见下方说明 |

> **关于 `quality_dimensions`**：代码检索会命中 `server.py:1062` 与 `server.py:1778`，但那是 API 响应字典中的一个**同名键**，与数据库列无关。该数据库列本身无代码引用。

---

## 三、`ptt_mode` 说明的意义

`STAGE5_INTERACTIVE_FALLBACK_PLAN.md` 标题为「阶段5 - 交互式兜底 - **完整规划**」，其三个核心功能之首即 **PTT 模式（Push-To-Talk）**。

`transcripts.ptt_mode` 列的存在表明：**Stage 5 曾在数据库层动过工，但代码从未跟上。**

这与 Stage 1（发言席位锁）、Stage 3（音量仲裁）的模式一致——写了模块、写了测试、文档标记完成，但从未接入主服务。区别仅在于，Stage 1/3 的痕迹留在了代码里，Stage 5 的痕迹留在了数据库里。

---

## 四、对重构的约束

| 约束 | 说明 |
|---|---|
| **禁止以 ORM 重建数据库** | 会丢失 3 张表与 6 列 |
| **禁止执行自动迁移** | 任何以 ORM 为准的 drop/create 都会造成结构丢失 |
| **容器化不得初始化数据库** | 阶段 5 的容器**只能连接**既有数据库，不得建库 |
| **本地测试库按 ORM 建立是安全的** | 但必须记录：它与生产库**结构不一致**，因此结构层面的测试结论不能直接外推到生产 |

---

## 五、复核方式

如需重新确认本文件是否仍然有效，执行只读查询：

```sql
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
ORDER BY TABLE_NAME, ORDINAL_POSITION
```

并与 `database.py` 中的 `Base.metadata.tables` 比对。两者表数应分别为 18 与 15。
