# 本地开发容器化

> **这份文档只管"本地开发"。线上部署的镜像与指令**尚未编写**——见文末代办。**
> `deploy/README.md` 里那套 systemd + nginx 的流程仍然有效，没被这份取代。
>
> 线上侧唯一需要现在就补的一步是**建库**：拿同一份 `db/schema.sql` 跑一次，
> 命令见 `deploy/README.md`。本机与线上共用一个脚本，这是刻意的。

---

## 它解决什么

消除「重建 venv 结果不同」。本仓库对环境的依赖相当刁钻，手工复现一遍要踩这些坑：

- Python 必须是 **3.12**（本机默认的 3.14 装不上依赖）
- `setuptools` 必须 `<81`，否则 `webrtcvad` 顶层那句 `import pkg_resources` 直接失败
- `insightface` / `webrtcvad` 在 Linux 上没有预编译轮子，要现场编译
- `opencv-python` 导入期要 dlopen `libGL.so.1`

容器把这些一次性钉死在 `Dockerfile` 里，换台机器 `docker compose up --build` 即可。

## 一条命令

**先备好两份 `.env`**（两份都必须，见下节），然后：

```bash
cp .env.example .env              # 填入密钥；LLM_API_KEY 不能为空
cp .env.dev.example .env.dev      # 开发库指向，照抄即可，不用改
docker compose up --build
```

打开 <http://localhost:8000>。

`up` 会按顺序拉起**三个**服务：

```
db       mcr.microsoft.com/mssql/server:2022-latest   建库用，数据落命名卷 mssql-data
db-init  同一个镜像，一次性跑 db/schema.sql，跑完退出（退出码 0 才算成功）
app      自仓库 Dockerfile 构建；镜像里**不含**任何数据库，只负责连过去
```

`db` 与 `db-init` 用的是 registry 镜像，**不打包进 app 镜像**——所以
`docker compose pull db db-init` 可以把数据库单独拉下来，不必重开 app。

`app` 的 `depends_on` 写的是 `service_completed_successfully`：**等 `db-init` 成功退出再起**。
不这么写，app 会连上一个还没建表的空库，"能连上"却是坏的，然后在第一次注册时抛出
一个和真实原因毫无关系的错。

首次构建要装一整套 ML 依赖（torch / insightface / pyannote / funasr），**很慢，且镜像很大**；
`db` 镜像本身另有 2.31 GB。之后只要 `requirements.txt` 没变，改代码不会触发重装——
依赖分了三层缓存，见 `Dockerfile` 的注释。

```bash
docker compose up -d            # 后台跑
docker compose logs -f app      # 看日志
docker compose down             # 停掉（不会删数据卷）
docker compose run --rm app python -m pytest     # 在容器里跑测试套件
docker compose run --rm app bash                 # 进容器看看
```

---

## 增强版：GPU 直通是一个**叠加文件**

`docker-compose.yml` 里**故意没有**设备预留。`deploy.resources.reservations.devices`
在 compose 里是硬要求：宿主没有能看见 GPU 的容器运行时（Linux 的
nvidia-container-toolkit / Windows 的 WSL2 后端）时，compose 会在起 `app`
**之前**就报 `could not select device driver "" with capabilities: [[gpu]]`。
写进主文件等于要求每个跑标准版的人都有 NVIDIA 显卡——而标准版的前提是
"宿主只需 Docker"，这正是它敢说自己"一条命令"的依据。

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

`docker-compose.gpu.yml` 只叠加两样：`app` 的设备预留，和把 `TORCH_INDEX_URL`
这个构建参数接出来。后者不是顺手加的，因为**光直通设备不够**：

`Dockerfile` 里 `TORCH_INDEX_URL` 默认指向 `download.pytorch.org/whl/cpu`
（CPU 版轮子小得多，这是把镜像压到可接受体积的关键）。CPU 版 torch 的
`torch.cuda.is_available()` **永远是 False**——设备已经交到容器里了，轮子用不了它。
要用上 GPU，把索引一起换掉：

```bash
TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124 \
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

`cu118` / `cu121` / `cu124` 对应不同 CUDA 版本，按宿主驱动能支持的挑；代价是镜像
大出好几 GB。叠加文件里那个 ARG 的**默认值就是 CPU 索引**，所以不设这个环境变量时，
加不加该文件在构建上没有任何区别——它不会偷偷改变标准版。

宿主侧两个前提：`nvidia-smi` 能打出版卡信息；容器运行时装好了 GPU 支持。
容器里是否真的看得见 GPU：

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec app \
  python -c "import torch; print(torch.cuda.is_available())"
```

守卫在 `tests_safe/test_docker_assets.py::TestGpuOverrideStaysAnOverride`，
五条断言里最要紧的一条是**主文件里不许出现设备预留**——那一条红了，标准版就废了。

---

## 起容器之前：两份 `.env` 都必须备好

**`.env.dev` 必填**——它管数据库指向（见下一节）。compose 里写成 `required: true`，
少一份就当场报错，不会静默跑到别的库上去。模板在 `.env.dev.example`，照抄即可。

**`.env` 里的 `LLM_API_KEY` 必填**——这一条是构建时**实测撞出来**的，不是推测：

```
app/services/llm_service.py:1088   llm = LLMService()      ← 模块级构造
app/services/llm_service.py:64       self.client = OpenAI(api_key=API_KEY, ...)
→ openai.OpenAIError: Missing credentials.
```

`LLM_API_KEY` 为空时，**`import server` 就失败**，容器连启动都到不了。
这是本仓库既有的行为（在本机跑也一样），不是容器引入的。

配套地，镜像构建期那一步冒烟测试也必须喂一个**假** key，否则构建就红——
Dockerfile 里写的是 `LLM_API_KEY=build-smoke-not-a-real-key`。那一步只 import、
不发请求，所以假值是安全的。

如果你只想让容器起来看看页面、不碰任何 AI 功能，给个假值也行：

```bash
LLM_API_KEY=dummy-not-a-real-key docker compose up
```

---

## 数据库配置按环境分层

这一节请务必读完再改 `docker-compose.yml`。

**背景**：`app/core/database.py` 的 `_ensure_transcripts_columns()` 在**导入期**执行，
也就是 **`import` 即 DDL**。所以「容器起来时连的是哪个库」不是一个抽象的配置问题——
它直接决定了容器启动时会不会对那个库发 `ALTER TABLE transcripts ADD ...`。

在此之前，本仓库只有一个 `.env`，而它指向**生产 RDS**。于是当时的做法是：
compose 的 `environment:` 段**硬写** 6 个数据库键，靠
`config.py::_apply_env_file` 的 `os.environ.setdefault` 语义
（**进程里已有的环境变量赢过 `.env` 文件**）把生产值挡在外面。
那是一次真正的修补，不是多余的设计。

**现在换成按环境分层**——因为"挡"只在开发机上成立，而线上那台机器要连的正是真实库：

| 文件 | 放什么 | 入库 |
|---|---|---|
| `.env` | 共享密钥（LLM / OSS / Agora / 阿里云） | 否 |
| `.env.dev` | 开发库指向 → compose 里的 `db` 服务 | 否（模板 `.env.dev.example` 入库） |
| `.env.prod` | 远程库指向 → 生产 RDS | 否（模板 `.env.prod.example` 入库） |

`APP_ENV` 选哪一层（`dev` / `prod`），`app/core/config.py::_load_dotenv` 本来就支持；
compose 里给 `app` 钉了 `APP_ENV=dev`。**这不是改业务代码**，只是把文件摆到位。

这么一换，安全性反而**更强**：开发工作区里**根本不存在**生产库连接信息——
不是"挡住了"，是"压根没有"。原先那 6 行硬写的 safety valve 随之删掉。

### 新守卫：问的问题变了

`TestComposeNeutralizesProductionDatabase` 已作废，换成
`TestComposePointsAtTheLocalDatabase` + `TestDevEnvLayer` + `TestNoProductionCredentialsAreTracked`。
断言不再问"挡住没有"，而问：

- `db` 是 registry 镜像（无 `build:`）且数据挂**命名卷**——bind mount 在 Windows 上
  会因不表达 POSIX 权限而起不来
- `db/schema.sql` 真的幂等——这是"每次 `up` 都会重跑它"的前提
- `app` 等 `db-init` **成功退出**；app 的库配置只来自 `.env.dev`，且 `required: true`
- **反向断言**：除 `app` 外，任何 service 都不得在 `environment:` 里定义那 6 个键
  （防的是"断言写在 A 上、改动发生在 B"那类失效）
- 入库文件里不含生产主机名 / 用户名 / 口令（实测抓到过一次）

### `db` / `db-init` 刻意**不碰** `DB_*` 命名空间

它们用 `MSSQL_HOST` / `MSSQL_DB` / `MSSQL_SA_PASSWORD`。理由是：运维侧的一次性容器
不该去读 app 的库配置——否则 `.env` 里那份 `DB_*` 有朝一日被挂上来，**建库就建到生产去了**。

### 想改指向，改 `.env.dev` 就行

不用再写叠加文件。`.env.dev` 就是那个开关，而且它**不在版本库里**，
于是"容器会连生产库"永远不会变成一个随手可及的仓库内开关。

把它里面的 `DB_HOST` / `DB_PORT` / `DATABASE_URL` 指过去即可，但**三个必须一起改**：
ORM 走 `DATABASE_URL`，而 `/api/register`、`/api/login` **不走 ORM**，直接读 `DB_*`。
只改一个的症状是"注册写 A 库、登录读 B 库"。

> ⚠️ 若指向真实库，容器**会对它发 DDL**（导入期的 `_ensure_transcripts_columns`）。
> 动手前确认你确实要这个。
>
> ⚠️ `docker-compose.yml` 里的 `${...}` 插值读的是**仓库根的 `.env`**，
> 而不是 `.env.dev`。所以那里**绝不插值** `DB_*` / `DATABASE_URL` ——
> 否则远程库的口令会被拉进 compose，`docker compose config` 一跑就摊在屏幕上。

### `.env` 不会进镜像

`Dockerfile` 最后一步是 `COPY . .`，因此 `.dockerignore` 里第一条就是
`.env` + `.env.*`（放行 `!.env.example` 与 `!.env.*.example`）。
镜像层只增不减，**一旦把生产口令打进层里，事后改 `.dockerignore` 也抹不掉**。
这道防线同样由 `tests_safe/test_docker_assets.py` 断言。

容器运行期之所以还能看到 `.env` / `.env.dev`，是因为仓库目录**挂载**了进去
（`.:/app`）——挂载发生在运行期，与镜像层无关。换句话说：**镜像里没有凭据，
容器里才有**，这两件事不矛盾。

---

## 容器里的配置来自哪

`.env` 与 `.env.dev` **都会**跟着仓库目录挂进容器（`/app/.env`、`/app/.env.dev`）。
`environment:` 段现在只剩三项：`APP_ENV=dev`、`PYTHONIOENCODING=utf-8`、
`WATCHFILES_FORCE_POLLING=true`——数据库那 6 个键已经交给 `.env.dev` 了。

一个副作用（与在本机直接跑 `uvicorn` 时**完全一样**）：
调 `/api/research-runtime` 的配置接口会就地改写**活动 env 文件**里的 `RESEARCH_*` 三行。
容器里 `APP_ENV=dev`，所以活动文件是 `.env.dev`；宿主上直接跑时默认也是 `dev`。
两侧都落在宿主的 `.env.dev` 上，不会去动 `.env`。

> 这正是 `.env.dev` 必须进 `.gitignore` 的原因之一：**它会被程序写入**。

---

## 在容器里跑测试：预计会有 **1 条**基线失败，且已查明原因

```bash
docker compose run --rm --no-deps app python -m pytest -q
# → 1 failed, 343 passed, 9 skipped
```

失败的是 `test_route_baseline`，只涉及 59 条路由里的 **2 条**。
（另比宿主多 7 个 skip：那是容器里没有 `node` 导致的前端渲染探针跳过，见 `tests_safe/`。）
两条都**不是**容器化引入的回归——代码是同一份（宿主目录挂进去的），
差异全部来自"Windows 宿主 vs Linux"这个平台事实。**线上那台 Linux 服务器
也会有同样的两条差异**，只是那里不跑这个测试。

### 1. `GET /api/research-runtime` —— 响应里带**绝对路径**

该接口返回 `model_root` / `gallery_root` / `cache_root` / `env_file` 四个字段，
值由 `app.core.paths.PROJECT_ROOT` 拼出：

| | `PROJECT_ROOT` | 字符数 |
|---|---|---|
| 宿主 | `D:\algorithm-study-master` | 25 |
| 容器 | `/app` | 4 |

路径在响应里出现多次，累计差 665 字节（基线 14392 → 容器 13727）。

### 2. `GET /api/download-exercises/1` —— **换行符**

这条更隐蔽，但把响应体打出来就一目了然了：

| | 长度 | `\n` | `\r\n` |
|---|---|---|---|
| 宿主基线 | 519 | 0 | 22 |
| 容器实测 | 497 | 22 | 0 |

差 22 字节 = 22 个换行各多一个 `\r`。

根因在 `app/routers/quiz.py`：它以**文本模式**写导出文件
（`open(filepath, "w", encoding="utf-8")`），于是 Windows 会把每个 `\n`
翻译成 `\r\n`，Linux 不会。这是 Python 的既定行为，不是缺陷。

### 为什么**不**就地重录基线

`tests_safe/baselines/routes.json` 是"重构不改变行为"这条承诺的唯一自动证据。
**为了让一个新环境变绿而去改金标准，正好会掩盖它本该抓到的回归。**
所以这里只记录现象、不改基线；要不要让它变成跨平台可比（例如签名前统一
换行、把仓库根替换成占位符），留给你定。

在此之前，在容器里跑测试请按这一条已知差异来看结果。

---

## 容器看到的是宿主**真实的** `storage/`

仓库目录整份挂进 `/app`，所以 `/app/storage` 就是宿主的 `storage/`。
好处是容器里能直接看到本机已有的数据；代价是**容器里的写操作会落到宿主上**。

这一条在当前设计下无法两全：`storage/` 里既有真实用户数据，又是应用运行必需的。
如果你希望容器与宿主数据隔离，把 `docker-compose.yml` 里那条整目录挂载换成
只挂代码子目录、再给 `storage` 配一个**命名卷**即可——但那之后容器里就看不到
本机的历史数据了。当前按"与在本机直接跑 uvicorn 行为一致"来取舍。

> 顺带一个观察：`tests_safe/test_route_baseline.py` 把 `/api/download-exercises/1`
> 归在"纯本地且**只读**"那一组里，但该处理器其实每次都会往
> `storage/exercises/` 写一个文件（`app/routers/quiz.py`）。
> 它不写库，所以基线本身仍然稳定；但"只读"这个说法不准确，
> 且跑一遍全量测试就会留下一个文件——实测该目录里已经攒了约 170 个。

---

## 已知取舍

| 事项 | 现状 | 理由 |
|---|---|---|
| 容器内以 **root** 运行 | 开发镜像如此 | 仓库目录从 Windows 宿主挂进来，非 root 用户在这些文件上的可写性取决于 Docker Desktop 的映射策略，失败起来是"存储写入被拒"这类很难看穿的错。**生产镜像必须换成非 root**（见代办）。 |
| 热重载开的是**轮询** | `WATCHFILES_FORCE_POLLING=true` | Windows / macOS 的宿主文件系统不产生 inotify 事件，不开轮询 `--reload` 永远不触发（表现为"改了代码没反应"）。代价是 CPU 略高。 |
| `/app/venv` 被一个空卷盖住 | 有意的 | 那是开发机的 Windows venv（2.1 GB，二进制不兼容），容器用不了，还会拖慢文件监听。容器用的是镜像里的 `/opt/venv`。 |
| 端口 **8000 写死** | 未改 | `server.py` 的 `__main__` 里是硬编码的，`settings.app.port` 目前没有任何调用点。要换端口请在 `command:` 里显式 `--port`。 |
| `pip check` 不在构建里跑 | 有意的 | 这套栈（funasr / insightface / pyannote 各自钉住不同版本的 numpy、protobuf、onnx）本来就存在版本重叠，`pip check` 几乎必然报一堆，放进构建只会让构建红掉而问题依旧。 |

> 另外提醒：`docker compose config` 会把你 `.env` 里的**密钥原文打印出来**
> （它要展示插值后的最终配置）。在共享屏幕上别随手跑。

---

## 代办：线上部署（尚未开始）

本阶段**只做本地开发**。以下留待后续，需要先定方案：

1. **生产镜像**：多阶段构建，把 `gcc` / `cmake` / `build-essential` 留在 builder 层，
   运行时只带 venv——现在的镜像是单阶段的，编译工具链也跟着进了最终镜像。
2. **非 root 用户**：生产镜像必须建 UID/GID 并切过去，配合卷的属主设置。
3. **编排**：nginx 反代与 TLS（现有 `deploy/nginx-smartclass1.conf` 与
   `deploy/deploy.sh` 是 systemd 路线的，要重写成容器路线的）。
4. **配置注入**：现在是挂 `.env` 文件。生产要考虑用 Docker secrets 或
   环境注入，而不是把凭据文件放在镜像旁。
5. **健康检查与滚动更新**：现在的 `HEALTHCHECK` 打的是 `GET /`，
   生产还该有一个不依赖磁盘文件的存活探针。
6. **模型与数据卷**：`storage/research_models/` 那几 GB 模型怎么进生产环境。

`deploy/README.md` 里那份 systemd 流程在方案定下来之前**仍然是可用的**，不要提前删。
