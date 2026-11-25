# Hint 与三维投入接口

> 适用于课堂运行中的 Hint 触发、发送记录与课后投入曲线查询。
> 所有接口要求 `Authorization: Bearer <session-token>`；除注明外仅本课堂教师可调用。

## 1. 候选生成

### `POST /api/check-silence`

教师手动触发一次“讨论停滞”评估；**只生成待发送提示，不发送**。

| 参数 | 类型 | 说明 |
|---|---|---|
| `meeting_id` | int | 课堂 ID |

响应：

```json
{"status": "success", "silent": true, "pending": [{"hint_id": 7, "hint_type": "discussion_stall", "text": "……"}]}
```

无候选时返回 `{"status":"success","silent":false,"pending":[]}`。

### `POST /api/check-quiet-members`

教师手动触发一次“低参与”评估；同样只生成候选。

响应：

```json
{"status": "success", "quiet_members": ["李同学"], "pending": [{"hint_id": 8}]}
```

> 服务端每 30 秒自动评估所有进行中的课堂（`app/services/hint_scheduler.py`），
> 调用方不需要再定时轮询这两个接口。

### 共同规则

- 课堂状态必须是 `running`；`created` / `ended` 不评估。
- 只使用学生发言，教师发言由适配层排除。
- 时间零点统一为 `meeting.started_at`（缺失时退回最早发言）。
- 同一 `dedupe_key` 在冷却期内（学生 120 秒 / 小组 300 秒）只生成一次。
- LLM 生成失败或返回空文本时使用固定模板，`HintLog.model` 记为 `template`。

## 2. 教师确认与发送

### `POST /api/hint-logs/{hint_id}/send`

教师确认一条候选并下发。只允许本课堂教师；同一课堂 10 分钟内最多 5 条。

- 小组级：向课堂广播 `topic_suggestion`
- 学生级：只发给目标学生
- 成功后 `hint_logs.status=sent`，记录 `sent_at` 与操作人
- 已处理（`sent` / `ignored`）或非候选 → 409
- 超过频率上限 → 429

### `POST /api/hint-logs/{hint_id}/ignore`

教师忽略一条候选；`hint_logs.status=ignored`。

## 3. 学生回应

### `POST /api/hint-logs/{hint_id}/response`

学生回应已发送的提示。个人提示只有目标学生能回应；小组提示要求是课堂参与者。

```json
{"response": "acknowledged"}
```

允许值：`acknowledged` / `need_help` / `dismissed`。响应写入 `hint_logs.response`；
候选未发送时返回 409。

## 4. 发送记录

### `GET /api/hint-logs/{meeting_id}`

教师查看本课堂的提示记录，按时间倒序。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `limit` | int | 50 | 1–200 |

响应中的 `evidence_id` 为 `H#<id>`，可直接作为 Agent 结论的证据引用。

```json
{
  "status": "success",
  "meeting_id": 12,
  "logs": [
    {
      "id": 7,
      "evidence_id": "H#7",
      "hint_type": "discussion_stall",
      "target_type": "group",
      "target_user_id": null,
      "trigger_reason": "全组已 130 秒没有新发言",
      "evidence": {"silence_seconds": 130},
      "text": "可以围绕……",
      "model": "llm",
      "prompt_version": "topic_suggestion_v1",
      "status": "sent",
      "created_by": 1,
      "sent_at": "2026-11-23T05:00:00"
    }
  ]
}
```

## 3. 三维投入

### `GET /api/engagement/{meeting_id}`

按维度、学生过滤已落库的投入曲线。

| 参数 | 类型 | 说明 |
|---|---|---|
| `dimension` | str | `emotional` / `behavioral` / `cognitive` |
| `user_id` | int | 教师可指定学生；学生只能查自己 |
| `limit` | int | 1–1000，默认 200 |

学生只返回自己的学生行；小组行（`user_id=null`）只对教师返回。

### 写入时机

课堂结束后由 `end-class` 异步重算并覆盖写入，重复结束不会重复触发。
窗口使用固定 5 分钟；没有时间线的维度退化为一个整节课窗口。

## 4. 错误与降级

| 情况 | 表现 |
|---|---|
| 未登录 | 401 |
| 非本课堂教师 / 学生越权 | 403 |
| 课堂不存在 | 404（`hint-logs`、`engagement`） |
| 课堂非 running | `check-*` 返回 error，`hint-logs` 可读 |
| GCA 数据不足 | 无候选；投入维度标记 `insufficient` / `unavailable` |
| LLM 不可用 | 模板兜底，提示仍可发送 |

## 5. 已知边界

- `HintTriggerState` 与在线成员表在进程内，生产为单 worker；重启会丢候选状态，
  冷却由 `hint_logs.created_at` 兜底。
- 评估循环由服务端每 30 秒驱动，只在 `running` 课堂工作；进程重启后下一轮自动恢复。
- 学生回应只记录标签，暂不反过来影响后续提示的生成。
