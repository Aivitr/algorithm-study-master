# gca_engine（vendor 快照）

- 来源：`https://github.com/a1helen0722-sys/group-analytics-engine`
- 分支：`develop`
- 提交：`ec1c7ea`（第二次合并后的状态，含中文分词、固定/滑动窗口、服务层加固）
- 迁入日期：2026-10-28
- 对应测试：`tests_safe/gca/`（原样复制）

约定：

- 本目录内代码**不在主仓库直接修改**；算法变更回到上游仓库提交，再按新提交重新同步。
- 主仓库只通过 `app/services/gca_service.py` 调用 `analyze_utterances()`，
  不使用 `gca_engine.service` 的进程内登记表。
- 上游 `feature/lei-engine` 还有两个窗口修复（`1360e0b`、`5890a6b`）未合并进
  `develop`，且与 `develop` 的 `Utterance` 校验存在测试冲突；同步前需上游先整合。
