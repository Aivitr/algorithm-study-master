# 行为投入模块说明

## 1. 教育学背景

行为投入（Behavioral Engagement）关注学习者在学习活动中的可观察参与行为，包括参与讨论、提出问题、回应任务与持续投入努力等外显活动。在课堂协作讨论场景中，口头发言频次、发言占比以及成员之间的轮次分配，能够为教师提供小组参与活跃度与话语分布的客观观察线索。[Fredricks、Blumenfeld 与 Paris（2004）](https://doi.org/10.3102/00346543074001059)

群体沟通分析（Group Communication Analysis，GCA）将参与度（`participation`）、社会影响力（`social_impact`）与沟通密度（`communication_density`）等可计算特征用于刻画多人互动中的个体角色与群体动态。为了进一步描述活跃发言人之间的话语分配是否集中在少数人手中，本模块同时输出发言占比总体标准差、最大单人占比与归一化香农熵（Pielou 均匀度，`H / ln(k)`，仅在活跃发言人 ≥ 2 时计算）。[Dowell、Nixon 与 Graesser（2019）](https://doi.org/10.3758/s13428-018-1102-z) · [Pielou（1966）](https://doi.org/10.1016/0022-5193(66)90013-0)

需要明确教育学解释边界：**发言次数与频率只反映可观察的口头参与行为，发言少不等于没有参与思考，也不直接等同于学习投入低。** 沉默学生可能正在阅读材料、倾听同伴或进行独立推理；同样，发言频繁也不必然意味着讨论有效或理解深入。因此，本轮模块只输出可解释的基础统计与时间变化趋势，**不计算未经实证标定的行为投入综合分**，输出结果仅作为教师观察与后续提示候选的参考依据。

## 2. 数据来源与计算

`analyze_behavioral(meeting_id, utterances, gca_result=None, ...)` 接收同一小组的 `Utterance` 列表及可选的既有 `GroupAnalysisResult`，通过公共工厂返回 `EngagementDimensionResult`（`dimension="behavioral"`）。学生标识使用字符串形式的 `user_id`（与 `Utterance.speaker_id` 一致），时间戳统一为课堂开始后的相对秒数。非法的 `meeting_id`、非列表输入、跨小组发言、重复 `utterance_id`、非法窗口参数或不一致的 `gca_result` 结构会抛出 `ValueError`。[公共协议](engagement_protocol.md#4-三个维度模块的函数契约) · [行为模块实现](../gca_engine/engagement/behavioral.py)

在计算前，模块按 `(timestamp, utterance_id)` 稳定排序，并按课堂适配器规则调用 `normalize_text` 过滤空白与纯 ASR 噪声标记（如 `[静音]`、`[噪音]`、`<unk>`）的无效发言，同时在 `warnings` 与 `metadata.empty_text_count` 中记录排除数量。[中文预处理](../gca_engine/preprocessing/chinese.py)

### 2.1 学生级与小组级指标

| 指标 | 位置 | 来源与计算口径 |
| --- | --- | --- |
| `utterance_count` | `student_metrics` / `group_metrics` | 该学生的有效发言条数（`float`）。 |
| `participation` | `student_metrics` / `group_metrics` | 发言占比 `count(a) / n`。当传入有效且批次一致的 `gca_result` 且无空文本过滤时，直接复用 GCA 结果；否则调用 `gca_engine.core.participation.participation` 在有效发言上计算，避免分母口径漂移。 |
| `utterances_per_minute` | `student_metrics` / `group_metrics` | 发言频率 `utterance_count / (duration_seconds / 60)`。当有效观察时长为 `0` 秒时省略该字段并记录警告，不除零。 |
| `speaking_duration_seconds` | `student_metrics` / `group_metrics`（可选） | 汇总有效 `end_time - timestamp`。当前真实课堂适配器一律传入 `end_time=None`，缺失时优雅降级跳过并在 `metadata`（`speaking_duration_available=False`、`end_time_coverage=0.0`）与 `warnings` 中标注；部分覆盖时仅统计含 `end_time` 的发言且不对缺失学生补零。 |
| `social_impact` | `student_metrics` / `group_metrics`（可选） | 传入有效、批次一致且为多人的 `gca_result` 时直接复用（不重算 LSA/GCA）；单人发言因缺少比较对象省略。 |
| `communication_density` | `student_metrics` / `group_metrics`（可选） | 传入有效且批次一致的 `gca_result` 时直接复用。 |
| 群体参与分布 | `metadata.group_distribution` | 包含 `active_speaker_count`（活跃发言人数）、`total_utterances`、`participation_std`（参与占比总体标准差）、`max_participation_share`（单人最高发言占比）与 `normalized_entropy`（归一化香农熵，范围 `[0, 1]`，仅在活跃人数 ≥ 2 时计算，单人为 `None`）。 |

小组汇总严格沿用 `gca_engine/aggregation.py` 口径，对每项存在有效有限值的指标输出 `mean / min / max / std / count`（总体标准差 `ddof=0`），缺失指标不补零。[小组统计口径](../gca_engine/aggregation.py) · [参与度实现](../gca_engine/core/participation.py)

### 2.2 时间窗口趋势

时间趋势默认开启（可通过 `timeline_enabled=False` 关闭），直接调用 `gca_engine/windows.py` 的 `duration_seconds`、`build_fixed_windows` 与 `build_sliding_windows` 复用窗口划分规则，不修改公共文件 `windows.py` 与 `aggregation.py`：[时间窗口实现](../gca_engine/windows.py)

- **固定 5 分钟窗口（`fixed_5min`）**：按 `[0, 300)`、`[300, 600)`、… 左闭右开切分，每项包含 `start_second`、`end_second`、`group_metrics` 及可选 `student_metrics`；无有效发言的窗口两者均为空字典 `{}`。
- **滑动 5 分钟窗口（`sliding_5min`）**：每 30 秒一个更新点（非整数倍结尾补课堂末尾点），按 `(center - 300, center]` 左开右闭取最近 5 分钟有效发言，每项包含 `center_second`、`group_metrics` 及可选 `student_metrics`；课堂时长不足 30 秒时返回空列表 `[]` 并附警告。

## 3. 状态与缺失处理

| 状态 | 触发条件与输出策略 |
| --- | --- |
| `ok` | 有效发言 ≥ 2 条。正常输出学生级指标、小组汇总、群体分布与时间窗口趋势。单人多条发言也返回 `ok`（与协议第 5.4 节及情感模块一致），但省略 `social_impact`、`normalized_entropy=None` 并输出单人受限警告。 |
| `insufficient` | 仅有 1 条有效发言。仍保留可计算的基础指标（如 `utterance_count`、`participation` 与固定窗口），在 `error` 与 `warnings` 中说明样本不足。 |
| `unavailable` | 输入发言为空列表，或所有发言清洗后均为空文本。`student_metrics={}`、`group_metrics={}`、`timeline=None`，`error` 说明原因。 |

当传入的 `gca_result` 出现状态非 `success`/`single_speaker`、学生名单与有效发言不一致或 `n_utterances` 与输入条数不一致时，模块会记录警告并忽略不匹配的 GCA 结果，改由发言本身计算行为基础指标；若 GCA 字段出现 `NaN`/`Inf` 也会安全跳过，确保输出可通过严格 JSON 序列化（`allow_nan=False`）。

## 4. 测试结果

以下结果来自 2026 年 11 月 20 日在 Python 3.12 环境（`jieba 0.42.1`）下执行的单元测试与质量检查：

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| `pytest tests_safe/gca/test_behavioral.py` | 22 passed, 0 failed | 覆盖输入校验、多人不对称计数/占比/频率/均衡度、完整与部分 `end_time` 降级、真实 GCA 复用与不匹配/NaN 防护、空发言/全空文本/0 秒单条/单人/短课堂边界、与 `windows.py` 窗口边界一致性及三维组合序列化 |
| `pytest tests_safe/gca/` | 325 passed, 0 failed | 含全部既有 GCA 回归测试，无回归 |
| `ruff check .` & `ruff format --check .` | 通过 | 代码风格与格式全部符合仓库规范 |
| `mypy` | 通过（117 source files, 0 issues） | 无新增类型检查错误 |

上述测试使用合成发言数据，验证范围为算法逻辑与协议契约正确性，不代表真实课堂教学效果。

## 5. 局限与待确认事项

1. **口头参与不等于全部行为投入**：当前仅依赖语音转写发言记录，无法观测倾听、笔记、举手、目光或屏幕操作等非言语行为；上游动作数据尚未接入统一协议，后续若引入需先对齐字段。
2. **缺少在线名单时的均衡度口径**：在未提供在线成员名单前，`active_speaker_count` 与 `normalized_entropy` 仅在至少发过 1 次言的成员中计算，全程未发言的在线成员不会被计入分母。
3. **发言时长依赖上游 `end_time`**：真实课堂适配器 `gca_engine/adapters/classroom.py` 目前统一传 `end_time=None`，真实场景下暂不可计算发言时长；待上游补充句级结束时间戳后即可自动生效。
4. **短时课堂频率波动与观察时长估算**：未显式传入 `duration_seconds` 时，观察时长按最后一条有效发言的时间戳估算；若课堂时长较短（如不足 60 秒），每分钟发言频率波动较大，解读时应结合 `utterance_count` 与 `duration_seconds`。
5. **与 `windows.py` / `aggregation.py` 的后续复用方案（回应协议待确认项 1）**：为严格遵守本轮不擅改公共文件的协作约定，本模块通过调用 `windows.py` 复用窗口边界，并在模块内实现同口径的通用数值汇总。待三维模块全部合入后，如组长与组员确认需要抽公共汇总参数，可再以独立小 PR 统一扩展 `aggregation.py` 与 `windows.py`。

## 参考文献

1. Fredricks, J. A., Blumenfeld, P. C., & Paris, A. H. (2004). School Engagement: Potential of the Concept, State of the Evidence. *Review of Educational Research*, 74(1), 59–109. [DOI 10.3102/00346543074001059](https://doi.org/10.3102/00346543074001059)
2. Dowell, N. M. M., Nixon, T. M., & Graesser, A. C. (2019). Group communication analysis: A computational linguistics approach for detecting sociocognitive roles in multiparty interactions. *Behavior Research Methods*, 51(3), 1007–1041. [DOI 10.3758/s13428-018-1102-z](https://doi.org/10.3758/s13428-018-1102-z)
3. Pielou, E. C. (1966). The measurement of diversity in different types of biological collections. *Journal of Theoretical Biology*, 13, 131–144. [DOI 10.1016/0022-5193(66)90013-0](https://doi.org/10.1016/0022-5193(66)90013-0)
