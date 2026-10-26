
## 一、新建的业务代码文件

### 1. 课堂状态统一定义

[app/core/meeting_state.py](algorithm-study-master-main/app/core/meeting_state.py:1)

新增内容：

- 定义三种课堂状态：
  - `created`：课堂已创建但未开始
  - `running`：课堂正在进行
  - `ended`：课堂已经结束
- 提供公共常量：
  - `CREATED`
  - `RUNNING`
  - `ENDED`
- 提供 `meeting_status_error()`，统一生成状态不允许时的提示。

作用是避免各个文件继续手写 `"active"`、`"ended"` 等字符串。

### 2. 课堂生命周期 Service

[app/services/meeting_lifecycle.py](algorithm-study-master-main/app/services/meeting_lifecycle.py:1)

新增两个数据库状态转换函数：
- `claim_start()`
  - 只有 `created` 才能更新成 `running`
  - 同时写入 `started_at`
- `claim_end()`
  - 只有 `running` 才能更新成 `ended`
  - 同时写入 `ended_at`
这里使用带旧状态条件的原子 `UPDATE`：

```text
created → running
running → ended
```

即使两个请求几乎同时到达，也只有一个请求能够真正修改成功，另一个请求只会得到“已经开始”或者“已经结束”的结果。

### 3. 存量数据库迁移脚本

[db/migrations/20261024_meeting_lifecycle.sql](algorithm-study-master-main/db/migrations/20261024_meeting_lifecycle.sql:1)

这是专门给已经存在数据的数据库使用的迁移脚本，负责：
- 增加 `started_at`
- 将旧状态迁移：
  - `active → running`
  - `paused → running`
  - `NULL → created`
  - `ended` 保持不变
- 对旧课堂近似回填 `started_at`
- 将旧默认值 `active` 删除
- 将新默认值设置为 `created`
- 将 `status` 改为非空
- 增加 CHECK 约束，只允许：
  - `created`
  - `running`
  - `ended`
- 如果发现未知状态，不会擅自转换，而是终止迁移并提示检查数据。
## 二、数据库和 ORM 文件
### 4. Meeting ORM 模型

[app/models/classroom.py](algorithm-study-master-main/app/models/classroom.py:18)

修改内容：

- `Meeting.status` 默认值由 `active` 改为 `created`
- 设置 `nullable=False`
- 增加 `started_at`
- 增加状态 CHECK 约束
- 更新状态注释为 `created/running/ended`

现在代码中新建：
```python
meeting = Meeting(...)
```
即使不手动填写状态，最终也会得到：

```python
status = "created"
started_at = None
ended_at = None
```

### 5. SQL Server 建表脚本

[db/schema.sql](algorithm-study-master-main/db/schema.sql:169)

修改了 `meetings` 表定义：

- `status` 默认值改成 `created`
- `status` 改成非空字段
- 增加 `started_at`
- 增加三状态 CHECK 约束

同时在建表脚本中加入幂等升级逻辑。这样：

- 新数据库会直接创建正确结构
- 已经存在的数据库也会自动升级
- 重复运行脚本不会重复添加字段或约束

### 6. 数据库初始化脚本

[db/init.sh](/algorithm-study-master-main/db/init.sh:42)

修复了执行 `schema.sql` 时使用的数据库主机变量：

```text
DB_HOST → MSSQL_HOST
```
原脚本前面定义的是 `MSSQL_HOST`，最后却误用了 `DB_HOST`。如果不修复，数据库迁移脚本可能无法正常执行。

---

## 三、开始和结束课堂接口

### 7. 课堂操作接口

[app/routers/classroom_ops.py](algorithm-study-master-main/app/routers/classroom_ops.py:1)

这是改动最多的后端文件之一。

#### 新增 `POST /api/start-class`

[开始课堂接口](algorithm-study-master-main/app/routers/classroom_ops.py:109)

处理规则：

- 课堂不存在：拒绝
- 操作者不是本课堂教师：拒绝
- 当前是 `created`：
  - 更新为 `running`
  - 写入 `started_at`
- 当前已经是 `running`：
  - 返回成功
  - `already_started = true`
  - 不重复执行开始操作
- 当前是 `ended`：
  - 拒绝重新开始

#### 完善 `POST /api/end-class`

[结束课堂接口](algorithm-study-master-main/app/routers/classroom_ops.py:160)

处理规则：

- 课堂不存在：拒绝
- 不是本课堂教师：拒绝
- 当前是 `created`：
  - 拒绝结束
  - 提示课堂尚未开始
- 当前是 `running`：
  - 更新为 `ended`
  - 写入 `ended_at`
  - 广播一次课堂结束
  - 关闭课堂连接
- 当前已经是 `ended`：
  - 返回成功
  - `already_ended = true`
  - 不再广播
  - 不再重复关闭连接

#### 其他状态检查

还在这个文件里给以下接口增加了 `running` 检查：

- `GET /api/agora-token`
- `POST /api/suggest-topic`
- `POST /api/quick-decompose`
- `POST /api/cluster-viewpoints`

---

## 四、登录和课堂进入流程

### 8. 登录、建课和加入课堂

[app/routers/auth.py](/algorithm-study-master-main/app/routers/auth.py:176)

修改内容：

- 不再只查询旧的 `active` 课堂
- 根据课堂码查询真实课堂，再检查状态
- 教师建课时状态设为 `created`
- 学生可以查询或加入：
  - `created`
  - `running`
- `ended` 课堂禁止重新加入
- 教师只能管理自己创建的课堂
- 不再信任前端传来的 `role` 字段决定能否创建课堂，而是使用数据库里的真实用户角色
- 阻止学生通过伪造 `role=teacher` 创建课堂
- 登录响应增加：
  - `meeting_status`
  - `created_at`
  - `started_at`
  - `ended_at`

---

## 五、课堂中业务功能的状态检查

### 9. 投票接口

[app/routers/votes.py](/algorithm-study-master-main/app/routers/votes.py:1)

给以下操作增加了课堂状态检查：

- 学生投票
- 关闭投票
- 确认投票结果

要求课堂必须是 `running`。

同时增加了投票和课堂的归属检查，防止把 A 课堂的投票 ID 带到 B 课堂进行操作。

注意：这里的投票状态依然是：

```text
active / closed
```

它是“投票的状态”，不是“课堂的状态”，所以没有改成 `running`。

### 10. WebSocket 和沉默检测

[app/routers/realtime.py](algorithm-study-master-main/app/routers/realtime.py:1)

增加了 `_meeting_is_running()` 检查。

以下 WebSocket 只允许连接 `running` 课堂：

- `/ws/{username}/{meeting_id}`
- `/ws-asr/{username}/{meeting_id}`
- `/ws-signal/{username}/{meeting_id}`

以下接口也只允许在 `running` 使用：

- `/api/browser-asr-final`
- `/api/check-silence`
- `/api/check-quiet-members`

未开始或已经结束的课堂会拒绝继续写入实时数据。

### 11. 发言保存和分析

[app/realtime/speech.py](algorithm-study-master-main/app/realtime/speech.py:1)

增加状态检查：

- 非 `running` 课堂不保存新发言
- 非 `running` 课堂不继续进行完整发言分析
- 非 `running` 课堂不继续进行流式发言分析

避免课堂结束后，延迟到达的语音结果继续污染数据库。

### 12. 音视频数据处理

[app/realtime/stream.py](algorithm-study-master-main/app/realtime/stream.py:1)

增加检查：

- 只有 `running` 课堂才保存和处理音视频数据
- `created` 和 `ended` 不再继续写入音视频结果

### 13. 知识图谱更新

[app/realtime/knowledge_graph.py](algorithm-study-master-main/app/realtime/knowledge_graph.py:1)

知识图谱实时更新只允许在 `running` 状态执行。

### 14. 报告生成

修改了三个报告入口：

- [app/routers/reports.py](algorithm-study-master-main/app/routers/reports.py:39)
- [app/routers/report_stream.py](algorithm-study-master-main/app/routers/report_stream.py:57)
- [app/routers/pdf_report.py](algorithm-study-master-main/app/routers/pdf_report.py:30)

现在：

- `created`：不能生成正式报告
- `running`：不能生成正式报告
- `ended`：允许生成报告

报告查询接口仍然可以正常读取已有报告。

---

## 六、查询和统计接口

### 15. 课堂信息查询

[app/routers/meeting.py](/algorithm-study-master-main/app/routers/meeting.py:60)

`GET /api/meeting/{meeting_id}` 增加返回：

- `meeting_status`
- `created_at`
- `started_at`
- `ended_at`

课堂总结接口只允许针对：

- `running`
- `ended`

### 16. 学生统计

[app/routers/student_stats.py](algorithm-study-master-main/app/routers/student_stats.py:1)

修改内容：

- 历史记录按照 `started_at` 和 `ended_at` 计算时间
- `created` 课堂时长为 0
- 学生首页统计分别计算：
  - `createdClasses`
  - `activeClasses`，对应 `running`
  - `completedClasses`，对应 `ended`
- 活跃课堂查询由旧的 `active` 改成 `running`

### 17. 教师统计

[app/routers/teacher.py](algorithm-study-master-main/app/routers/teacher.py:1)

修改内容：

- `created` 课堂不参与课堂活跃度、风险和平均分计算
- 课堂时长优先使用：
  - `started_at`
  - `ended_at`
- 教师课堂列表增加：
  - `started_at`
  - `ended_at`

### 18. 未接线路由说明

[app/routers/unrouted.py](algorithm-study-master-main/app/routers/unrouted.py:1)

没有启用其中未完成的接口，只把文档里的接口总数从 59 更新成 60。

---

## 七、前端文件

### 19. 页面模板

[index.html](algorithm-study-master-main/index.html:483)

修改内容：

- 课堂状态显示改为：
  - 待开始
  - 进行中
  - 已结束
- `created` 课堂显示“开始课堂”按钮
- 只有 `running` 课堂显示“结束课堂”按钮
- 状态标签不再使用旧的 `active`
- 教师课堂管理页面增加开始课堂入口

### 20. 前端业务逻辑

[static/js/app.js](algorithm-study-master-main/static/js/app.js:1)

新增状态数据：

- `meetingStatus`
- `meetingStartedAt`
- `meetingEndedAt`

主要修改：

- 建课成功后，不会立即进入实时课堂
- 教师需要点击“开始课堂”
- 新增 `startClassFromManage()`
- 只有 `running` 才会：
  - 启动课堂计时器
  - 加入 Agora
  - 建立实时连接
  - 启动沉默检测
- 使用后端 `started_at` 计算真实课堂时长
- 教师结束课堂失败时，不会错误退出页面
- 收到 `class_ended` 广播后更新状态并清理连接
- 学生主动退出 `running` 课堂时不再提前生成正式报告
- 正式报告在收到课堂结束事件后延迟生成
- 新增：
  - `meetingStatusLabel()`
  - `meetingStatusBadgeClass()`
  - `scheduleReportGeneration()`

### 21. 应用入口说明

[server.py](algorithm-study-master-main/server.py:126)

新增 `/api/start-class` 后，业务接口数量由 59 变成 60，因此同步更新了相关注释。

---

# 测试方面修改了什么

## 一、新建的测试文件

### 1. 课堂生命周期测试

[tests_safe/test_meeting_lifecycle.py](algorithm-study-master-main/tests_safe/test_meeting_lifecycle.py:1)

这是本次唯一全新建立的测试文件。

包含以下测试：

1. 新建课堂默认是 `created`
2. 新建课堂的 `started_at` 和 `ended_at` 为空
3. 第一次开始课堂：
   - 状态变成 `running`
   - 写入 `started_at`
4. 重复开始课堂：
   - 返回 `already_started=true`
   - `started_at` 不变化
5. 两个开始请求竞争时，只有一个能取得状态转换权
6. `created` 课堂不允许结束
7. 其他教师不能开始不属于自己的课堂
8. 学生不能伪造 `role=teacher` 创建课堂
9. 第一次结束课堂：
   - 状态变成 `ended`
   - 写入 `ended_at`
   - 只广播一次
10. 重复结束课堂：
    - 返回 `already_ended=true`
    - 不再广播
    - `ended_at` 不变化
11. `ended` 课堂不能重新开始
12. `created` 课堂不能调用只允许 `running` 的接口

---

## 二、修改的已有测试文件

### 2. 投票关闭幂等性测试

[tests_safe/test_vote_close_idempotency.py]

修改测试课堂状态：

```text
active → running
```

并补充 `started_at`。

投票记录本身仍然保持：

```text
active → closed
```

原有三项投票幂等测试继续保留：

- 重复关闭只追加一次子目标
- 原子关闭只有一次成功
- 手动关闭后再确认不会重复执行副作用

### 3. 测试数据夹具

[tests_safe/fixtures.py]

修改内容：

- 已结束课堂增加 `started_at`
- 进行中课堂状态由 `active` 改成 `running`
- 进行中课堂增加 `started_at`

### 4. LLM 接口打桩测试

[tests_safe/test_endpoints_mocked.py]

话题建议现在只允许 `running` 课堂，因此原测试由已结束的 1 号课堂改成运行中的 2 号课堂。

### 5. WebSocket 测试

[tests_safe/test_websocket_and_manager.py]
以前测试直接连接不存在的假课堂 ID。

现在状态门禁生效后，不存在的课堂必须拒绝连接，所以测试新增 `running_ws_meetings` 夹具，先建立真实的 `running` 测试课堂，再检查：

- 加入广播
- ping/pong
- 同课堂成员可见
- 不同课堂成员隔离

### 6. 路由契约测试

[tests_safe/test_route_contract.py]

修改内容：

- 加入 `POST /api/start-class`
- HTTP 路由数量由 56 改成 57
- 总业务接口数量由 59 改成 60

### 7. 路由响应基线

[tests_safe/baselines/routes.json]

只更新了与本次改动有关的响应：

- 首页 HTML
- 课堂历史
- 课堂信息
- 学生首页统计
- 教师课堂列表

没有用重新录制的方式覆盖其他环境相关基线。

### 8. 其他测试说明文件

同步更新接口数量注释：

- [tests_safe/test_readme_routes.py]
- [tests_safe/test_routers_layout.py]

---

最终与这次改动直接相关的测试结果是：

```text
108 passed
1 skipped
```

全套测试结果是：

```text
385 passed
11 skipped
4 failed
```

剩余 4 个失败来自仓库原先缺少的文档、Agora 临时目录和环境相关旧基线，不是状态机修改产生的功能错误。

---

## 四、结束课堂收尾补充（2026-10-26）

在原有 CAS + 幂等 + 归属校验的基础上，`/api/end-class` 补齐以下收尾动作，均只在
CAS 取得结束权的那个请求里执行：

- 冻结本课堂仍在进行中的投票（`status: active -> closed`，记录 `closed_at`）；
- 清理本课堂的内存态：`vote_confirmations`、`silence_notified`；
- 关闭聊天、实时语音（含 ASR 会话）与信令三类 WebSocket 连接；
- **由后端触发一次课后报告任务**：按课堂内学生名单逐个生成报告，单个失败不影响其余；
  前端不再调用 `generate-report-stream`，避免重复生成。

未完成（前置依赖未就绪，登记为后续）：

- 处理已提交但未完成的分析任务——需要 A6 的「在途分析登记表」；
- 停止课堂 Agent 与后端监测任务——A6/A7 尚未实现。

当前全套测试结果：`438 passed / 2 skipped`。
