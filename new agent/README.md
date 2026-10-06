# Classroom Group Analysis Agent（课堂小组分析智能体）

给它一个课堂 ID 和一句教师提问，它会自己决定调用哪些工具去取数、算指标、找证据，
最后输出一份**每条结论都带证据编号**的协作诊断报告，以及可以直接下发的干预动作卡。

- 实现形态：单文件 `group_analysis_agent.py`（约 1800 行，含设计说明）
- 模型通道：DeepSeek（复用项目已有的 `openai` 包走 OpenAI 兼容接口）
- 新增依赖：**无**
- 离线自检：19 项，全部通过（`--selftest`）

---

## 一、这个 Agent 的创新与不同之处

### 1. 测量与推理分离：数字不许由模型"估"

常规做法是把课堂数据拼成一个大 Prompt，让大模型直接说出"参与度 0.63"这类数字——无法复现、无法追责。
本 Agent 把两者彻底分开：**六个 GCA 指标全部由确定性算法计算**，函数返回的不只是数值，还有
计算口径（formula）、样本量（sample_size）和置信度（high/medium/low）。大模型只负责选工具、
读数据、下判断。它拿不到数字就写不出数字。

### 2. 证据账本 + 结论自检：把可追溯做成机制

每次工具调用都会往证据账本里登记条目，生成 `E#` 编号，并尽量挂上原始出处（如 `T#1834` 指向某条发言）。
最终报告里每条结论都必须标注证据编号；跑完还有一轮**自检**，把结论逐条拿回证据清单里核对，
没有证据支撑的会被标出来并降级为"推测"。

这不是靠 Prompt 里写一句"请勿编造"实现的，而是结构上的约束：证据表本身就是模型可见的上下文，
自检是独立的一轮模型调用。

### 3. 无标签小组发现：从行为里推断出数据库里没有的结构

项目数据库里**没有小组实体**——`/api/class-groups` 名字像分组，实际是按学生个人的统计；
`MemberConnection` 只是在线上线状态。所以常规做法要么让老师手动预分组，要么按学号硬切。

本 Agent 走第三条路：用发言的相邻接话关系构建交互网络，做**确定性的加权标签传播**切出协作子群，
再按"跨组互动占比"和"连接度"标注三种角色——核心贡献者、跨组桥接人、被孤立者。不需要改表、
不需要老师事先分组，分析的颗粒度直接来自真实讨论行为。

它会回答这类问题：这节课实际形成了两个讨论圈；两个圈之间只有张某在传话；李某全程在线却一次都没有接话。

### 4. 把"跨模态错位"当成协作质量指标

项目积累了别的系统没有的字段：`cross_modal_consistency`（跨模态一致性）、`audio_tone`（语调）、
`body_action`（动作）、`binding_confidence`（声纹绑定置信度）。本 Agent 用它做一件具体的事：
找**"嘴上说懂了、表情是困惑"**的发言点（表情负向但语调正向、表情负向但语言附和、一致性分数过低），
并把错位率折算进协作质量。这让分析从"谁说了多少"上升到"说的和表现的是否一致"。

### 5. 输出的是干预动作卡，不是一段建议

报告里的每条干预都是结构化动作：触发证据、干预对象、动作类型、话术草稿、预期影响、风险提示。
其中"预期影响"不是拍脑袋——它来自**同教师历史课堂的沉默窗口统计**：历史上一个沉默成员在下一个
5 分钟窗口里开口的概率是多少，样本量多少。Agent 会明确写上这是相关性估计而非因果推断。

动作卡可以直接通过 `dispatch_intervention` 下发（点名引导 / 全班话题提示），这是唯一的写操作，
必须人工确认才会真正执行，默认只产出建议。

### 6. 生命周期门禁 + 三档时延预算

Agent 不能脱离课堂状态乱调用工具。数据库只存 active/paused/ended，本 Agent 在此基础上推导统一三态
created → running → ended，并为**每个工具声明允许的状态**：建课阶段只能查上下文，讨论中才开放分析工具，
课后禁止实时干预类工具。

状态不允许时**不抛异常**，而是返回结构化原因加替代工具建议，模型可以自己纠正下一步，不会因为
一次越权调用就整轮崩掉。

同时按场景给出三档预算，同一个 Agent 适配三种用法：

| 模式 | 允许的工具 | 最大轮次 | 自检 | 场景 |
|---|---|---|---|---|
| `realtime` | 5 个测量类 | 4 | 关闭 | 课堂进行中实时提醒 |
| `on_demand` | 8 个（含写操作） | 8 | 开启 | 教师随堂提问 |
| `after_class` | 7 个只读 | 12 | 开启 | 课后深度复盘 |

### 7. 零新依赖，且能平滑升级

没有引入 LangChain、Agents SDK 或任何编排框架，循环本身只有一百多行，用项目已装的 `openai` 包
直接走 function calling。八个工具都是带类型注解的普通 Python 函数，将来要换成 OpenAI Agents SDK，
把 `MiniHarness` 换成 `agents.Runner`、给函数加 `@function_tool` 即可，工具实现不用重写。

### 一句话对比

| 维度 | 常见做法 | 本 Agent |
|---|---|---|
| 指标来源 | 模型读了数据后自己"估" | 确定性算法计算，附口径与样本量 |
| 结论可信度 | 无法回溯 | 每条结论挂 `E#` / `T#` 证据，并有自检轮 |
| 小组划分 | 老师预先分组或按学号切 | 从接话网络自动发现子群与角色 |
| 质量维度 | 发言量、情绪统计 | 增加跨模态一致性（说的 vs 表现的） |
| 输出形态 | 一段文字建议 | 结构化动作卡，可一键下发 |
| 状态安全 | 前端或调用方自己判断 | 工具级状态门禁 + 替代建议 |
| 时延 | 一套逻辑套所有场景 | realtime / on_demand / after_class 三档预算 |

---

## 二、文件构成与在项目中的对应位置

| 本目录 | 对应到项目中的位置 | 说明 |
|---|---|---|
| `group_analysis_agent.py` | 项目根目录 | Agent 本体：8 个 Tool、生命周期 Policy、证据账本、六个 GCA 指标、迷你 Harness、FastAPI 路由、命令行入口 |
| `compat/webrtcvad.py` | 项目根目录 `compat/` | 纯 Python 的 webrtcvad 替代实现，Windows 无 MSVC 时的必要补丁 |
| `scripts/requirements-agent-pinned.txt` | 项目根目录 `scripts/` | Agent 运行所需的最小依赖（精确版本） |
| `scripts/fetch_wheels.ps1` | 项目根目录 `scripts/` | 一键下载上述依赖的 wheel，供离线/弱网环境安装 |
| `README.md`（本文件） | —— | 说明文档 |

---

## 三、怎么跑

Agent 依赖项目里的 `config.py`、`database.py`、`research_algorithm_fusion.py`，
所以要在项目目录下运行，不能独立运行本文件夹。

三项离线检查（不需要数据库、不需要联网）：

```powershell
venv\Scripts\python.exe group_analysis_agent.py --tools      # 8 个工具与策略表
venv\Scripts\python.exe group_analysis_agent.py --selftest   # 19 项纯算法自检
venv\Scripts\python.exe group_analysis_agent.py --check      # 配置 / 数据库 / 算法体检
```

真正跑一次分析（需要数据库与 DeepSeek 出网）：

```powershell
venv\Scripts\python.exe group_analysis_agent.py --meeting-id 12 --mode on_demand `
    --question "分析这个班的讨论，参与是否均衡，我该不该干预"
```

挂到现有服务上（在 `server.py` 增加两行，本 Agent 不改动任何现有文件）：

```python
from group_analysis_agent import router as agent_router
app.include_router(agent_router)
```

挂载后可用两个接口：

- `GET  /api/agents/group-analysis/tools` —— 查看工具、策略与模式预算
- `POST /api/agents/group-analysis` —— 传入 `meeting_id`、`question`、`mode`

每次运行都会在 `storage/agent_traces/` 留下一条 trace，记录每一轮模型调用、工具名、参数、耗时与结果摘要。

---

## 四、依赖

Agent 本身不需要任何新增依赖，它用的 `openai`、`sqlalchemy`、`fastapi` 项目里都已经有。
`scripts/requirements-agent-pinned.txt` 是把整套运行环境固定下来的清单（Python 3.12 + Windows 已验证）。

需要离线安装时：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\fetch_wheels.ps1 -OutDir D:\wheels
python -m pip install --no-index --find-links D:\wheels -r scripts\requirements-agent-pinned.txt
```

三个注意点：

1. `torch` 的 wheel 约 118MB，下载耗时较长，属于声纹模块（resemblyzer）的依赖。
2. `webrtcvad` 在 Windows 上需要 MSVC 编译，装不上是正常的；用 `compat/webrtcvad.py` 顶上即可。
3. 不要安装 `typing==3.7.x` 这个旧 backport，它会遮蔽标准库的 `typing`。

研究增强模块（insightface、pyannote.audio、sentence-transformers、funasr 等）不是本 Agent 运行所需，
按需另装；缺失时 Agent 会自动降级，不影响标准模式的八个工具。
