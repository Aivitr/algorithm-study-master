# 认知投入模块说明

## 1. 教育学背景

认知投入（Cognitive Engagement）是学习者为理解任务、掌握知识和解决问题所投入的思考与努力，也体现在策略选择、理解监控和调整方法等学习活动中。课堂发言提供了其中一部分可见证据，例如回应同伴的论点、补充新的解释，以及延续和组织自己的论述。[Fredricks、Blumenfeld 与 Paris（2004）](https://doi.org/10.3102/00346543074001059)

ICAP 框架把可观察的学习活动分为互动、建构、主动和被动四类，为观察回应、共同建构和生成新解释提供了理论依据。群体沟通分析（Group Communication Analysis，GCA）用发言之间的语义关系描述协作讨论中的互动与贡献特征。本模块据此把同伴回应、新增语义、自身前后发言的语义联系，以及上游给出的发言质量作为**代理指标**，即通过可观察的语言产出间接描述讨论过程。语义相似可能来自复述，语义新颖也可能来自偏题。沉默、阅读和独立推理通常不会体现在转写中。这些指标不能直接等同于认知深度、学习能力或最终学习效果。[Chi 与 Wylie（2014）](https://doi.org/10.1080/00461520.2014.965823) · [Dowell、Nixon 与 Graesser（2019）](https://doi.org/10.3758/s13428-018-1102-z)

## 2. 数据来源与计算

`analyze_cognitive(meeting_id, utterances, quality, gca_result=None)` 接收同一小组的 `Utterance`（课堂发言记录）、`SpeechQualityRecord`（上游发言质量评分记录）及可选的 `GroupAnalysisResult`（已计算的 GCA 结果）。函数通过公共工厂返回 `EngagementDimensionResult`（单个投入维度的结果）。学生键使用字符串形式的 `user_id`，与 `Utterance.speaker_id` 一致。非法输入、重复发言或评分标识、跨小组发言或 GCA 结果会触发 `ValueError`（输入值错误）。[数据结构](../gca_engine/schemas.py) · [公共协议](engagement_protocol.md#4-三个维度模块的函数契约) · [认知模块](../gca_engine/engagement/cognitive.py)

| 指标 | 来源、计算口径与解释 |
| --- | --- |
| `overall_responsivity` | 读取 GCA 学生指标。上游对该学生后续发言与同伴先前发言的语义关联做汇总，取回应矩阵的行均值，排除自身项。单人时省略该字段。语义关联无法单独证明观点得到实质回应。 |
| `newness` | 读取 GCA 学生指标。上游比较每条发言与先前讨论所覆盖的语义空间，按学生取各条发言的新颖性均值。数值受发言顺序和既有讨论内容影响。 |
| `internal_cohesion` | 读取 GCA 学生指标。上游取回应矩阵中该学生对应的对角项，描述同一学生前后发言的语义联系。较高的关联也可能来自重复表达。 |
| `quality_mean` | 对学生匹配到的有效 `quality_score` 取算术平均。没有有效评分时省略该字段，均值只代表纳入统计的评分样本。 |
| `quality_count` | 学生匹配到的有效质量评分条数。 |
| `quality_coverage` | 有效评分条数除以有效发言条数。学生指标使用个人发言作分母，`metadata.quality_coverage` 使用全组发言作分母，全组分母为零时取 `None`。该比例描述评分覆盖情况。 |

评分用字符串 `utterance_id` 与发言匹配，课堂数据中该值对应 `str(Transcript.id)`。评分归属取匹配发言的 `speaker_id`。按课堂适配器的基本清洗规则，清洗后为空的发言从匹配和覆盖率分母中排除。模块仅使用 `quality_score`，并读取 `feedback` 辅助判定。未匹配记录、缺失分数、非有限数和超出 `0–100` 的分数均不纳入统计。[课堂适配器](../gca_engine/adapters/classroom.py) · [转写模型](../app/models/transcript.py) · [评分结构](../gca_engine/engagement/protocols.py)

空反馈和已知状态反馈（“评估中”“已断句，正在评分”“评估超时”，匹配前去除首尾空白及末尾的句点或省略号）会被排除。通用反馈“已评估”搭配 `0` 或 `50` 时也排除，因为无法确认来源。默认未评分零分因此不会自动计入，带具体反馈且满足过滤规则的真实 `0` 或 `50` 可以计入。现有短句规则写入的 `35` 分及其反馈满足纳入条件。缺分不会补值。[实时评分写入](../app/realtime/speech.py) · [流式评分写入](../app/realtime/stream.py)

小组按指标汇总实际有值的学生，输出 `mean/min/max/std/count`（均值、最小值、最大值、总体标准差、参与该项统计的人数）。`group_metrics.quality_mean` 对学生均分等权汇总。`group_metrics.quality_coverage` 汇总各学生覆盖率，其 `mean` 与按全组发言计算的 `metadata.quality_coverage` 可能不同。缺失指标不补零。有可用代理指标或质量分时，有效发言学生可获得实际观测到的零评分条数和零覆盖率。两路均无可用指标时，这些零值只记录在元数据中，学生和小组指标留空。[小组统计口径](../gca_engine/aggregation.py) · [回应指标实现](../gca_engine/core/responsivity.py) · [新颖性实现](../gca_engine/core/newness.py)

## 3. 状态与缺失处理

| 状态 | 当前实现 |
| --- | --- |
| `ok` | GCA 返回 `success`，有至少两名有效发言人，三项代理指标覆盖所有纳入学生，至少有一条有效质量评分，并且未检测到批次不一致。 |
| `insufficient` | 有有效发言或可用代理指标，但数据不足以满足 `ok`。包括单人、GCA 缺失或不完整、评分全不可用、发现名单或发言条数不符，以及只有可用 GCA 指标而没有发言列表。保留可用指标并说明原因。 |
| `unavailable` | 没有有效发言且没有可用认知指标。学生和小组指标为空，`error` 说明原因。 |

状态表示数据可用程度。`insufficient` 和 `unavailable` 不应解读为学习投入低。本模块复用 GCA 结果，无需重跑 GCA 或 LSA（潜在语义分析，用于形成可比较的文本语义表示）。首版 `timeline=None`，未生成认知维度时间趋势或综合分。[协议状态定义](engagement_protocol.md#2-状态码统一方案回应评论-2) · [实现](../gca_engine/engagement/cognitive.py)

## 4. 测试结果

以下数字来自 2026 年 11 月 16 日交付复核时重新运行的认知模块测试和完整 GCA 测试。测试使用项目锁定的 `jieba 0.42.1` 中文分词库。

| 测试范围 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: |
| 认知模块单元测试 | 28 | 0 | 0 |
| 完整 GCA 回归测试 | 295 | 0 | 0 |

完整 GCA 回归测试用于检查原有模块是否受本次变更影响，其中已包含 28 条认知模块测试。用例覆盖正常汇总、缺失及异常评分、非法输入、单人发言、GCA 缺失或不一致、边界状态，以及严格 JSON 序列化（将结果转换成文本并拒绝非有限数）。用例使用合成数据，验证范围为软件行为。[认知模块测试](../tests_safe/gca/test_cognitive.py)

## 5. 局限与待确认事项

1. GCA 指标和质量均分是发言过程的代理指标。本次交付仅验证了软件行为。将这些数值用于评价认知深度、学习能力或学习效果，需要另行开展课堂验证。
2. 上游评分记录缺少可靠的来源标志。保守过滤可能排除有效的真实评分，待确认无法证实来源的 `0`、`50` 的处理口径。
3. 评分覆盖率低时仍可能返回 `ok`。当前依据是所需指标是否可用，覆盖率应与评分结果一并解读。尚无经过验证的覆盖率阈值，低覆盖的状态口径待确认。
4. 模块能发现额外学生或已知发言条数不符。`GroupAnalysisResult` 缺少逐条发言标识，名单和数量相同的批次仍需调用方确保来源一致。
5. 发言列表为空而传入可用 GCA 指标时，当前保留可用指标并返回 `insufficient`。公共协议的无发言示例对应空维度，这一组合的最终状态待组长确认。正常样例和部分缺失样例还分别使用 `quality_coverage` 和 `quality_score_coverage`，本模块使用前者。
6. 当前只提供整段讨论的基础指标和评分统计。首版时间趋势为 `None`，无综合认知投入分。

## 参考文献

1. Fredricks, J. A., Blumenfeld, P. C., & Paris, A. H. (2004). School Engagement: Potential of the Concept, State of the Evidence. *Review of Educational Research*, 74(1), 59–109. [DOI 10.3102/00346543074001059](https://doi.org/10.3102/00346543074001059)
2. Chi, M. T. H., & Wylie, R. (2014). The ICAP Framework: Linking Cognitive Engagement to Active Learning Outcomes. *Educational Psychologist*, 49(4), 219–243. [DOI 10.1080/00461520.2014.965823](https://doi.org/10.1080/00461520.2014.965823)
3. Dowell, N. M. M., Nixon, T. M., & Graesser, A. C. (2019). Group communication analysis: A computational linguistics approach for detecting sociocognitive roles in multiparty interactions. *Behavior Research Methods*, 51(3), 1007–1041. [DOI 10.3758/s13428-018-1102-z](https://doi.org/10.3758/s13428-018-1102-z)
