# 关闭投票幂等性修复说明
本次修改设计四个文件
app/routers/votes.py
static/js/app.js
index.html
tests_safe/test_vote_close_idempotency.py

## 1. 问题描述

原 `/api/close-vote` 接口没有判断投票是否已经关闭。教师重复点击“结束投票”或多个关闭请求同时到达时，后端会重复执行以下操作：

- 重新关闭投票；
- 重复调用 LLM；
- 重复生成子目标；
- 重复向 `Meeting.knowledge_points` 追加子目标；
- 重复广播投票结果。

最终会造成课堂目标数据污染。

## 2. 原因分析

原接口只检查投票是否存在，没有检查其 `status`，并且“检查状态”和“修改状态”不是原子操作。

此外，教师手动关闭和学生全部确认后的自动关闭分别实现了一套关闭逻辑，两条路径之间也可能发生重复执行。

## 3. 修改内容

### 后端

在 `app/routers/votes.py` 中增加 `_claim_vote_close()`：

- 通过数据库条件更新，将 `active` 原子修改为 `closed`；
- 只有第一个请求能成功获得关闭权；
- 后续请求返回 `already_closed=true`；
- 后续请求不再调用 LLM、追加子目标或广播结果；
- 同时校验 `vote_id` 与 `meeting_id` 的归属关系；
- 教师手动关闭和学生确认自动关闭均使用相同的原子关闭控制。

### 前端

在投票关闭请求期间：

- 设置 `voteClosing` 状态；
- 禁用“结束投票”按钮；
- 显示“正在结束……”；
- 避免用户连续点击产生重复请求。

前端控制仅用于改善用户体验，真正的数据一致性仍由后端保证。

## 4. 测试验证

新增：

`tests_safe/test_vote_close_idempotency.py`

覆盖以下场景：

1. 相同投票连续关闭两次，只追加一次子目标；
2. 同一投票的原子关闭权只能取得一次；
3. 教师手动关闭后，学生再次确认不会重复执行关闭副作用。

运行命令：

```powershell
docker compose exec app python -m pytest tests_safe/test_vote_close_idempotency.py -v