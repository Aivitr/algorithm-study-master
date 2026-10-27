# 课堂分析 Agent

课堂分析 Agent 基于 OpenAI Agents SDK 和现有 DeepSeek 模型，为教师提供课堂发言、互动统计与知识点覆盖分析。Agent 通过受状态门禁保护的工具读取课堂数据，并输出结构化分析结果。

## 主要能力

- 读取课堂学生发言，并返回 `T#` 证据编号。
- 统计发言量、参与者、互动关系、发言质量与情绪分布。
- 读取知识图谱，分析学习目标覆盖情况。
- 使用 `Runner.run` 完成模型决策、工具调用和结果回灌循环。
- 将模型调用、工具调用及耗时记录到本地 JSON trace。
- 关闭云端 tracing，不向外部上传 Agent trace。

## 代码结构

| 文件 | 作用 |
|---|---|
| `app/agents/model.py` | 创建与现有 LLM 配置同源的 DeepSeek 模型 |
| `app/agents/state.py` | 课堂三态推导、工具状态门禁和原子 CAS |
| `app/agents/tools.py` | 发言、统计、知识点三个课堂级工具 |
| `app/agents/group_analysis_agent.py` | Agent 指令、结构化输出和工具装配 |
| `app/agents/service.py` | `Runner.run` 执行入口与 trace 生命周期 |
| `app/agents/trace.py` | 本地模型及工具调用 trace |
| `app/services/classroom_agent_service.py` | 工具使用的只读课堂数据 Service |
| `app/routers/agents.py` | Agent HTTP 接口 |

## HTTP 接口

### 提交分析问题

```http
POST /api/agents/group-analysis
Content-Type: application/json

{
  "meeting_id": 1,
  "question": "分析本课堂的参与是否均衡",
  "max_turns": 8
}
```

### 查询工具清单

```http
GET /api/agents/group-analysis/tools
```

返回工具名称、说明、参数 Schema 和允许的课堂状态。

## 状态安全

课堂统一推导为 `created`、`running`、`ended` 三种状态。发言、统计和知识点工具仅在 `running` 或 `ended` 状态可用。

所有课堂状态修改均使用原子比较并交换：

```sql
UPDATE meetings
SET status = :new_status
WHERE id = :meeting_id AND status = :old_status
```

代码仅在影响行数为 `1` 时认定状态迁移成功。

## 本地 Trace

每次运行都会在 `storage/agent_traces/<run_id>.json` 中记录：

- 运行编号、课堂编号、问题和总耗时。
- 每次模型调用的模型名和耗时。
- 每次工具调用的名称、参数、耗时和结果状态。
- 最终成功或失败结果。

`storage/` 属于本地运行数据，不应提交到 Git 仓库。运行配置已设置 `tracing_disabled=True` 和 `trace_include_sensitive_data=False`。

## 相关测试

| 文件 | 作用 |
|---|---|
| `tests_safe/test_agent_routes.py` | 验证提问和工具清单接口 |
| `tests_safe/test_agent_trace.py` | 验证本地 trace 的事件与耗时记录 |
| `tests_safe/test_route_contract.py` | 验证包含两条 Agent 接口的路由契约 |

依赖版本与兼容约束见 `requirements.txt` 和 `requirements.lock.txt`。
