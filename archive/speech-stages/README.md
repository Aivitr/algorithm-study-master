# 多说话人课堂语音识别优化（Stage 1–5）· 归档

本目录收「多人教室语音识别优化方案」这一整条工作线的产物。它是一次**分阶段推进、
到 Stage 5 为止未全部完成**的改造：Stage 1–4 有实现与文档，Stage 5 只有规划。

```
speech-stages/
├── modules/        7 个模块：说话人分离 / 声纹 / 音量过滤
├── tests/          3 个验证脚本
├── verification/   3 个阶段验收脚本
├── docs/          12 份阶段文档（Stage 1–5 与 P4）
└── audio_constraint_test.html   前端音频约束的测试页
```

---

## ⚠️ 本目录的脚本**归档后不再可直接运行**

这不是缺陷，是这次搬迁的**已知代价**，归档时已登记并接受。

### 原因：裸文件名引用

`verification/check_project_status.py` 用**裸文件名**引用 **14 个同级文件**
（实测清点）：

```
COMPLETE_SOLUTION_SUMMARY.md          PROJECT_STATUS_REPORT.json
STAGE1_SPEAKER_LOCK_IMPLEMENTATION.md STAGE2_CROSS_USER_DEDUP_IMPLEMENTATION.md
STAGE3_SPEAKER_VOLUME_ARBITRATION_IMPLEMENTATION.md
STAGE4_FRONTEND_AUDIO_CONSTRAINT_IMPLEMENTATION.md  STAGE4_TEST_CHECKLIST.md
audio_constraint_test.html            index.html
server.py                             test_cross_user_dedup.py
test_speaker_lock.py                  test_speaker_volume_arbitration.py
verify_stage4.py
```

归档前这 14 个都在仓库根，所以它能跑。归档后它们被分到
`docs/` `tests/` `verification/` 和仓库根，**裸文件名解析到的位置全变了**。

当时的取舍是：归档结构本身就要求把它们分到四个子目录，所以取另一半要求——
**用 README 记录，而不是保持可运行**。这些脚本的价值在记录阶段进展，不在执行。

### 两个本来就坏的导入（与本次归档无关，原样保留）

| 位置 | 问题 |
|---|---|
| `modules/voiceprint_api.py:7` | `from flask import app`——**这是个 FastAPI 项目**。该文件从来没有成功导入过。另：它引用的 `ROOT_DIR` 也未定义 |
| `modules/aliyun_speaker_diarization.py:10` | `from ai_core import refresh_aliyun_token, ALIYUN_CONFIG`——已核对，**这两个名字在 `ai_core.py` 中确实存在**（第 12、24 行），所以这一条是可解析的；但 `ai_core` 仍是仓库根的运行期模块，本归档模块与它有依赖关系 |

**这两处都没有修**。不改内容、不删文件：保留它作为「当时的真实状态」的证据。

### `tests/` 里那 3 个脚本为什么还能导入 `server`

```python
from server import manager, ConnectionManager   # test_cross_user_dedup.py:20
from server import manager                      # 另两个
```

阶段 3 把 `ConnectionManager` / `SignalConnectionManager` 迁去了
`app/realtime/`。但 `server.py` **仍然持有这几个名字**
（已用 AST 核对 `manager` / `ConnectionManager` / `signal_manager` /
`SignalConnectionManager` 四个名字均在 `server.py` 的模块级命名空间中），
所以上面这些导入**依然成立**。保留这些名字是有意的——它们让搬迁对旧引用透明。

不过这些脚本**不会再被收集**：`pytest.ini` 限定 `testpaths = tests_safe`，
且 `archive/legacy-tests/conftest.py` 的同类闸门不覆盖本目录。
它们也不在 `tests_safe/` 的导入隔离之内。

---

## 清单

### `modules/`（7 个）

| 文件 | 行数 | 内容 |
|---|---|---|
| `aliyun_speaker_diarization.py` | 385 | 阿里云说话人分离 |
| `speaker_diarizer.py` | 371 | 说话人分离 |
| `voiceprint_realtime_transcriber.py` | 281 | 声纹实时转写 |
| `voiceprint_api.py` | 254 | 声纹 API（**坏**，见上） |
| `voiceprint_service.py` | 212 | 声纹服务 |
| `lightweight_voice_filter.py` | 196 | 轻量语音过滤（音量/能量门限） |
| `async_voiceprint_transcriber.py` | 160 | 异步声纹转写 |

**为什么它们不在 `app/`**：AST 实测，`server.py` 的导入传递闭包为 15 个模块，
**这 7 个一个都不在其中**——当前实时主链路走的是 `ai_core` +
`voiceprint_manager`，不是这一支。它们是被取代的那一支。

### `tests/`（3 个）

| 文件 | 行数 | 对应阶段 |
|---|---|---|
| `test_cross_user_dedup.py` | 379 | 阶段 2：跨用户重复文本抑制 |
| `test_speaker_volume_arbitration.py` | 278 | 阶段 3：音量仲裁说话人 |
| `test_speaker_lock.py` | 204 | 阶段 1：发言席位锁 |

### `verification/`（3 个）

| 文件 | 行数 | 内容 |
|---|---|---|
| `check_project_status.py` | 297 | 按 14 个同级文件的存在性汇总项目状态（见上「裸文件名引用」） |
| `verify_stage4.py` | 199 | Stage 4 验收 |
| `verify_p4_completion.py` | 190 | P4 任务完成度验收 |

### `docs/`（12 份）

**Stage 1–5 的实现/规划（9 份）**

| 文件 | 标题 |
|---|---|
| `STAGE1_SPEAKER_LOCK_IMPLEMENTATION.md` | 阶段1 实现：发言席位锁（Speaker Lock） |
| `STAGE2_CROSS_USER_DEDUP_IMPLEMENTATION.md` | 阶段2 实现：跨用户重复文本抑制 |
| `STAGE3_SPEAKER_VOLUME_ARBITRATION_IMPLEMENTATION.md` | 阶段3 实现：音量仲裁说话人 |
| `STAGE4_COMPLETION_SUMMARY.md` | 阶段4 完成总结 · 最终报告 |
| `STAGE4_DEPLOYMENT_CHECKLIST.md` | 阶段4 完成及最终部署清单 |
| `STAGE4_FRONTEND_AUDIO_CONSTRAINT_IMPLEMENTATION.md` | 阶段4 实现：前端音频采集强约束 |
| `STAGE4_TEST_CHECKLIST.md` | 阶段4 前端音频约束 · 测试清单 |
| `STAGE4_VERIFICATION_REPORT.json` | 阶段4 验收报告（JSON） |
| `STAGE5_INTERACTIVE_FALLBACK_PLAN.md` | 阶段5 交互式兜底 · **完整规划**（仅规划，无实现） |

**P4 测试质量保证（3 份）**

| 文件 | 标题 |
|---|---|
| `P4_COMPLETION_SUMMARY.md` | P4 测试质量保证 · 任务完成总结 |
| `P4_QUICK_REFERENCE.md` | P4 任务完成速查表 |
| `P4_TEST_EXECUTION_GUIDE.md` | P4 测试质量保证执行指南 |

### `audio_constraint_test.html`

Stage 4「前端音频采集强约束」的测试页（17KB）。归档清单未枚举此文件；
实测它只被 `check_project_status.py` 与 `verify_stage4.py` 引用，二者都属 Stage 4，
故随本工作线归档。放在本目录根而非 `docs/`，因为它是**工具**不是文档。

---

## 查阅指引

- 映射依据与取舍 → `archive/README.md`
- 为什么这 7 个模块不在 `app/` → `archive/README.md` + 本文件
- 声纹管理器（**仍在使用**的那个，与这里的不同）→ 仓库根 `voiceprint_manager.py`
