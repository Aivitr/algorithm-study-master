# archive/ —— 归档总览

本目录收**不再参与运行**的代码与文档。归档不等于删除：
**没有删除任何文件**，只是把它们从仓库根搬到这里并分类。

```
archive/
├── prototypes/      早期原型（1/ 与 3/，已被现方案替代）
├── speech-stages/   多说话人课堂语音识别优化（Stage 1–5），未完成的改造线
├── legacy-tests/    遗留测试（原 tests/、test/、根级 test_*.py）—— ⚠️ 见下
├── ops-scripts/     手动执行的运维/维护脚本 —— ⚠️ 见下
├── dev-docs/        开发过程文档（阶段总结、修复记录、审计报告）
├── vendors/         第三方依赖内置副本（**有意为空**）
└── unsorted/        未归类备用（**有意为空**）
```

逐文件的映射依据与取舍，各子目录的 README 里逐条写明。

---

## ⚠️ 两个目录不是"看着玩"的：它们会连生产库

**这不是危言耸听，已经真实发生过一次。**

本仓库工作区的 `.env` 指向**生产阿里云 RDS**。而：

- `database.py` 在**模块导入期**就执行 `_ensure_transcripts_columns()`
  （`database.py:243`），必要时对 `DATABASE_URL` 执行
  `ALTER TABLE transcripts ADD ...`。**`import database` 这个动作本身即 DDL。**

于是：

| 目录 | 风险 |
|---|---|
| `legacy-tests/` | 里面的文件顶部写着 `from server import app`——**收集它们 = 触发上面那条 DDL** |
| `ops-scripts/` | 是**手动执行**的脚本，绕开应用直连数据库；`init_db.py` 一句命令就是 `CREATE TABLE` |

**不要直接对这些目录跑 pytest 或 python。** 各目录的 README 开头都写了具体防护。

### 三道闸门（按可靠性排序）

| # | 位置 | 覆盖范围 |
|---|---|---|
| 1 | 仓库根 `conftest.py` | **所有** pytest 调用——把 `DATABASE_URL` 换成临时 sqlite、`DB_*` 换成不可达值 |
| 2 | `legacy-tests/conftest.py` 的 `pytest_configure` | 参数指向该目录时**中止会话**（退出码 4） |
| 3 | `ops-scripts/_prod_guard.py` | 这些脚本运行前检查目标；**远程库要求显式确认**，否则退出码 2 |

第 2 道之所以要单独存在：**显式给出的路径参数绕得过一切基于收集钩子的机制**
（`testpaths`、`collect_ignore`、`pytest_ignore_collect` 全部失效）。
这一点是实测得出的，不是推断——过程记在 `legacy-tests/conftest.py` 的文件头。

---

## 各目录一句话

| 目录 | 是什么 | 先读 |
|---|---|---|
| `prototypes/` | 原 `1/`、`3/` 两组来历不明的旧脚本。编号含义无文档记载，故不沿用编号命名 | `prototypes/README.md` |
| `speech-stages/` | 一条走到 Stage 5 就停下的工作线：7 个模块 + 3 个测试 + 3 个验收脚本 + 12 份文档。归档后脚本不再可直接运行（裸文件名引用失效） | `speech-stages/README.md` |
| `legacy-tests/` | 39 个文件，**13 个踩在生产库 DDL 路径上**。内含一次真实事故的记录 | `legacy-tests/README.md` |
| `ops-scripts/` | 会连库的运维脚本，含 `_prod_guard` 防护 | `ops-scripts/README.md` |
| `dev-docs/` | 9 份开发过程文档。注意 `PROJECT_STATUS_REPORT.json` 是**另一台机器**的旧快照 | `dev-docs/README.md` |
| `vendors/` | 有意为空——唯一候选被 gitignore 且是运行期条件引用，移走会静默失效 | `vendors/README.md` |
| `unsorted/` | 有意为空——已登记的"未归类备用"落点 | `unsorted/README.md` |

---

## 归档的边界：什么**没有**进来

以下有意留在仓库根，理由是它们**仍参与运行**：

| 类别 | 文件 |
|---|---|
| 前端运行文件 | `index.html`、`pcm-processor.js` |
| 模型资产 | `haarcascade_frontalface_default.xml` |
| 研究模块资产 | `prepare_enhanced_model_layout.ps1`、`setup_enhanced_runtime.ps1`、`install_enhanced_models_from_local.ps1`、`download_enhanced_open_models.py`、`requirements_enhanced_runtime.txt`、`enhanced_bridge_templates/` |
| 运行期模块 | 15 个 `.py`——它们将迁往 `app/`（阶段 3 的后续步骤），**不是归档对象** |

最后一类值得强调：**`archive/` 只收"不再运行"的东西。** 那 15 个模块虽然最终也会
离开仓库根，但去处是 `app/`，理由是"换个更清楚的位置"，不是"不再需要"。

判断依据是 AST 实测的 `server.py` 导入传递闭包（15 个模块）加上字符串引用扫描——
两者都不命中的才是归档对象。**单靠 `import` 语句不够**：`research_runtime.py:940`
是用**路径字符串**引用同级脚本的，只查 import 会漏。
