# 本地开发容器化（阶段 5）

> **这份文档只管"本地开发"。线上部署的镜像与指令**尚未编写**——见文末代办。**
> `deploy/README.md` 里那套 systemd + nginx 的流程仍然有效，没被这份取代。

---

## 它解决什么

消除「重建 venv 结果不同」。本仓库对环境的依赖相当刁钻，手工复现一遍要踩这些坑：

- Python 必须是 **3.12**（本机默认的 3.14 装不上依赖）
- `setuptools` 必须 `<81`，否则 `webrtcvad` 顶层那句 `import pkg_resources` 直接失败
- `insightface` / `webrtcvad` 在 Linux 上没有预编译轮子，要现场编译
- `opencv-python` 导入期要 dlopen `libGL.so.1`

容器把这些一次性钉死在 `Dockerfile` 里，换台机器 `docker compose up --build` 即可。

## 一条命令

```bash
docker compose up --build
```

然后打开 <http://localhost:8000>。

首次构建要装一整套 ML 依赖（torch / insightface / pyannote / funasr），**很慢，且镜像很大**。
之后只要 `requirements.txt` 没变，改代码不会触发重装——依赖分了三层缓存，见 `Dockerfile` 的注释。

```bash
docker compose up -d            # 后台跑
docker compose logs -f app      # 看日志
docker compose down             # 停掉（不会删数据卷）
docker compose run --rm app python -m pytest     # 在容器里跑测试套件
docker compose run --rm app bash                 # 进容器看看
```

---

## 起容器之前：`.env` 里必须有 `LLM_API_KEY`

这一条是构建时**实测撞出来**的，不是推测：

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

## 安全设计：容器**默认连不上生产库**

这一节请务必读完再改 `docker-compose.yml`。

**背景**：`app/core/database.py` 的 `_ensure_transcripts_columns()` 在**导入期**执行，
也就是 **`import` 即 DDL**。而工作区的 `.env` 指向**生产 RDS**。
所以「容器起来时连的是哪个库」不是一个抽象配置问题，它直接决定了
容器启动时会不会对生产库发 `ALTER TABLE transcripts ADD ...`。

**做法**：`app/core/config.py::_apply_env_file` 用的是 `os.environ.setdefault` 语义——
**进程里已有的环境变量赢过 `.env` 文件**。这条既有语义正好可以当安全阀：
`docker-compose.yml` 的 `environment:` 段显式给出 6 个数据库键，
`.env` 里指向生产的同名值就再也盖不过来。

| 键 | 容器里的值 | 为什么是这个值 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./storage/app.db` | ORM 侧回退到容器内 SQLite |
| `DB_HOST` | `127.0.0.1` | `/api/register`、`/api/login` 直连用，容器里没人监听 → 立刻连接被拒 |
| `DB_PORT` | `1433` | 同上 |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | 占位值 | 同上，且一眼能看出不是真的 |

两条**不要做**：

- **不要删掉这几行** —— `.env` 的生产值会原样生效。
- **不要在后面的清单文件里改成空字符串** —— `create_engine("")` 会直接抛
  `ArgumentError`，应用起不来。「显式赋值为无害值」和「赋空值」是两回事，
  前者才是安全阀。（`tests_safe/conftest.py` 出于同一理由也是赋值而非 `del`。）

这一条由 `tests_safe/test_docker_assets.py::TestComposeNeutralizesProductionDatabase`
钉住——有人顺手清理掉那几行时，测试会红。

### 那我想连真实库联调怎么办

仓库**刻意不提供**现成的叠加文件：那等于把"容器会连生产库"变成一个随手可及的开关。
真要这么做，自己写一份 `docker-compose.realdb.yml`：

```yaml
# 只在明确要连真实库时创建，用完删掉
services:
  app:
    environment:
      DATABASE_URL: ${DATABASE_URL:?请在 .env 里设置}
      DB_HOST: ${DB_HOST:?}
      DB_PORT: ${DB_PORT:-1433}
      DB_USER: ${DB_USER:?}
      DB_PASSWORD: ${DB_PASSWORD:?}
      DB_NAME: ${DB_NAME:?}
```

```bash
docker compose -f docker-compose.yml -f docker-compose.realdb.yml up
```

`:?` 的作用是"没设就报错停下"，而不是静默连到别处去。

> ⚠️ 这样起来之后，容器**会对生产库发 DDL**。动手前确认你确实要这个。
>
> ⚠️ 变量值里若含 `$`，compose 的插值会吃掉它。密码里有 `$` 时别用这个写法。

### `.env` 不会进镜像

`Dockerfile` 最后一步是 `COPY . .`，因此 `.dockerignore` 里第一条就是 `.env`。
镜像层只增不减，**一旦把生产口令打进层里，事后改 `.dockerignore` 也抹不掉**。
这道防线同样由 `tests_safe/test_docker_assets.py` 断言。

---

## 容器里的配置来自哪

`.env` **会**跟着仓库目录挂进容器（`/app/.env`），这是有意的：
LLM / OSS / 阿里云那些键正需要它，被 `environment:` 挡住的**只有数据库那 6 个**。
优先级是「`environment:` > `.env`」，两处都写了的以 `environment:` 为准。

一个副作用（与在本机直接跑 `uvicorn` 时**完全一样**）：
调 `/api/research-runtime` 的配置接口会就地改写 `.env` 里的 `RESEARCH_*` 三行，
而这个 `.env` 就是宿主上那个文件。

---

## 在容器里跑测试：预计会有 **1 条**基线失败，且已查明原因

```bash
docker compose run --rm --no-deps app python -m pytest -q
# → 1 failed, 276 passed, 2 skipped
```

失败的是 `test_route_baseline`，只涉及 59 条路由里的 **2 条**。
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

路径在响应里出现多次，累计差 665 字节（基线 14388 → 容器 13723）。

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
换行、把仓库根替换成占位符），留给你定 —— 见 A24。

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
> 见 A24。

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
