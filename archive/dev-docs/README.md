# 开发过程文档 · 归档

本目录收 9 份**开发过程**产物：阶段总结、修复记录、审计报告。它们的共同点是
描述「当时做了什么、当时坏在哪」，而不是「现在该怎么用」——后者留在仓库根与
`docs/`。

```
dev-docs/
├── BUGFIX_*.md                     3 份修复记录
├── COMPLETE_SOLUTION_SUMMARY.md    阶段 1-4 总结
├── README_OPTIMIZATION.md          同上，快速开始版
├── GEMMA_INTEGRATION_REFACTOR_GUIDE.md
├── UI_UPGRADE_NOTES.md
├── DATABASE_AUDIT_REPORT.md
└── PROJECT_STATUS_REPORT.json      （见下方提醒）
```

---

## ⚠️ 关于 `PROJECT_STATUS_REPORT.json`

这是一份**机器生成、且属于另一台机器**的报告，不能当作当前仓库的状态。

实测：它内部有 **12 处**硬编码绝对路径，形如

```
D:\\study system\\change\\algorithm-study-master\\...
```

那是**本项目迁移前**的路径。也就是说：

- 它记录的「哪些文件存在」是**过去某个时刻、在另一台机器上**的事实；
- 拿它对当前仓库做判断会得到错误结论。

保留它是为了留下那份状态快照（以及 `check_project_status.py` 曾产出过什么），
**但不要用它核对现状**。当前状态以仓库实际内容为准。

---

## 清单

| 文件 | 行数 | 内容 |
|---|---|---|
| `COMPLETE_SOLUTION_SUMMARY.md` | 537 | 多人教室语音识别优化方案 · 阶段 1–4 完整总结 |
| `GEMMA_INTEGRATION_REFACTOR_GUIDE.md` | 515 | Gemma 接入重构执行文档（明确「阿里云 ASR 保持不变」） |
| `README_OPTIMIZATION.md` | 402 | 同一方案的快速开始指南 |
| `UI_UPGRADE_NOTES.md` | 344 | 界面升级说明 |
| `BUGFIX_AGORA_GATEWAY_ERROR.md` | 287 | Agora 连接错误 `CAN_NOT_GET_GATEWAY_SERVER` |
| `BUGFIX_AGORA_TOPIC.md` | 241 | Agora Token 与课堂主题 |
| `BUGFIX_SHOWTOAST_ERROR.md` | 177 | `showToast` 错误排查 |
| `DATABASE_AUDIT_REPORT.md` | 155 | 数据库配置全面审计报告 |
| `PROJECT_STATUS_REPORT.json` | 73 | 机器生成的状态快照（**见上方提醒**） |

前二份与 `COMPLETE_SOLUTION_SUMMARY.md` / `README_OPTIMIZATION.md` 描述的正是
`../speech-stages/` 那条工作线——那 7 个模块为什么会被取代，这两套文档是背景。

### 关于 `DATABASE_AUDIT_REPORT.md` 的一处**空白**

该报告是**生产库结构的权威记录**之一（`../ops-scripts/README.md` 也指向它）。
但实测：它**未提及** `transcripts` 表上那五个研究列——
`binding_source`、`binding_confidence`、`identity_review_status`、
`identity_review_note`、`cross_modal_consistency`。

这影响一次具体的核验判断：**这份审计报告不能用来证明
那五列在生产库中存在或不存在**，它两侧都没有覆盖。

---

## 查阅指引

- 生产库有哪些表/列**不在 ORM 里** → 本目录 `DATABASE_AUDIT_REPORT.md`
- 运维脚本如何连库、有哪些防护 → `../ops-scripts/README.md`
- 那条语音优化工作线本身 → `../speech-stages/README.md`
