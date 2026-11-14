# 第二阶段公共协议：三维学习投入 + Hint 触发候选

> 组长（陈虹宇）2026-11-14 提交，基于 feat/gca 分支实际代码核对。
> 代码实现：`gca_engine/engagement/protocols.py`（数据结构）、
> `gca_engine/engagement/triggers.py`（Hint 规则）。
> 对应测试：`tests_safe/gca/test_engagement_protocols.py`、
> `tests_safe/gca/test_hint_triggers.py`。
> 本文档回应任务文档评论 1（统一成什么）、评论 2（状态定义）、
> 评论 3（Hint 规则与输出字段）。

## 1. 统一口径

- 学生身份：`user_id` 转成的字符串（与现有 `speaker_id` 同一口径）。
- 时间：课堂开始后的相对秒数（float），与 `Utterance.timestamp` 同一零点。
- 输入复用 `Utterance`；情绪与质量评分分别用 `EmotionRecord`、
  `SpeechQualityRecord` 补充。
- 窗口：沿用现有固定/滑动 5 分钟窗口（`gca_engine/config.py`
  FIXED_WINDOW_SECONDS=300 / SLIDING_STEP_SECONDS=30），不新建窗口规则。
- 小组汇总口径与 `gca_engine/aggregation.py` 一致：
  `{指标名: {mean, min, max, std, count}}`，无数据时 `{}`。

## 2. 状态码统一方案（回应评论 2）

现有 `AnalysisStatus` 7 种（success / empty_transcript / single_speaker /
insufficient_data / invalid_input / not_found / internal_error）**保持原样不动**，
它是"整体分析状态"，Agent 组已按它对接。

任务文档里的 `ok / insufficient / unavailable` 是**另一个层面**——"某一个维度的数据
够不够"，落到新协议 `DIMENSION_STATUS` 三值：

| 取值 | 含义 | 该维度允许输出 |
|---|---|---|
| `ok` | 有足够有效数据，指标可以计算 | student_metrics / group_metrics / timeline |
| `insufficient` | 有数据但太少/太稀疏（如整节课只有 1 条情绪记录） | 只输出可算指标，不输出综合分 |
| `unavailable` | 完全没有该维度数据（如课堂未开情绪识别） | 全部为空，error 说明原因 |

两者互不替代：`EngagementResult.status` 用 AnalysisStatus 7 种；
`EngagementDimensionResult.status` 用 DIMENSION_STATUS 三值。

## 3. 数据结构（详细定义见代码 docstring）

- `EmotionRecord`：情绪输入（meeting_id / user_id / emotion_type / timestamp /
  intensity? / source? / record_id?），对应上游 EmotionLog。
  注意：上游 `app/models/emotion.py` EmotionLog 没有课堂相对秒数字段
  （created_at 是墙钟、video_start_time 是视频内秒数），适配层需按
  `meeting.started_at` 换算（同 `app/services/gca_service.py:49` 的做法）。
- `SpeechQualityRecord`：质量评分输入（utterance_id / quality_score? /
  relevance_score? / feedback?），对应上游 Transcript 的 LLM 打分结果。
  注意：上游 `quality_score` 是 Integer、默认 0 表示未打分，缺失率判定
  应由适配层依据 `quality_feedback` 是否有值。
- `EngagementDimensionResult`：单维度输出（dimension / status /
  student_metrics / group_metrics / timeline / metadata / warnings / error）。
  三个维度模块统一返回它。
- `EngagementResult`：整合输出（meeting_id / status / dimensions 三键齐全 /
  student_metrics / group_metrics / timeline / metadata / warnings / error）。
  缺任一维度键即校验失败。
- `HintCandidate`：GCA → Agent 的 Hint 候选（见第 6 节字段表）。

## 4. 三个维度模块的函数契约

三位组员在各自分支实现，函数签名统一（参数可扩展，返回结构必须一致）：

```python
# gca_engine/engagement/emotional.py（岳柔）
def analyze_emotional(records: list[EmotionRecord],
                      meeting_id: str) -> EngagementDimensionResult: ...

# gca_engine/engagement/behavioral.py（雷梦琪）
def analyze_behavioral(meeting_id: str,
                       utterances: list[Utterance],
                       gca_result: GroupAnalysisResult | None = None) -> EngagementDimensionResult: ...

# gca_engine/engagement/cognitive.py（葛艾蓝）
def analyze_cognitive(meeting_id: str,
                      utterances: list[Utterance],
                      quality: list[SpeechQualityRecord],
                      gca_result: GroupAnalysisResult | None = None) -> EngagementDimensionResult: ...
```

约定：

- 输入不合法抛 `ValueError`（与现有 `register_meeting` 一致）；数据不足/不可用
  **不抛异常**，返回对应 `insufficient` / `unavailable` 结果（用 `dimension_result()` 工厂构建）。
- `student_metrics` / `group_metrics` 无数据时给 `{}`（不是 None）；`timeline` 不可用时给 `None`。
- 小组统计口径与 `aggregation.py` 一致（mean/min/max/std/count）。
- 时间趋势如需计算，窗口边界直接复用 `windows.py`（`build_fixed_windows` /
  `build_sliding_windows`）；注意 `windows.py` 的 `group_metric_stats` 目前只汇总
  SIX_METRICS 六个名字，自定义指标名会被丢弃——三维模块要么把指标值挂到六个名字下，
  要么自己按同口径汇总，**先与雷梦琪确认是否扩展 windows.py 支持自定义指标名**（待确认项 1）。
- 维度 `timeline` 的输出形状沿用引擎 timeline 约定（`gca_engine/schemas.py`
  `GroupAnalysisResult` 的 docstring）：
  `{"fixed_5min": [{"start_second", "end_second", "group_metrics": {...}}], "sliding_5min": [{"center_second", "group_metrics": {...}}]}`，
  无数据的窗口 `group_metrics` 为 `{}`；本轮不计算时间趋势时给 `None`。
- 行为维度注意：当前课堂适配器 `gca_engine/adapters/classroom.py` 一律传
  `end_time=None`，真实数据的"发言时长"暂不可用，本轮只统计次数/频率。
- 整合入口由组长实现：`analyze_engagement(meeting_id, ...) -> EngagementResult`，
  其中 `student_metrics` / `group_metrics` 是三个维度结果的投影，不重复计算。
  等三个维度模块合入后编写。

## 5. JSON 样例

以下样例全部由当前代码实际生成（`json.dumps(result.to_dict())`），
序列化与校验测试见 `tests_safe/gca/test_engagement_protocols.py::TestSampleScenarios`。

### 5.1 正常三维结果（截取关键结构，完整示例见测试）

```json
{
  "meeting_id": "m1",
  "status": "success",
  "dimensions": {
    "emotional": {
      "dimension": "emotional", "status": "ok",
      "student_metrics": {"u001": {"positive_ratio": 0.6}, "u002": {"positive_ratio": 0.4}},
      "group_metrics": {"positive_ratio": {"mean": 0.5, "min": 0.4, "max": 0.6, "std": 0.1, "count": 2}},
      "timeline": null,
      "metadata": {"coverage": 0.9, "n_records": 40},
      "warnings": [], "error": null
    },
    "behavioral": {
      "dimension": "behavioral", "status": "ok",
      "student_metrics": {"u001": {"utterance_count": 8.0, "participation": 0.7}},
      "group_metrics": {"utterance_count": {"mean": 6.5, "min": 5.0, "max": 8.0, "std": 1.5, "count": 2}},
      "timeline": null, "metadata": {"n_utterances": 13}, "warnings": [], "error": null
    },
    "cognitive": {
      "dimension": "cognitive", "status": "ok",
      "student_metrics": {"u001": {"overall_responsivity": 0.6, "quality_mean": 82.0}},
      "group_metrics": {"quality_mean": {"mean": 78.5, "min": 75.0, "max": 82.0, "std": 3.5, "count": 2}},
      "timeline": null, "metadata": {"quality_coverage": 0.8}, "warnings": [], "error": null
    }
  },
  "student_metrics": {"u001": {"emotional": {"positive_ratio": 0.6},
                              "behavioral": {"utterance_count": 8.0, "participation": 0.7},
                              "cognitive": {"overall_responsivity": 0.6, "quality_mean": 82.0}}},
  "group_metrics": {"emotional": {"positive_ratio": {"mean": 0.5, "count": 2}}, "...": "同上结构"},
  "timeline": null,
  "metadata": {"dimension_status": {"emotional": "ok", "behavioral": "ok", "cognitive": "ok"}},
  "warnings": [], "error": null
}
```

### 5.2 某个维度数据缺失（情绪未开启）

```json
{
  "dimensions": {
    "emotional": {
      "dimension": "emotional", "status": "unavailable",
      "student_metrics": {}, "group_metrics": {}, "timeline": null,
      "metadata": {}, "warnings": [],
      "error": "课堂未开启情绪识别"
    },
    "behavioral": { "...": "status=ok，正常输出" },
    "cognitive": { "...": "status=ok，正常输出" }
  },
  "status": "success",
  "group_metrics": { "behavioral": {...}, "cognitive": {...} }
}
```

规则：整合层 `status` 仍为 `success`（其余维度可用）；`group_metrics` 不出现
`emotional` 键；`dimensions["emotional"].status` 为 `unavailable`。

### 5.3 无发言记录

```json
{
  "meeting_id": "m1",
  "status": "insufficient_data",
  "dimensions": {
    "emotional": {"dimension": "emotional", "status": "unavailable",
                  "student_metrics": {}, "group_metrics": {}, "timeline": null,
                  "metadata": {}, "warnings": [], "error": "没有任何发言记录"},
    "behavioral": { "...": "同上" },
    "cognitive": { "...": "同上" }
  },
  "student_metrics": {}, "group_metrics": {}, "timeline": null,
  "metadata": {}, "warnings": [], "error": "没有任何发言记录"
}
```

### 5.4 单人发言

```json
{
  "status": "single_speaker",
  "dimensions": {
    "emotional": {"status": "ok", "...": "正常输出"},
    "behavioral": {"status": "ok", "...": "正常输出"},
    "cognitive": {"dimension": "cognitive", "status": "insufficient",
                  "student_metrics": {}, "group_metrics": {}, "timeline": null,
                  "metadata": {"n_speakers": 1}, "warnings": [],
                  "error": "只有一名发言人，回应类指标无比较对象"}
  },
  "warnings": ["只有一名学生发言：回应类指标受限"]
}
```

### 5.5 部分指标可用但不计算综合分

```json
{
  "status": "success",
  "dimensions": {
    "emotional": {"dimension": "emotional", "status": "insufficient",
                  "student_metrics": {"u001": {"positive_ratio": 0.5}},
                  "group_metrics": {"positive_ratio": {"mean": 0.5, "min": 0.5, "max": 0.5, "std": 0.0, "count": 1}},
                  "timeline": null, "metadata": {"coverage": 0.2}, "warnings": [],
                  "error": "情绪记录覆盖不足，未计算综合分"},
    "behavioral": {"status": "ok", "...": "正常输出"},
    "cognitive": {"dimension": "cognitive", "status": "insufficient",
                  "student_metrics": {}, "group_metrics": {}, "timeline": null,
                  "metadata": {"quality_score_coverage": 0.3}, "warnings": [],
                  "error": "质量评分缺失较多，未计算综合分"}
  }
}
```

本轮**不输出** E_e / E_b / E_c 综合分；部分指标照常输出并在 error/warnings 说明局限。

## 6. Hint 触发规则（回应评论 3）

实现：`gca_engine/engagement/triggers.py`，纯 Python，不调 LLM。
两类候选都**只在数据足够时产出**，条件不满足/数据不足时返回空列表。

### 6.1 低参与（学生级，hint_type=`low_participation`）

| 项 | 约定 |
|---|---|
| 适用对象 | 未提供在线名单：已知发言人（至少发过 1 次言的学生）；提供时：在线名单内成员（含从未发过言的成员，与上游 `get_quiet_members` 口径一致） |
| 在线名单（可选） | `online_members: list[str] \| None`，user_id 转字符串（与 `speaker_id` 同一口径）。`None`（默认）→ 判断池为已知发言人，**从未发过言的学生不会被判低参与**；空列表 → 无人在线，不触发。名单需由 Agent 侧传入（GCA 只能看到发言数据） |
| 数据输入 | 统一 `Utterance` 列表 |
| 时间窗口 | 滑动 5 分钟 `(now-300, now]`，30 秒一个评估点（与 `windows.py` 同口径） |
| 触发条件 | 连续 2 个评估点都满足下面任一条件：<br>① 窗口内 0 次发言，且判断池内其他成员都有发言（依据：上游 `get_quiet_members` 条件 1，connection.py:107-109）<br>② 发言次数 < 其他成员平均 × 0.3，且平均 ≥ 3（依据：上游 `get_quiet_members` 条件 2，connection.py:110-112） |
| 数据不足 | 整节课发言 < 2 条、判断池成员 < 2 人、窗口内发言 < 2 条 → 不触发 |
| 去重/冷却 | 候选级冷却 120 秒/人（`dedupe_key` = `low_participation:{meeting_id}:student:{user_id}`） |
| 证据 | `evidence` = 规则名（zero_speech/low_ratio）、自己发言数、其他人平均、已发言人数、连续点数（low_ratio 规则另附 `ratio_threshold`） |

### 6.2 讨论停滞（小组级，hint_type=`discussion_stall`）

| 项 | 约定 |
|---|---|
| 适用对象 | 全组 |
| 数据输入 | 统一 `Utterance` 列表 |
| 触发条件 | 距最后一条发言（max(end_time, timestamp)）≥ 120 秒（依据：上游 `is_group_silent(silence_seconds=120)`，connection.py:115） |
| 数据不足 | 整节课发言 < 2 条 → 不触发 |
| 去重/冷却 | 候选级冷却 300 秒/组（`dedupe_key` = `discussion_stall:{meeting_id}:group:all`） |
| 证据 | `evidence` = 最后发言时间、沉默秒数、阈值 |

### 6.3 阈值依据标注（不虚构）

- 120 秒沉默、0.3 比例、"平均 ≥ 3"：**已有代码依据**（feat/gca 现有实现）。
- 连续 2 个评估点、学生冷却 120 秒、小组冷却 300 秒：**候选配置，无实验依据**
  （前端已有 120s/180s 展示节流先例：static/js/app.js 第 129/133 行，
  轮询周期 30s/60s 见第 3662-3685 行），待课堂观察/A/B 验证后调整。
- 5 分钟窗口 / 30 秒步长：与现有 `gca_engine/config.py` 默认一致。
- 在线名单口径：与上游 `get_quiet_members` 一致（connection.py:91 按
  `get_online_members` 取 WS 连接表成员）。
- 上游 `get_quiet_members` docstring 提到的条件 3（绝对阈值兜底）在代码中
  **未实现**，本模块不采用。

### 6.4 教育口径（写入理由，避免误读）

- 低发言 ≠ 低学习投入：可能是在听讲、思考或看材料。因此触发条件要求
  "对比其他成员明显偏低"且"连续两个评估点"，并只产出**候选**，由教师最终把关。
- 无新发言 ≠ 讨论无效：可能正在阅读或独立解题。停滞候选只是给教师/Agent
  提供干预时机，不代表讨论失败。

## 7. HintCandidate 字段（GCA → Agent 输出）

| 字段 | 类型 | 含义 |
|---|---|---|
| meeting_id | str | 小组 ID |
| hint_type | str | `low_participation` / `discussion_stall`（本轮只有两类） |
| target_type | str | `student` / `group` |
| target_user_id | str \| None | 学生级必填；小组级为 None |
| window | dict | `{start_second, end_second}` 最近滑动窗口（左开右闭） |
| trigger_reason | str | 人读触发原因（中文） |
| evidence | dict | 可解释证据（计数、均值、阈值、连续点数） |
| data_status | str | 恒为 `ok`（数据不足时不产出候选；字段为契约稳定保留） |
| generated_at | float | 课堂相对秒数（评估时刻） |
| dedupe_key | str | 去重键，Agent 侧发送级冷却可继续使用 |

样例（代码实际输出）：

```json
{
  "meeting_id": "m1",
  "hint_type": "low_participation",
  "target_type": "student",
  "target_user_id": "A",
  "window": {"start_second": 360.0, "end_second": 660.0},
  "trigger_reason": "最近窗口内 A 0 次发言，其余 2 名成员均有发言",
  "evidence": {"rule": "zero_speech", "self_utterances": 0,
               "peer_utterances_mean": 2.0, "peers_spoken": 2,
               "peers_total": 2, "consecutive_points": 2},
  "data_status": "ok",
  "generated_at": 660.0,
  "dedupe_key": "low_participation:m1:student:A"
}
```

`hint_id` / `priority` / `status` 等字段本轮**不新增**：候选阶段不需要 ID
（Agent 落库时生成），优先级由 Agent 按类型/时间排序即可，避免冗余字段。

## 8. GCA 与 Agent 的接口契约（与 Agent 组长确认用）

GCA 组交付两个 Python 入口（HTTP 路由由系统/Agent 侧负责）：

```python
from gca_engine.engagement import compute_hint_candidates, HintTriggerState

# 整合层每 30 秒调用一次（课堂相对秒数由整合层换算）
state = HintTriggerState()
candidates = compute_hint_candidates(
    meeting_id, utterances, now_second=t, state=state,
    online_members=online_members,   # list[str] | None，见第 6.1 节
)
# -> list[HintCandidate]，Agent 组拿 evidence/trigger_reason 组装 Prompt
```

Agent 组拿到候选后负责：LLM 生成提示文本 → 教师确认（可选）→ WebSocket 发送 →
记录（AIInsight/HintLog）→ 发送级冷却（可复用 `dedupe_key`）。
GCA 组**不**调用任何 LLM，**不**直接发送任何提示。

上游旧触发逻辑（feat/gca 实际代码，与本协议功能重叠但分层不同）：

| 旧实现 | 位置 | 与新协议差异 |
|---|---|---|
| `/api/check-silence` | app/routers/realtime.py:348 | 判断(120s)+LLM+广播同一端点；`silence_notified` 一次性去重；无教师确认/记录反馈 |
| `/api/check-quiet-members` | app/routers/realtime.py:393 | 判断+LLM+定向发送同一端点；按**在线成员**（WS 连接表）比较；无记录反馈 |
| 前端轮询 | static/js/app.js:3660-3685 | 每 30s 调 check-silence、每 60s 调 check-quiet-members（仅 running 状态） |
| 前端节流 | static/js/app.js:129/133 | classroomHintCooldownMs=120000 / topicSuggestionCooldownMs=180000 |

## 9. 待与 Agent 组长确认的问题

1. `windows.py` 的小组汇总目前只认 SIX_METRICS 六个指标名，三维模块的自定义
   指标（如 `utterance_count`）需要扩展汇总支持或自行按同口径汇总——先与
   雷梦琪确认方案，再与 Agent 组约定 timeline 内指标名的读取方式。
2. 上游已有 `/api/check-silence`、`/api/check-quiet-members` 两套旧触发逻辑
   （在 Agent 侧、直接调 LLM 发提示），与本协议的两类候选功能重叠。需要双方
   确定：旧接口下线/保留并行/改为调用本协议候选，避免两套 Hint 同时触发。
3. 在线名单：GCA 侧输入格式已定义（`online_members: list[str] | None`，
   user_id 转字符串，与 speaker_id 同一口径；未提供时只判断已知发言人，
   从未发过言的学生不会被判低参与）。仍需确认：本轮 Agent 是否按此格式
   传入在线名单（取数来源 `get_online_members`，connection.py:60，WS 连接表）。
4. 候选的评估周期（建议 30 秒，与滑动窗口步长一致）由哪一侧的定时器驱动。
