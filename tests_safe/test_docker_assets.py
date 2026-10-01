"""容器化资产守卫（阶段 5）。

本文件防的是容器化引入的**两类新故障**，两类都不会在 `python server.py` 下出现，
所以既有的 264 个测试一个都拦不住：

1. **镜像里带着生产凭据。**
   `Dockerfile` 最后一步是 `COPY . .`。只要 `.dockerignore` 漏掉 `.env`，
   生产库口令就进了镜像层——而镜像层是**只增不减**的，之后无论怎么改都
   仍在 `docker history` 里躺着。本仓库的 `.env` 恰好指向生产 RDS
   （见 `tests_safe/README.md` 那条导入链），所以这不是理论风险。
   同理，`python server.py` 的**导入期**会执行 `_ensure_transcripts_columns()`，
   于是"容器起来时连的是哪个库"直接决定它会不会对生产库发 DDL。

2. **容器连错库 / 压根连不上。**
   这一条换过形态。原先是"写死当安全阀"：compose 的 `environment:` 里显式给出
   那 6 个数据库键，把 `.env` 里指向生产的值盖住（`setdefault` 语义下进程环境变量优先）。
   那时工作区的 `.env` 装的就是生产库，只能这么挡。

   改成**按环境分层**后，开发侧指向生产的键根本不在 `.env` 里
   （它们在 gitignore 的 `.env.prod`），于是断言也跟着换了对象：
   不再问"盖住了没有"，而问 **"库指向是不是只有一个来源、且那个来源指向本机容器"**。
   具体在 `TestComposePointsAtTheLocalDatabase`（编排形状）、
   `TestDevEnvLayer`（开发层内容）与 `TestNoProductionCredentialsAreTracked`
   （凭据没被提交）三处。

3. **requirements.txt 被切成两份时的静默遗漏。**
   镜像分两层装依赖（torch 三件套走 PyTorch CPU 索引，其余走 PyPI）。
   切分由 `tools/split_requirements.py` 现算，不另立一份清单——但"现算"也得
   有人证明它没把某个包漏掉或算重。漏掉的后果是运行时 `ModuleNotFoundError`，
   且按本仓库的老规矩，多半还是**延迟导入**里才炸。

4. **构建上下文里少了运行时资产。**
   前三条都在挡"不该进去的进去了"，这条挡反方向：`.dockerignore` 是一条通配规则
   就能扫掉一整棵子树的，而 `index.html`、`static/` 这些正是 `server.py` 在
   **运行时**才读的。少一个的后果在宿主机上完全不可见——所有测试读的是宿主文件，
   只有容器里的页面白屏。阶段 6 把前端资源全量落到 `static/` 之后，
   这条路第一次真的会疼。

对齐 `pytest.ini` 的安全约定：本文件只读文件、不起容器、不连任何数据库。
"""

from __future__ import annotations

import importlib.util
from fnmatch import fnmatch
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# 必须由 compose **显式覆盖**的数据库键。
#
# 这张名单不是随手挑的：它对应两条**读不同变量**的代码路径
# （`app/core/database.py` 读 DATABASE_URL，`app/routers/auth.py` 的
# 注册/登录直连读 DB_*）。少覆盖任何一条，那条路径就连回生产。
_PROD_DB_KEYS = (
    "DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
)

# 绝不能进构建上下文的东西。分两类理由：
#   * 凭据：`.env`（生产口令）、`voiceprints.json`（真实用户声纹）
#   * 体积：`venv/`（2.1 GB）、`.git/`、`storage/`、`uploads/`（真实用户文件）
_FORBIDDEN_IN_CONTEXT = (
    ".env",
    "venv",
    ".git",
    "storage",
    "uploads",
    "voiceprints.json",
    # 2026-10-01 加。加它不是为了好看：它是这份清单里**唯一一条此前
    # 没有任何断言盯着**的排除项——`.dockerignore` 里写着它，但名单里没有它，
    # 于是"删掉那一行"不会有任何测试变红。
    #
    # 但要说清这条断言**抓不到什么**：下面的比对是把模式字符串做归一化
    # （去尾 `/`、去头部 `*` 与 `/`），`CDN本地化命令.txt` 与 `**/CDN本地化命令.txt`
    # 归一到同一个串，两者都算通过。所以它只保证"名字还在清单里"，
    # **不保证模式在 Docker 的路径语义下真的匹配得到**。真正的坑正是后者：
    # 文件从根目录搬走、模式还是裸文件名，规则就悄悄失效（现已改成 `**/`）。
    # 那是靠人看注释守的，别指望这条断言。
    "CDN本地化命令.txt",
    # 2026-10-02 加。归档的死代码与旧运维脚本不进镜像层。理由不是体积
    # （整棵 archive/ 才 1.1 MB），而是那份层的性质：Dockerfile 末行 `COPY . .`
    # 会把它烘进镜像，而镜像层只增不减。archive/ 里躺着 `ops-scripts/`
    # 那批碰生产库的脚本与 prototypes/ 里的半成品，它们**没有任何 import 指向**
    # （运行链路不读 archive/），烘进可推送的层是纯负担。
    #
    # 注意这条**在开发容器里看不出来**：docker-compose.yml 把仓库 bind-mount 到
    # `/app`，运行时是宿主那份，archive/ 照旧在。这条只管烘进镜像的那一份——
    # 也就是真正会被 push、被线上拉起的那一份。同理，容器内跑测试也不受影响：
    # 它读的是挂载进来的宿主 archive/，`test_legacy_isolation.py` 要求的
    # `archive/legacy-tests/` 仍然在。
    "archive",
)

# 反过来：必须**留在**构建上下文里的运行时资产。
#
# 上面那张表是"进去了就出事"，这张是"没进去就出事"。只挡一个方向是不够的——
# `.dockerignore` 的末尾一直写着「index.html、app/、tools/ 都要保留」，
# 但那句话此前**只是散文**：谁要是在那里补一条 `static/`（理由是"生成物不必进镜像"，
# 听上去相当合理），宿主机上的每一条测试都会照样全绿，只有容器里的页面变成白屏。
# 阶段 6 把前端资源全量落到 static/ 之后，这条路径第一次真的会疼。
_REQUIRED_IN_CONTEXT = (
    "index.html",        # app/routers/pages.py 的 `GET /` 真的读这个文件
    "pcm-processor.js",  # `GET /pcm-processor.js`
    "static",            # 阶段 6：本地化的前端资源，由 server.py 的 /static 挂载伺服
    "app",
    "tools",
    "tests_safe",
)


def _dockerignore_patterns() -> set[str]:
    """`.dockerignore` 里生效的行（去注释、去空行）。文件不存在则返回空集。"""
    ignore = REPO_ROOT / ".dockerignore"
    if not ignore.is_file():
        return set()
    return {
        line.strip()
        for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _pattern_hits(relpath: str, patterns: set[str]) -> bool:
    """单条仓库相对路径（`app/x.py`）会不会被这些模式排除。

    认识的形态：精确同名（含整棵子树）、`**/x`、`*.ext`。
    不认识的：中缀 `a/**/b`、字符类、转义。真到那一步，与其把这里养成小半个
    Docker，不如直接起一次容器验证。

    `fnmatch` 的 `*` 会跨 `/`，比 Docker 的本义宽一点——对这个用途是好事：
    多认出来的情形由调用方（只判顶层条目）兜着，不会变成误报。
    本函数的行为由 `test_pattern_hits_matches_expectation` 逐条钉住，
    因为它一旦被"简化"成字符串相等，上面那条断言就会静默失效。
    """
    for raw in patterns:
        if raw.startswith("!"):  # 取反规则本身不构成排除
            continue
        pattern = raw.rstrip("/")
        if not pattern:
            continue
        if relpath == pattern or relpath.startswith(pattern + "/"):
            return True
        if fnmatch(relpath, pattern):
            return True
        if pattern.startswith("**/") and fnmatch(relpath, pattern[3:]):
            return True
    return False


# 本守卫**只判条目整体是否被排除**，不逐个子文件扫。
#
# 这一条边界是试出来的：最初的版本 rglob 整个子树，结果
# `app/__pycache__/*.pyc` 立刻报了红——而那是**应该**被排除的，Python 会重新生成
# 字节码。把"整棵子树被扫掉"和"子树里的缓存被扫掉"混为一谈，守卫就变成了噪声。
#
# 代价是漏掉一种情形：`**/*.css` 这类规则不会让 `static` 这个目录名被排除，
# 却会扫掉它下面的样式表。这个缺口是**已知且有意留着**的——
# 真要堵它，就得逐文件判定"这个文件运行时会不会被读到"，而那需要引入
# SOURCES.json / index.html 的可达性，等于把阶段 6 的守卫复制一份到这里。
# 与其做一个半吊子的复制，不如把边界写清楚：这里管"目录整个没了"。


def _load_split_tool():
    """按路径加载 `tools/split_requirements.py`。

    `tools/` 没有 `__init__.py`，靠隐式命名空间包能被 `import tools.x` 找到——
    但那要求当前工作目录恰好是仓库根。测试可能在别处被调用，所以按文件路径加载，
    摆脱对 cwd 的依赖（`test_paths_anchor.py` 说的正是这类 cwd 假设）。
    """
    path = REPO_ROOT / "tools" / "split_requirements.py"
    spec = importlib.util.spec_from_file_location("_split_requirements", path)
    assert spec is not None and spec.loader is not None, f"无法加载 {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _compose_file(name: str) -> dict:
    path = REPO_ROOT / name
    assert path.is_file(), f"{path} 不存在（阶段 5 的本地开发编排）"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _compose() -> dict:
    return _compose_file("docker-compose.yml")


def _env_file_entries(service: dict) -> list[tuple[str, bool]]:
    """把一个 service 的 `env_file` 归一成 [(路径, 是否必填)]。

    compose 允许两种写法：裸字符串（默认 required: false）与
    `{path: ..., required: ...}`。两种都得认，否则换个写法守卫就静默失效。
    """
    out = []
    for entry in service.get("env_file") or []:
        if isinstance(entry, str):
            out.append((entry, False))
        elif isinstance(entry, dict):
            out.append((str(entry.get("path")), bool(entry.get("required", False))))
    return out


def _parse_env_file(path: Path) -> dict[str, str]:
    """读一个 .env 形态的文件成字典。只认 `KEY=VALUE`，跳过注释与空行。"""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


# --------------------------------------------------------------------------
# 1. 构建上下文不得含凭据与体积大户
# --------------------------------------------------------------------------


class TestDockerignore:
    def test_dockerignore_exists(self):
        ignore = REPO_ROOT / ".dockerignore"
        assert ignore.is_file(), (
            "缺少 .dockerignore。Dockerfile 的 `COPY . .` 会因此把 venv/（2.1 GB）、"
            ".git/ 与**生产凭据 .env** 一并打进镜像。"
        )

    @pytest.mark.parametrize("entry", _FORBIDDEN_IN_CONTEXT)
    def test_heavy_or_secret_path_is_excluded(self, entry):
        ignore = REPO_ROOT / ".dockerignore"
        if not ignore.is_file():
            pytest.skip(".dockerignore 不存在（另一条断言已在报红）")

        lines = {
            line.strip()
            for line in ignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        # 接受 `venv`、`venv/`、`**/venv` 等写法
        assert any(entry == line or line.rstrip("/").lstrip("*").lstrip("/") == entry
                   for line in lines), (
            f".dockerignore 没有排除 {entry!r}。"
            f"现有条目：{sorted(lines)}"
        )

    @pytest.mark.parametrize("entry", _REQUIRED_IN_CONTEXT)
    def test_runtime_asset_is_not_excluded(self, entry):
        """运行时真会读的文件/目录不得被 `.dockerignore` 扫出去。

        与上一条互补：那条问"危险的东西出去了吗"，这条问"必需的东西还在吗"。
        只挡前者的话，一条看着很合理的 `static/`（"生成物，何必进镜像"）
        就能让容器里的页面白屏，而**宿主机的全部测试依然全绿**——
        正是阶段 6 要消灭的那类"在开发机上看不出来"。

        判据是"这个条目**本身**会不会被排除"，不追究它下面的缓存目录
        （见 `_pattern_hits` 上方那段边界说明）。
        """
        assert not _pattern_hits(entry, _dockerignore_patterns()), (
            f".dockerignore 排除了 {entry!r}。\n"
            f"这类资产由 `python server.py` 在运行时读取，宿主机上永远看不出问题，"
            f"只有容器里才会表现为白屏或 404。"
        )


# 守卫自己的守卫。
#
# 上面那条断言的全部力量都在 `_pattern_hits` 上：它要是被"简化"成只做字符串相等
# （很容易发生——看着像等价改写），`static/` 这类规则就再也拦不住，
# 而上面那条测试**照样全绿**。本仓库反复出现的就是这种失效。
#
# 两个方向都点名：该报的必须报，不该报的必须不报。后者同样重要——
# 会误报的守卫会被注释掉（这个函数的 rglob 版本就是这么被改掉的）。
@pytest.mark.parametrize(
    "entry, patterns, expected",
    [
        ("static", {"static/"}, True),
        ("static", {"static"}, True),
        ("static", {"**/static"}, True),
        ("index.html", {"*.html"}, True),
        ("pcm-processor.js", {"**/*.js"}, True),
        # 不该报：子树里的缓存被排除是正常的，Python 会重建
        ("static", {"**/__pycache__"}, False),
        ("app", {"*.py[cod]"}, False),
        ("tools", {"tmp/"}, False),
        # 取反规则不构成排除
        ("static", {"!static"}, False),
    ],
)
def test_pattern_hits_matches_expectation(entry, patterns, expected):
    assert _pattern_hits(entry, patterns) is expected


# --------------------------------------------------------------------------
# 2. 容器不得连生产库（安全阀换了形态：写死 → 分层）
# --------------------------------------------------------------------------
#
# 上一版的两条断言（`environment` 里必须写死那 6 个键、且 DATABASE_URL 必须是
# 无害的 sqlite 回退）已经**随设计一起作废**：那时工作区的 `.env` 装的就是
# 生产库，只能靠"进程环境变量优先"把它盖住。
#
# 现在改成按环境分层 —— 开发工作区里指向生产的那 6 个键**根本不在 `.env` 里**
# （它们在 `.env.prod`，而 `.env.prod` 被 gitignore）。安全性由"压根没有"提供，
# 比"写死挡住"更强。于是守卫要跟着换：不再问"盖住了没有"，而要问
# **"库指向是不是只有一个来源，且那个来源指向本机容器"**。


class TestComposePointsAtTheLocalDatabase:
    def test_db_is_a_registry_image_with_a_named_volume(self):
        """db 必须是**单独拉取**的 registry 镜像，且数据落命名卷。

        - 不能有 `build:`：那意味着数据库被打包进本仓库构建的镜像，与
          "组件镜像单独拉取、服务只负责连过去"的约定相反。
        - 数据目录必须挂**命名卷**（不是 bind mount）：bind mount 在
          Windows/macOS 上会因宿主文件系统不表达 POSIX 权限而起不来。
        """
        db = (_compose().get("services") or {}).get("db")
        assert db is not None, "docker-compose.yml 里没有 db 服务"

        assert db.get("build") is None, (
            "db 声明了 build —— 数据库应当用 registry 镜像单独拉取，"
            "而不是由本仓库构建。"
        )
        image = str(db.get("image", ""))
        assert image.startswith("mcr.microsoft.com/mssql/server"), (
            f"db 用的不是 MSSQL 官方镜像，而是 {image!r}。\n"
            f"pymssql 说的是 TDS 协议，换成 MySQL 镜像后 /api/register、"
            f"/api/login 依然是死的（只是从「连接被拒」变成「语法错误」）。"
        )

        mounts = [str(v) for v in (db.get("volumes") or [])]
        data_mounts = [m for m in mounts if m.endswith(":/var/opt/mssql")]
        assert data_mounts, (
            f"db 的数据目录没有挂卷：{mounts}。\n"
            f"不挂卷的话数据落在容器的可写层，容器一删库就没了"
            f"（此前那个手起的 smartclass-mssql 就是这么丢了数据的）。"
        )
        for mount in data_mounts:
            assert not mount.startswith((".", "/", "~", "\\")), (
                f"db 数据卷应当是**命名卷**而不是 bind mount，实际是 {mount!r}。"
            )

    def test_db_init_runs_the_schema_script(self):
        """一次性建库服务的三个要件：脚本在、目录挂了、服务确实引用了它。"""
        for name in ("db/schema.sql", "db/init.sh"):
            path = REPO_ROOT / name
            assert path.is_file(), (
                f"{name} 不存在。"
                f"MSSQL 镜像没有 postgres/mysql 那样的 /docker-entrypoint-initdb.d，"
                f"建库只能靠 db-init 服务跑这个脚本。"
            )
            assert path.read_text(encoding="utf-8").strip(), f"{name} 是空的"

        init = (_compose().get("services") or {}).get("db-init")
        assert init is not None, "docker-compose.yml 里没有 db-init 服务"

        mounts = [str(v) for v in (init.get("volumes") or [])]
        assert any("/db" in m for m in mounts), (
            f"db-init 没有挂载 db/ 目录：{mounts}，它读不到 schema.sql"
        )

    def test_schema_sql_is_idempotent(self):
        """建库脚本必须**重复执行无副作用** —— 这是"生产开发通用"的前提。

        判据是每条 CREATE 都被 IF ... IS NULL / IF NOT EXISTS 包住。
        `docker compose up` 每次都会重跑 db-init；不幂等的话第二次就报错，
        而那个报错发生在一个人毫不知情的时候（他只是重启了一下服务）。
        """
        sql = (REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        # 逐条 CREATE TABLE 都要有 OBJECT_ID 守卫
        tables = [ln for ln in sql.splitlines() if ln.startswith("CREATE TABLE ")]
        guards = [ln for ln in sql.splitlines() if "OBJECT_ID(N'dbo." in ln and "IS NULL" in ln]
        assert tables, "schema.sql 里一条 CREATE TABLE 都没有"
        assert len(guards) >= len(tables), (
            f"{len(tables)} 张表但只有 {len(guards)} 条 OBJECT_ID 守卫 —— "
            f"有表没被 IF ... IS NULL 包住，重复执行会报 'already exists'。"
        )
        # 索引与外键同理
        for stmt in ("CREATE NONCLUSTERED INDEX", "CREATE UNIQUE NONCLUSTERED INDEX"):
            made = [ln for ln in sql.splitlines() if ln.startswith(stmt)]
            if made:
                assert "IF NOT EXISTS (SELECT 1 FROM sys.indexes" in sql, (
                    f"有 {stmt} 但没有对应的 IF NOT EXISTS 守卫"
                )
        assert "IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys" in sql or \
               "ADD CONSTRAINT" not in sql, (
            "有外键约束但没有 IF NOT EXISTS 守卫，重复执行会撞名"
        )

    def test_app_waits_for_db_init(self):
        """app 必须等 db-init **成功退出**，否则会连上一个还没建表的空库，
        然后在注册时抛出一个和真实原因毫无关系的错。"""
        app = _compose()["services"]["app"]
        depends = app.get("depends_on") or {}
        assert isinstance(depends, dict), (
            "app 的 depends_on 写成了短格式（列表）—— 那种写法不支持 condition，"
            "等价于只保证容器启动顺序，不保证 db-init 跑完。"
        )
        condition = (depends.get("db-init") or {}).get("condition")
        assert condition == "service_completed_successfully", (
            f"app 对 db-init 的 condition 是 {condition!r}，"
            f"应为 'service_completed_successfully'。"
        )

    def test_app_takes_db_config_from_the_env_layer(self):
        """app 的库指向只能来自 `.env.dev`，不能又写死在 environment 里。"""
        app = _compose()["services"]["app"]

        entries = dict(_env_file_entries(app))
        assert ".env.dev" in entries, (
            "app 没有读 .env.dev —— 库指向就没来源了"
        )
        assert entries[".env.dev"] is True, (
            ".env.dev 必须写成 required: true。\n"
            "缺了它的正确表现是 compose 立刻报错；写成 required: false 的话，"
            "容器会带着空的 DB_* 起来，然后在注册时给一个莫名其妙的失败。"
        )

        hardcoded = sorted(set(_PROD_DB_KEYS) & set(app.get("environment") or {}))
        assert not hardcoded, (
            f"app 的 environment 里又写死了 DB 键：{hardcoded}。\n"
            f"库指向应当由 .env.dev 单独提供 —— 两个来源一旦不一致，"
            f"症状是「连不上库」这种指不到病因的报错。"
        )

    def test_no_other_service_defines_db_keys(self):
        """反向断言：**除 app 外**任何 service 都不得在 environment 里定义那 6 个键。

        为什么要反向断言：上面那条只管得住 app。若将来新加的服务（或有人
        "顺手"给 db/db-init 补上）也能设置这些键，配置就有了第二个入口 ——
        这正是"守卫拦不住"的失效的典型：断言写在 A 上，改动却发生在 B。
        """
        offenders = {}
        for name, service in (_compose().get("services") or {}).items():
            if name == "app":
                continue
            hit = sorted(set(_PROD_DB_KEYS) & set(service.get("environment") or {}))
            if hit:
                offenders[name] = hit
        assert not offenders, (
            f"这些服务在 environment 里定义了库配置键：{offenders}。\n"
            f"库指向只应有 app 一个消费者；运维侧容器（db/db-init）用的是"
            f"MSSQL_* 自己那套命名。"
        )


# --------------------------------------------------------------------------
# 2b. 开发库那层本身：指向哪里、口令是不是只有一个来源
# --------------------------------------------------------------------------


class TestDevEnvLayer:
    @pytest.fixture()
    def example(self) -> dict[str, str]:
        path = REPO_ROOT / ".env.dev.example"
        assert path.is_file(), (
            f"{path.name} 不存在。它是给人照抄的模板（cp .env.dev.example .env.dev），"
            f"必须入库。"
        )
        return _parse_env_file(path)

    def test_declares_every_db_key(self, example):
        """6 个键 + sa 口令，一个都不能少 —— 它们对应**读不同变量**的代码路径。

        注意这里刻意用变量下标而不是字面量 `example.get("MSSQL_SA_PASSWORD")`：
        `tests_safe/test_env_docs.py` 把任何 `get("大写串")` 都当作"代码读取了
        这个环境变量"，字面量写法会让 MSSQL_SA_PASSWORD 被误判成 app 的配置项，
        进而要求它出现在 `.env.example` 里 —— 而它其实是 db 容器与 init.sh 的，
        归属 `.env.dev.example`。
        """
        required = ["MSSQL_SA_PASSWORD"] + list(_PROD_DB_KEYS)
        missing = [k for k in required if not example.get(k)]
        assert not missing, (
            f".env.dev.example 缺少这些键：{missing}。\n"
            f"ORM 读 DATABASE_URL，而 /api/register、/api/login **不走 ORM**，"
            f"直接读 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME。"
            f"少任何一个，那条路径就连不上。"
        )

    def test_points_at_the_compose_db_service(self, example):
        """宿主名必须是服务名 `db`，端口必须是**容器内**的 1433。

        这条防的是最常见的手误：照着本机联调的习惯写成 localhost:1433。
        容器里的 localhost 是容器自己，没有任何东西监听。
        """
        assert example["DB_HOST"] == "db", (
            f"DB_HOST 是 {example['DB_HOST']!r}，应为 'db'（compose 网络里的服务名）。\n"
            f"写 localhost 的话，容器里的 localhost 是它自己。"
        )
        assert example["DB_PORT"] == "1433", (
            f"DB_PORT 是 {example['DB_PORT']!r}，应为容器内的 1433。"
        )
        assert example["DB_NAME"] == "cscl_db", (
            f"DB_NAME 是 {example['DB_NAME']!r}，应与 db/schema.sql 建的库同名。"
        )

    def test_password_has_exactly_one_source(self, example):
        """`MSSQL_SA_PASSWORD`、`DB_PASSWORD` 与 `DATABASE_URL` 里嵌的口令必须一致。

        这三个值语义上是**同一个口令**：第一个是 db 容器初始化 sa 时设的，
        后两个是 app 连它时提供的。改一个忘另两个的症状是"连不上库"，
        而报错信息完全指不出病因。所以这里把"它们相等"从约定变成断言。
        """
        from urllib.parse import unquote, urlsplit

        sa = example["MSSQL_SA_PASSWORD"]
        assert example["DB_PASSWORD"] == sa, (
            f"DB_PASSWORD 与 MSSQL_SA_PASSWORD 不一致 —— app 会用错口令连 db"
        )
        url = urlsplit(example["DATABASE_URL"])
        assert unquote(url.password or "") == sa, (
            f"DATABASE_URL 里嵌的口令与 MSSQL_SA_PASSWORD 不一致 —— "
            f"ORM 那条路径会连不上（而注册/登录用的却是另一个口令，两边表现不一致，更难查）"
        )

    def test_database_url_matches_the_same_target(self, example):
        """DATABASE_URL 的方言、主机、端口、库名要与 DB_* 一致。"""
        from urllib.parse import urlsplit

        url = urlsplit(example["DATABASE_URL"])
        assert url.scheme == "mssql+pymssql", (
            f"DATABASE_URL 的方言是 {url.scheme!r}，应为 mssql+pymssql"
        )
        assert url.hostname == example["DB_HOST"], "DATABASE_URL 的主机与 DB_HOST 不一致"
        assert str(url.port) == example["DB_PORT"], "DATABASE_URL 的端口与 DB_PORT 不一致"
        assert url.path.lstrip("/") == example["DB_NAME"], "DATABASE_URL 的库名与 DB_NAME 不一致"


# --------------------------------------------------------------------------
# 2c. 入库文件不得含生产凭据
# --------------------------------------------------------------------------


class TestNoProductionCredentialsAreTracked:
    """把"生产主机名/口令没被提交"从一次人工核对变成可重复的断言。

    为什么现在才需要它：分层之前，生产凭据集中在**一个** gitignore 的 `.env` 里，
    只要那条 gitignore 规则在就不会漏。分层之后，凭据散在 `.env.prod`、
    模板、文档、部署脚本若干处 —— 少写一个占位符、文档里顺手贴一段真实连接串，
    都能把生产主机名带进仓库。实测已经发现过一次。

    跳过而不是失败：新克隆的仓库里本来就没有 `.env.prod`（它不入库），
    这时没有真相可比，没得测。
    """

    def test_tracked_files_contain_no_prod_db_values(self):
        import subprocess

        prod = REPO_ROOT / ".env.prod"
        if not prod.is_file():
            pytest.skip(".env.prod 不存在（新克隆的仓库里本来就没有）—— 无真相可比")

        # 只查**真正敏感**的三个。DB_PORT / DB_NAME 不是秘密：3433 是阿里云 RDS
        # 的常见端口，cscl_db 在 db/schema.sql 与编排文件里到处都要出现。
        # 把它们扫进来只会得到假红 —— 而假红会让人把这个守卫整个关掉。
        env = _parse_env_file(prod)
        values = {k: env.get(k, "") for k in ("DB_HOST", "DB_USER", "DB_PASSWORD")}
        # 太短的值（比如 1~3 个字符）当子串搜会匹配到无关内容，同样是假红来源
        values = {k: v for k, v in values.items() if len(v) >= 4}
        assert values, f"{prod} 里没有可查的敏感值（DB_HOST/DB_USER/DB_PASSWORD），测试无意义"

        leaked = {}
        for key, value in values.items():
            result = subprocess.run(
                ["git", "grep", "-lF", "--", value],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
            )
            if result.stdout.strip():
                leaked[key] = result.stdout.strip().splitlines()

        assert not leaked, (
            f"入库文件里出现了生产库的值：{leaked}\n"
            f"生产凭据只应存在于 .env.prod（已被 gitignore）。"
            f"文档里请写占位符，例如 <生产 RDS 主机名>。"
        )


class TestGeneratedSchemaCarriesNoSourceHost:
    """比上一条**更早生效**的守卫：不依赖 `.env.prod` 是否存在。

    上一条在新克隆的仓库里会 skip（那里没有 `.env.prod` 当真相），于是最需要它
    的时候恰好不在。这一条不问"值泄没泄"，只问"产物里有没有写出源主机的位置"——
    与真值无关，任何克隆都跑。

    实测经过：`db/schema.sql` 的自动生成头部原本写的是
    `来源：cscl_db @ <真实主机>`，随第一次提交入了库，随后才被上一条抓住。
    所以这里再钉一道，并且钉在**产物形状**上——生成器改回去就会立刻红。
    """

    def test_schema_sql_source_line_has_no_host(self):
        text = (REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        offenders = [ln for ln in text.splitlines() if "来源：" in ln and "@" in ln]
        assert not offenders, (
            "db/schema.sql 的「来源」行里嵌了主机名 —— 这个文件是入库的：\n  "
            + "\n  ".join(offenders)
            + "\n主机名只应存在于 .env.prod（已 gitignore）。"
            "产物里别写它，或改写 <生产 RDS 主机名>。"
        )

    def test_exporter_header_does_not_interpolate_the_host(self):
        """生成器本身也不许把 host 插进「来源」行——否则重新生成就会复发。

        改产物是治标：`db/schema.sql` 是**生成物**，跑一次
        `python tools/export_prod_schema.py --yes` 就带回来了。真正的修处在模板。
        """
        lines = (REPO_ROOT / "tools" / "export_prod_schema.py").read_text(
            encoding="utf-8"
        ).splitlines()
        offenders = [ln.strip() for ln in lines if "来源：" in ln and "{host}" in ln]
        assert not offenders, (
            "生成器的头部模板又把源主机名插回去了：\n  "
            + "\n  ".join(offenders)
            + "\n改这里才治本 —— db/schema.sql 是生成物。"
        )


# --------------------------------------------------------------------------
# 3. 依赖切分是一份**划分**：不漏、不重、不另立清单
# --------------------------------------------------------------------------


class TestRequirementsSplit:
    @pytest.mark.parametrize("manifest", ["requirements.txt", "requirements-dev.txt"])
    def test_split_is_a_partition_preserving_order(self, manifest):
        tool = _load_split_tool()
        path = REPO_ROOT / manifest
        source = path.read_text(encoding="utf-8")
        # 基准取**展开 -r 之后**的清单：开发镜像是照着 requirements-dev.txt 装的，
        # 它首行的 `-r requirements.txt` 必须被跟随，否则 torch 会整个漏掉。
        origin = tool.expand_requirements(source, path.parent)
        heavy, light = tool.split_requirements(source, path.parent)

        assert origin, f"{manifest} 展开后一条 requirement 都没有"
        merged = heavy + light

        # (a) 合起来 = 原清单。少一项就是容器里运行期 ModuleNotFoundError，
        #     多一项就是装了个清单里没有的包。
        assert sorted(merged) == sorted(origin), (
            f"切分后的两份合起来与 {manifest}（展开 -r 后）对不上——"
            "有包被漏掉或重复。漏掉的包在容器里要到**运行时**才报 ModuleNotFoundError。\n"
            f"  只在原清单：{sorted(set(origin) - set(merged))}\n"
            f"  只在切分后：{sorted(set(merged) - set(origin))}"
        )
        assert len(merged) == len(set(merged)), (
            f"切分后出现重复条目：{sorted(x for x in merged if merged.count(x) > 1)}"
        )

        # (b) 每一份都保持它在原清单里的**相对顺序**。
        #
        #     这里不能写成 `merged == origin`——heavy 是从原清单**中间**抽出来的，
        #     拼回去必然换位。真正要保的不变量是"顺序不变"而非"位置不变"：
        #     顺序一旦被打乱，改一个无关行的位置就会让镜像层缓存整体失效。
        def is_subsequence(sub: list[str], whole: list[str]) -> bool:
            it = iter(whole)
            return all(item in it for item in sub)

        assert is_subsequence(heavy, origin), (
            f"重型层的顺序与 {manifest} 不一致：{heavy}"
        )
        assert is_subsequence(light, origin), (
            f"其余层的顺序与 {manifest} 不一致：{light}"
        )

    def test_every_declared_heavy_package_exists_in_requirements(self):
        tool = _load_split_tool()
        # 拿开发镜像真正会喂进去的那份清单来核。
        path = REPO_ROOT / "requirements-dev.txt"
        names = {
            tool.package_name(line)
            for line in tool.expand_requirements(
                path.read_text(encoding="utf-8"), path.parent
            )
        }
        missing = [name for name in tool.HEAVY_PACKAGES if name not in names]
        assert not missing, (
            f"切分工具声明这些包走 PyTorch 索引，但 requirements-dev.txt"
            f"（展开 -r 后）里没有：{missing}。\n"
            f"多半是清单改了名或删了包，而切分名单没跟着改——"
            f"那会让 Dockerfile 去装一个清单里不存在的包，或者反过来"
            f"让某个 torch 系包走了普通 PyPI（在 Linux 上会拉进 CUDA 版，镜像涨到数 GB）。"
        )


# --------------------------------------------------------------------------
# 3b. GPU 直通是**叠加**文件，不是第二份编排
# --------------------------------------------------------------------------
#
# `docker-compose.gpu.yml` 存在的唯一理由是：`deploy.resources.reservations.devices`
# 在 compose 里是硬要求 —— 宿主没有能看见 GPU 的容器运行时（Linux 的
# nvidia-container-toolkit / Windows 的 WSL2 后端）时，compose 会在起 app
# **之前**直接报 `could not select device driver "" with capabilities: [[gpu]]`。
# 所以它绝不能进主文件：那等于把"必须有 NVIDIA 显卡"加给每一个跑标准版的人，
# 而标准版前提是"宿主只需 Docker"。
#
# 下面六条按危险程度排：倒数第二条（主文件里不许有）才是真正要守住的，
# 最后一条反过来盯着它别变成空转。


_GPU_OVERRIDE = "docker-compose.gpu.yml"


def _reserved_devices(service: dict) -> list:
    """Service 声明的设备预留（`deploy.resources.reservations.devices`）。

    单独抽出来是因为它被两个方向用到：一个查叠加文件**有**，一个查主文件**没有**。
    后者的失效方式是**静默**的——这段 dict 导航要是写错了，它取到的永远是空列表，
    于是"主文件里不许有"这条断言平凡通过，而仓库里那台没独显的机器照样起不来。
    所以调用方还得有一条反向断言盯着这个函数本身（见下面的
    `test_the_reservation_scanner_finds_the_known_good_override`）。
    """
    return (
        ((service.get("deploy") or {}).get("resources") or {})
        .get("reservations", {})
        .get("devices")
        or []
    )


class TestGpuOverrideStaysAnOverride:
    def test_it_only_touches_the_app_service(self):
        """叠加文件只许改 app。

        多写一个 `db:` 就等于把数据库的定义复制到这里 —— 主文件一改就悄悄
        分叉，而症状是"加了 GPU 之后库连不上了"这种指不到病因的报错。
        """
        services = _compose_file(_GPU_OVERRIDE).get("services") or {}
        assert set(services) == {"app"}, (
            f"{_GPU_OVERRIDE} 只应叠加 app，实际写了：{sorted(services)}"
        )

    def test_it_reserves_an_nvidia_gpu(self):
        app = _compose_file(_GPU_OVERRIDE)["services"]["app"]
        devices = _reserved_devices(app)
        assert any(
            "nvidia" in str(d.get("driver"))
            and "gpu" in [str(c) for c in d.get("capabilities") or []]
            for d in devices
        ), (
            f"{_GPU_OVERRIDE} 里没有 nvidia 的设备预留：{devices}\n"
            f"写法见 compose 规范：deploy.resources.reservations.devices 下"
            f"`driver: nvidia` + `capabilities: [gpu]`。"
        )

    def test_it_does_not_pin_the_build_context_again(self):
        """叠加文件不得重复 context / dockerfile / target。

        写了就等于把它们钉死在本文件里：主文件哪天改了构建目标，只有不加 GPU
        的人跟着变，加 GPU 的人还停在旧的那份上——两套镜像长得不一样。
        """
        build = _compose_file(_GPU_OVERRIDE)["services"]["app"].get("build") or {}
        for key in ("context", "dockerfile", "target"):
            assert key not in build, (
                f"{_GPU_OVERRIDE} 的 app.build 里又写了一遍 `{key}` —— "
                f"叠加文件只应补 `args`，其余交给主文件。"
            )

    def test_it_does_not_smuggle_database_config(self):
        """与 `test_no_other_service_defines_db_keys` 同一个理由：配置只应有一个入口。"""
        app = _compose_file(_GPU_OVERRIDE)["services"]["app"]
        hit = sorted(set(_PROD_DB_KEYS) & set(app.get("environment") or {}))
        assert not hit, f"{_GPU_OVERRIDE} 里的 app.environment 定义了库键：{hit}"

    def test_the_main_file_carries_no_gpu_reservation(self):
        """**这一条是本节的重点**：主文件里出现设备预留，标准版就废了。

        `docker-compose.yml` 是"一条命令拉起整套系统"的那份，前提是宿主
        只需 Docker。设备预留是硬要求，写进去以后没有独显的机器、演示机和 CI
        都会在 `up` 时直接失败 —— 而且失败发生在**起服务之前**，
        报的是 docker 的设备驱动错误，和"这个仓库需要显卡"这件事看不出关系。
        """
        offenders = {
            name: _reserved_devices(service)
            for name, service in (_compose().get("services") or {}).items()
            if _reserved_devices(service)
        }
        assert not offenders, (
            f"docker-compose.yml 里有服务预留了设备：{offenders}\n"
            f"GPU 直通只应写在 {_GPU_OVERRIDE} 里，用 "
            f"`docker compose -f docker-compose.yml -f {_GPU_OVERRIDE} up` 叠加。"
        )

    def test_the_reservation_scanner_finds_the_known_good_override(self):
        """守卫自己的守卫：上面那条断言的力量全在 `_reserved_devices` 上。

        它要是哪天被"简化"（或 compose 的字段层级理解错了），取到的永远是空
        列表，于是"主文件里不许有设备预留"**照样全绿**——而仓库里这台没独显的
        机器在 `up` 时会直接失败。本仓库反复出现的就是这类"断言写在 A 上、
        改动发生在 B"的静默失效。

        所以这里拿那份**已知正确**的叠加文件反向验证：扫描器必须能在它身上
        看见预留。
        """
        app = _compose_file(_GPU_OVERRIDE)["services"]["app"]
        assert _reserved_devices(app), (
            f"扫描器在 {_GPU_OVERRIDE} 上什么都没找到，而那份文件里明明有预留。\n"
            f"说明 `_reserved_devices` 的字段层级已经与 compose 规范对不上——"
            f"上面那条「主文件不许有」的断言因此是平凡成立的。"
        )


# --------------------------------------------------------------------------
# 4. 编排引用的 Dockerfile 真的在
# --------------------------------------------------------------------------


def test_compose_build_context_has_a_dockerfile():
    services = _compose().get("services") or {}
    for name, service in services.items():
        build = service.get("build")
        if build is None:
            continue
        context = build if isinstance(build, str) else build.get("context", ".")
        dockerfile = "Dockerfile" if isinstance(build, str) else build.get("dockerfile", "Dockerfile")
        assert (REPO_ROOT / context / dockerfile).is_file(), (
            f"service {name!r} 声明构建 {context}/{dockerfile}，但该文件不存在"
        )
