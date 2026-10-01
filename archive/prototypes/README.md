# 早期原型（已被现方案替代）

本目录收两组**独立示例/旧版脚本**：`legacy-1/` 与 `legacy-3/`。

## 为什么改了名字

原目录名是 `1/`、`3/`（没有 `2/`，但 `server.py` 的导入引导段一直无条件追加它，
是一处无害的空操作——现已登记在 `tests_safe/test_paths_anchor.py` 的断言里）。

编号的含义**无文档记载**。原 `1/README1.md` 只说它们是「独立示例/旧版脚本」，
未说明是否属于某个编号方案。因此归档时**不沿用编号命名**——`legacy-1`、`legacy-3`
明确表达「一段来历不明、已被替代的历史」，而 `1`、`3` 会暗示一种未经证实的顺序。
（归档目录的命名说明。）

---

## `legacy-1/` — 原 `1/`

### 这些文件原本是干什么的

语音识别/说话人分离的**早期实现**，多个独立可运行脚本：

| 文件 | 作用 |
|---|---|
| `aliyun.py` | 离线一次性识别。REST 取 token + HTTP POST 逐段识别 |
| `service_aliyun.py` | 流式识别**子进程服务**（子进程协议：`SYSTEM_READY` / 读路径 / 输出文本） |
| `service_funasr.py` | 同协议的 FunASR 版（走本地 FunASR Docker，非阿里云 NLS） |
| `funasr_recognizer.py` | FunASR 识别器，Docker/本地两种模式 |
| `service_speaker.py` | pyannote 说话人分离子进程服务 |
| `speaker.py` | pyannote 说话人分离辅助函数 |
| `extract.py` | ffmpeg 从视频提取音频 |
| `video.py` | 读 `_complete_analysis.json` 生成最终视频 |
| `test.py` | 环境检查（torch / pyannote / whisper / moviepy） |

### 为什么在这里

**已被现方案整体替代。** `1/README1.md`（随目录保留，是这里最准确的一份说明）
记录得很清楚：

> 1 是独立示例/旧版脚本，未被 server.py 接线，只把该目录加入了 `sys.path`
> （server.py:22），并未 import 或 subprocess 启动其中任何脚本。
>
> 实时 ASR 走的是阿里云 NLS `ai_core.RealtimeTranscriber` + `server.ASRSessionManager`
> + `/ws-asr` + 前端 这条完整链路；`1/` 目录的 `service_aliyun.py` 等是未被引用的
> 旧版/示例。

`docs/route-inventory.md` 与阶段 0 的实测均确认这一点：**没有任何运行期模块从
`1/` 导入**。它的存在只剩历史意义。

### 已知的引用关系与注意事项

- `server.py` 的导入引导段仍会把 `legacy-1/` 的**原路径**（`<root>/1`）追加进
  `sys.path`。归档后该路径不存在，`os.path.isdir` 判断会跳过——这是既有行为，
  不报错。`tests_safe/test_paths_anchor.py::test_server_syspath_additions_are_known_and_present`
  会在有人忘记同步时失败。
- `legacy-3/c_realtime_integration.py` 按 `ROOT_DIR/'1'` 引用本目录。归档后
  这个相对关系不再成立（见下）。
- 各脚本内**硬编码了密钥**（如 `aliyun.py` 的 `main()`、`service_speaker.py` 的
  `HF_TOKEN`）。这些是历史明文凭据，**可能已失效，但不要提交任何真实密钥的更新**；
  若要复用其中代码，先替换为环境变量读取。

---

## `legacy-3/` — 原 `3/`

### 这些文件原本是干什么的

单个脚本 `c_realtime_integration.py`：把 `legacy-1/` 里的三个子进程服务
（说话人分离 / 阿里云 ASR / FunASR）串成的**实时集成编排**，按固定时长切片
（`CHUNK_DURATION = 8.0`、`STEP_SIZE = 6.0`）驱动它们跑完整链路。

### 为什么在这里

同一套被替代方案的编排层。它依赖 `legacy-1/` 的三个服务脚本与一个
`domo.mp4` 视频文件。

### 已知的引用关系与注意事项

- **归档后不再可直接运行**：脚本按 `ROOT_DIR = dirname(dirname(__file__))`
  反推仓库根，再从那里找 `1/` 与 `domo.mp4`。移入
  `archive/prototypes/legacy-3/` 后，`ROOT_DIR` 变成了 `archive/prototypes/`，
  三个服务脚本与视频都找不到了。
- `domo.mp4` **在本仓库中从来不存在**（未被 git 跟踪，也不在 `.gitignore` 的
  说明里）。也就是说该脚本在归档**之前**就已无法端到端运行——归档只是让这一点
  更明显。
- 源码含大量 `[EMOJI]` 占位（如 `CHUNK_DURATION = 8.0  # [EMOJI]`），
  语义已不可读。这是注释污染，**归档不修复它**——
  修复会改动原文，而原文本身就是需要保留的证据。

---

## 查阅指引

- 想了解这套旧方案的设计意图 → 先读 `legacy-1/README1.md`
- 想了解现行 ASR 链路 → 读 `app/realtime/`（阶段 3 迁出）与 `ai_core.py`
- 想看这套方案走到哪一步停止 → `../speech-stages/README.md`
