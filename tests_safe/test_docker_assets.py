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

2. **容器默认连生产库。**
   `app/core/config.py::_apply_env_file` 用 `setdefault` 语义——**进程环境变量优先**。
   这既有的语义正好可以拿来当安全阀：只要 compose 在 `environment:` 里显式给出
   那 6 个数据库键，`.env` 里指向生产的同名声就永远盖不过来。
   本条断言那 6 个键**确实在**——有人"顺手清理"掉它们时，测试会红，
   而不是等到某次 `docker compose up` 静默对生产库发了 ALTER TABLE。

   （为什么是赋值而不是 `del`：`_apply_env_file` 对"不存在的键"会补上文件里的值。
   `del` 掉等于把生产值请回来。见 `tests_safe/conftest.py` 同款理由。）

3. **requirements.txt 被切成两份时的静默遗漏。**
   镜像分两层装依赖（torch 三件套走 PyTorch CPU 索引，其余走 PyPI）。
   切分由 `tools/split_requirements.py` 现算，不另立一份清单——但"现算"也得
   有人证明它没把某个包漏掉或算重。漏掉的后果是运行时 `ModuleNotFoundError`，
   且按本仓库的老规矩，多半还是**延迟导入**里才炸。

对齐 `pytest.ini` 的安全约定：本文件只读文件、不起容器、不连任何数据库。
"""

from __future__ import annotations

import importlib.util
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
)


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


def _compose() -> dict:
    path = REPO_ROOT / "docker-compose.yml"
    assert path.is_file(), f"{path} 不存在（阶段 5 的本地开发编排）"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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


# --------------------------------------------------------------------------
# 2. 容器默认不得连生产库
# --------------------------------------------------------------------------


class TestComposeNeutralizesProductionDatabase:
    def test_app_service_environment_overrides_all_db_keys(self):
        services = _compose().get("services") or {}
        assert services, "docker-compose.yml 里没有任何 service"

        # 取各 service 里唯一那个跑应用的（本阶段的编排只有它一个）
        env = {}
        for service in services.values():
            env.update(service.get("environment") or {})

        missing = [key for key in _PROD_DB_KEYS if key not in env]
        assert not missing, (
            f"docker-compose.yml 的 environment 没有覆盖这些键：{missing}。\n"
            f"原因：app/core/config.py 用 os.environ.setdefault 语义加载 .env，"
            f"**进程环境变量优先**。这里显式给出即可挡住 .env 里的生产值；"
            f"一个都不给，容器起来就会连上生产 RDS，并在**导入期**执行"
            f"_ensure_transcripts_columns()。\n"
            f"（不要改成 del/留空字符串：前者等于把生产值请回来，"
            f"后者会让 create_engine('') 直接抛异常。）"
        )

    def test_default_database_url_is_local_sqlite(self):
        services = _compose()["services"]
        env = {}
        for service in services.values():
            env.update(service.get("environment") or {})
        assert str(env["DATABASE_URL"]).startswith("sqlite:"), (
            "默认 DATABASE_URL 应当指向容器内的 SQLite（无害回退），"
            f"实际是 {env['DATABASE_URL']!r}。"
        )


# --------------------------------------------------------------------------
# 3. 依赖切分是一份**划分**：不漏、不重、不另立清单
# --------------------------------------------------------------------------


class TestRequirementsSplit:
    def test_split_is_a_partition_preserving_order(self):
        tool = _load_split_tool()
        source = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        heavy, light = tool.split_requirements(source)

        origin = [
            line.strip()
            for line in source.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        merged = heavy + light

        # (a) 合起来 = 原清单。少一项就是容器里运行期 ModuleNotFoundError，
        #     多一项就是装了个清单里没有的包。
        assert sorted(merged) == sorted(origin), (
            "切分后的两份合起来与 requirements.txt 对不上——"
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
            f"重型层的顺序与 requirements.txt 不一致：{heavy}"
        )
        assert is_subsequence(light, origin), (
            f"其余层的顺序与 requirements.txt 不一致：{light}"
        )

    def test_every_declared_heavy_package_exists_in_requirements(self):
        tool = _load_split_tool()
        source = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        names = {
            line.strip().split("==")[0].split(">=")[0].split("<")[0].strip().lower()
            for line in source.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        missing = [name for name in tool.HEAVY_PACKAGES if name not in names]
        assert not missing, (
            f"切分工具声明这些包走 PyTorch 索引，但 requirements.txt 里没有：{missing}。\n"
            f"多半是 requirements.txt 改了名或删了包，而切分名单没跟着改——"
            f"那会让 Dockerfile 去装一个清单里不存在的包，或者反过来"
            f"让某个 torch 系包走了普通 PyPI（在 Linux 上会拉进 CUDA 版，镜像涨到数 GB）。"
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
