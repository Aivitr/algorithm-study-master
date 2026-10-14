# 课堂教学设计 Agent

文件：`agent1_teaching_design.py`　｜　面向阶段：课堂创建之后、正式开课之前　｜　提交顺序：第 1 个

## 一句话说明

把课程主题与参考资料转化为可执行、可判定的教学目标，并在教师确认后写回课堂记录。

## 对应设计文档的哪些部分

对应《课堂小组分析 Agent 设计说明》中的以下章节：

| 设计文档部分 | 本文件中的对应实现 |
|---|---|
| 五、工具设计 | 按"读资料 → 读历史 → 生成 → 校验 → 写回"的顺序组织五个工具，工具只调用已有能力，不重复实现业务 |
| 七、权限与课堂生命周期 | 全部工具可读；写回工具 `save_learning_goals` 仅允许在"已建课未开课"状态下调用，并要求教师确认 |
| 八、循环与上下文工程 | 证据账本与结论自检：工具执行会登记证据编号，结论生成后再核对一次是否有证据支撑 |
| 九、三档运行时预算 | 模式命名与预算沿用文档定义，本文件使用其中的 on_demand 与 after_class 两档 |
| 十、输出契约 | 固定 JSON 输出：摘要、目标列表、质量提示、后续动作 |
| 十一、创新点与其最初做法（第 1 条） | "数字改为由代码计算"的思路在此处的落点是：目标是否可验证由代码打分，而不是由模型自称"已达标" |

## 完成了什么

工具清单：

| 工具 | 作用 | 状态 | 权限 |
|---|---|---|---|
| `get_course_materials` | 读取主题、参考资料、已有目标与课堂状态 | created/running/ended | 只读 |
| `get_previous_goals` | 读取同一位教师的历史教学目标 | 全部状态 | 只读 |
| `draft_learning_goals` | 生成候选目标，复用项目已有的模型通道 | 全部状态 | 只读 |
| `check_goal_quality` | 检查可验证性、表述长度与目标之间的重复度 | 全部状态 | 只读 |
| `save_learning_goals` | 把确认后的目标写回课堂记录 | created | 写，需确认 |

关键能力：

- **可验证性评分**：识别"说出、写出、设计、比较"等可观察行为动词，标记"了解、掌握、体会"等难以判定的表述，并给出 0 到 1 的分数与原因。
- **重复检测**：用二元组 Jaccard 相似度比较目标两两之间的重合度，避免生成语义重复的条目。
- **历史递进参照**：读取同一教师此前的教学目标，用于判断本节目标是否与前序课程形成递进。
- **写回可追溯**：写回的目标带有编号与初始状态，后续阶段可以直接读取。
- **证据账本**：每次工具调用登记证据编号（`E#`），结论需要引用编号，便于核查。
- **结论自检**：结论生成后再核对一次证据，缺乏支撑的表述会被写入 `unsupported_claims` 字段。

输出契约与设计文档第十节保持一致：`summary`、`structure`、`metrics_reading`、`findings`、`interventions`、`data_gaps`、`unsupported_claims`。

验证结果：`--selftest` 共 16 项检查，全部通过；`--check` 可验证模型配置与数据库连通性。

## 与相邻阶段的关系

- **上游**：依赖课堂记录中已有的主题与参考资料，不需要其他阶段的前置产物，是整条链路的起点。
- **本阶段新增**：把"生成目标"变成"生成可判定的目标"，并首次引入写操作与人工确认。
- **下游**：本阶段产出的学习目标是后续课中观察、协作分析与课后复盘判断"是否偏离目标""目标达成度多少"的基准，因此写回质量直接影响后续所有阶段的准确性。

## 运行方式

```bash
python agent1_teaching_design.py --tools
python agent1_teaching_design.py --selftest
python agent1_teaching_design.py --check
python agent1_teaching_design.py --meeting-id 12 --mode on_demand --question "帮我为这节课设计教学目标"
```

## 接入现有服务

把本文件夹整体放入项目根目录，然后在服务入口注册路由：

```python
from agent1_teaching_design.agent1_teaching_design import teaching_design_router
app.include_router(teaching_design_router)
```

接口：`GET /api/agents/teaching-design/tools`、`POST /api/agents/teaching-design/run`

## 已知边界

- 可验证性评分基于行为动词的词面判断，无法理解语义层面的目标质量。
- 写回会整组覆盖 `knowledge_points`，不保留历史版本；如需留痕应由外部做版本记录。
