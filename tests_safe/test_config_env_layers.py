"""分环境配置：`.env.<APP_ENV>` 作为覆盖层，且有**唯一的「活动 env 文件」**概念。

本文件回答的是“配置错误会静默生效”那条问题
------------------------------------
「配置错误会静默生效——服务可能连到错误的数据源」。

阶段 4 之前，全项目只有**一个** `.env`：读它、也写它
（`_write_env_updates()` 会就地改写，见 `server.py:2375` 的研究配置持久化）。
于是"切换环境"实际上是"手工编辑那个文件"，而 `APP_ENV` 虽然被读进
`settings.app.env`，**全仓库没有任何一处消费它**——环境概念是装饰性的。

本步给 `APP_ENV` 以实际含义：它选择一个**覆盖层** `.env.<APP_ENV>`，
叠加在基础 `.env` 之上。

优先级（从高到低）
------------------
1. **进程环境变量**——最高。这是既有语义（`setdefault`），本步不动它：
   测试隔离闸门正是靠"先显式赋值 DB_* 再导入 config"来挡住生产库的
   （见根 `conftest.py`）。
2. `.env.<APP_ENV>` 覆盖层
3. `.env` 基础层

**为什么"零变化"是本步的硬要求**
--------------------------------
阶段 4 做这步时，本仓库只有一个 `.env`，且它指向生产 RDS。所以当时必须做到：
**不存在覆盖层文件时，行为与改前逐位相同**。下面 `test_no_overlay_is_bit_identical`
就是钉这一条——否则这次"配置改造"本身就成了新的事故来源。

（阶段 8 起仓库里**确实有了**覆盖层：`.env.dev` / `.env.prod` 做环境分层。
上面那条 `tmp_path` 造的假目录仍全部成立，它测的是**加载机制**，
与仓库里实际有没有覆盖层无关。）

测试怎么做到不碰真实 `.env`
---------------------------
配置函数都接受显式的 `root` / `environ` 参数（生产调用处走默认值）。
本文件全部用 `tmp_path` 造的假目录与假字典，**不读、不写仓库里那个真实的
`.env`**——它含有生产库凭据。
"""

import subprocess
from pathlib import Path

import pytest

from app.core import config
from app.core.paths import PROJECT_ROOT


# ---------------------------------------------------------------- 读文件

def test_read_env_file_parses_and_skips_noise(tmp_path):
    """基本解析：取 KEY=VALUE，跳过空行与注释，剥掉包裹的引号。"""
    f = tmp_path / ".env"
    f.write_text(
        "# 注释行\n"
        "\n"
        "PLAIN=value\n"
        "SPACED =  padded  \n"
        'DOUBLE="quoted"\n'
        "SINGLE='quoted'\n"
        "WITH_EQUALS=a=b=c\n"
        "EMPTY=\n",
        encoding="utf-8",
    )
    got = dict(config._read_env_file(f))
    assert got["PLAIN"] == "value"
    assert got["SPACED"] == "padded"
    assert got["DOUBLE"] == "quoted"
    assert got["SINGLE"] == "quoted"
    # 只按第一个 '=' 切分，值里的 '=' 必须保留（密码里常有）
    assert got["WITH_EQUALS"] == "a=b=c"
    assert got["EMPTY"] == ""
    assert "#" not in got


def test_read_env_file_missing_returns_empty(tmp_path):
    """文件不存在时返回空列表，**不抛异常**——调用方据此判断层是否存在。"""
    assert config._read_env_file(tmp_path / "nope.env") == []


# ---------------------------------------------------------------- 写环境

def test_apply_env_file_does_not_override_existing(tmp_path):
    """既有环境变量优先——这是本仓库既有的 `setdefault` 语义，必须保持。

    测试隔离闸门依赖它：先显式赋值生产相关的 `DB_*`，再导入 config，
    靠的就是"已存在的不被 `.env` 覆盖"。
    """
    f = tmp_path / ".env"
    f.write_text("A=from_file\nB=from_file\n", encoding="utf-8")

    environ = {"A": "from_process"}
    added = config._apply_env_file(f, environ)

    assert environ["A"] == "from_process", "进程环境变量被文件覆盖了"
    assert environ["B"] == "from_file"
    assert added == 1, "返回值应为「本次新写入的条数」"


# ---------------------------------------------------------------- APP_ENV 的选择

def test_resolve_app_env_prefers_process_env(tmp_path):
    """进程环境里的 APP_ENV 优先于 `.env` 里的。"""
    base = tmp_path / ".env"
    base.write_text("APP_ENV=from_file\n", encoding="utf-8")
    assert config._resolve_app_env({"APP_ENV": "from_process"}, base) == "from_process"


def test_resolve_app_env_falls_back_to_base_file_then_default(tmp_path):
    """`.env` 里有就用它；都没有则默认 `dev`。"""
    base = tmp_path / ".env"
    base.write_text("APP_ENV=staging\n", encoding="utf-8")
    assert config._resolve_app_env({}, base) == "staging"

    empty = tmp_path / "empty.env"
    empty.write_text("OTHER=1\n", encoding="utf-8")
    assert config._resolve_app_env({}, empty) == "dev"

    assert config._resolve_app_env({}, tmp_path / "missing.env") == "dev"


# ---------------------------------------------------------------- 分层加载

def _write(root: Path, name: str, body: str) -> Path:
    p = root / name
    p.write_text(body, encoding="utf-8")
    return p


def test_overlay_overrides_base(tmp_path):
    """覆盖层里有的键以覆盖层为准，其余仍来自基础层。"""
    _write(tmp_path, ".env", "SHARED=base\nONLY_BASE=b\n")
    _write(tmp_path, ".env.dev", "SHARED=overlay\nONLY_OVERLAY=o\n")

    environ = {"APP_ENV": "dev"}
    config._load_dotenv(root=tmp_path, environ=environ)

    assert environ["SHARED"] == "overlay"
    assert environ["ONLY_BASE"] == "b", "基础层独有的键不应丢失"
    assert environ["ONLY_OVERLAY"] == "o"


def test_process_env_beats_every_layer(tmp_path):
    """进程环境变量高于覆盖层、也高于基础层。"""
    _write(tmp_path, ".env", "K=base\n")
    _write(tmp_path, ".env.dev", "K=overlay\n")

    environ = {"APP_ENV": "dev", "K": "process"}
    config._load_dotenv(root=tmp_path, environ=environ)
    assert environ["K"] == "process"


def test_no_overlay_is_bit_identical(tmp_path):
    """**本步的硬要求**：不存在覆盖层文件时，加载结果与"只有基础层"完全一致。

    这条断言防的是"配置改造本身成为新的事故来源"：当前仓库只有一个 `.env`
    且指向生产库，若加了分层后哪怕多写入一个键、或改变一个既有键的取值，
    后果都不可接受。所以逐键比对两次加载的全部结果。
    """
    _write(tmp_path, ".env", "A=1\nB=2\nAPP_ENV=dev\n")

    # 场景一：今天的行为——只加载基础层
    before = {"APP_ENV": "dev"}
    config._apply_env_file(tmp_path / ".env", before)

    # 场景二：分层加载（本目录没有 .env.dev）
    after = {"APP_ENV": "dev"}
    config._load_dotenv(root=tmp_path, environ=after)

    assert after == before


# ---------------------------------------------------------------- 活动文件（读与写必须同一个）

def test_active_file_is_overlay_when_present(tmp_path):
    """有覆盖层时，「活动文件」是覆盖层。"""
    _write(tmp_path, ".env", "A=1\n")
    _write(tmp_path, ".env.dev", "B=2\n")

    active = config._load_dotenv(root=tmp_path, environ={"APP_ENV": "dev"})
    assert active == tmp_path / ".env.dev"


def test_active_file_is_base_when_no_overlay(tmp_path):
    """没有覆盖层时，「活动文件」是基础层——与今天一致。"""
    _write(tmp_path, ".env", "A=1\n")
    active = config._load_dotenv(root=tmp_path, environ={"APP_ENV": "dev"})
    assert active == tmp_path / ".env"


def test_active_file_is_none_when_nothing_exists(tmp_path):
    """两个文件都不存在时返回 None（调用方据此不做写回）。"""
    active = config._load_dotenv(root=tmp_path, environ={"APP_ENV": "dev"})
    assert active is None


def test_writer_targets_the_active_file_not_always_dot_env(tmp_path):
    """**写回必须落在活动文件上**，否则读写分家。

    这是本步最容易出事的地方：`server.py:2375` 的
    `persist_research_runtime_config()` 会**就地改写** env 文件。
    若读的是 `.env.prod` 而写的是 `.env`，那台机器上的研究配置就会写错文件；
    更糟的情形是反过来——把运行时改动写进了不该碰的那一份。
    """
    _write(tmp_path, ".env", "RESEARCH_RUNTIME_MODE=documented_only\n")
    _write(tmp_path, ".env.dev", "RESEARCH_RUNTIME_MODE=enhanced_strict\n")

    active = config._load_dotenv(root=tmp_path, environ={"APP_ENV": "dev"})
    config._write_env_updates({"RESEARCH_RUNTIME_MODE": "enhanced_strict"}, env_path=active)

    assert "enhanced_strict" in (tmp_path / ".env.dev").read_text(encoding="utf-8")
    # 基础层不得被这次写回改动——它可能正是生产那一份
    assert (tmp_path / ".env").read_text(encoding="utf-8") == (
        "RESEARCH_RUNTIME_MODE=documented_only\n"
    ), "写回改动了非活动文件"


# ---------------------------------------------------------------- 现状核对

def test_repo_has_exactly_the_expected_overlay_files():
    """登记现状：本仓库**有了**覆盖层，且就是这几份，没有多出来的。

    这一条是从 `test_repo_has_no_overlay_files_today` 演化来的 —— 它当时断言
    "一份覆盖层都没有"，并在文档里写明那是**现状登记而非永久断言**：
    "一旦有人真的加了覆盖层，这条会失败，提醒同步检查生产部署说明"。
    阶段 8 正是那个时刻（引入 `.env.dev` / `.env.prod` 做环境分层），
    于是按它自己写下的指示，把它换成这个后继版本。

    它现在防的东西变了：不再是"有没有分层"，而是**分层有没有失控** ——
    多出一份没人知道来历的 `.env.staging`，就意味着有一台机器在用一套
    谁也没测过的配置。多出来的那份必须在这里登记、并想清楚它由谁消费。
    """
    from app.core.paths import PROJECT_ROOT

    expected = {
        ".env.dev.example",    # 开发库指向（模板，入库）
        ".env.prod.example",   # 线上库指向（模板，含占位符，入库）
        ".env.dev",            # 开发层实体（gitignore）
        ".env.prod",           # 线上层实体（含生产凭据，gitignore）
    }
    found = {p.name for p in PROJECT_ROOT.glob(".env.*") if p.name != ".env.example"}

    unexpected = sorted(found - expected)
    assert not unexpected, (
        f"仓库里出现了预期之外的 env 覆盖层：{unexpected}。\n"
        f"多一份覆盖层 = 有一台机器在用一套谁也没测过的配置。\n"
        f"若确实需要，请把它加进本测试的 expected 集合，并说明它由谁消费。"
    )


# ---------------------------------------------------------------- 覆盖层的凭据防泄漏
#
# 这一段是**实测发现的问题**后补的，不是预防性设计：
# 引入 `.env.<APP_ENV>` 覆盖层时，`.gitignore` 里只有一条 `.env`。
# 也就是说 `.env.prod`（装生产凭据的那份）**不会被忽略**——
# 加"分环境支持"这个动作本身，反倒让生产凭据变得容易提交。
#
# 这属于同一类问题：不是"现在错了"，而是
# **"将来错了却不出声"**。所以这里用 `git check-ignore` 把规则本身钉住。

@pytest.mark.parametrize(
    "name",
    [".env.prod", ".env.dev", ".env.staging", ".env.local", ".env.production"],
)
def test_env_overlay_files_are_gitignored(name):
    """任何 `.env.<环境>` 覆盖层都必须被 git 忽略——它们装的是凭据。"""
    result = subprocess.run(
        ["git", "check-ignore", "-q", name],
        cwd=str(PROJECT_ROOT), capture_output=True,
    )
    assert result.returncode == 0, (
        f"{name} 没有被 .gitignore 忽略——它含有凭据，提交出去就是泄露。\n"
        f"请确认 .gitignore 里有 `.env.*` 这条规则。"
    )


def test_env_examples_are_not_gitignored():
    """示例文件必须**不被**忽略——它是给人照抄的模板，得进仓库。

    这条与上一条是一对：防的是"为了盖住 .env.prod 而顺手写成 `.env*`"，
    那会把示例文件也一起挡在仓库外，模板随之消失 —— 而模板一消失，
    新开发者就不知道开发库该指向哪里，只能靠猜。

    阶段 8 加了 `.env.dev.example` / `.env.prod.example` 之后，
    这条从"只有 .env.example"扩成逐个点名：**每一个**模板都要能进仓库。
    """
    for name in (".env.example", ".env.dev.example", ".env.prod.example"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", name],
            cwd=str(PROJECT_ROOT), capture_output=True,
        )
        assert result.returncode != 0, (
            f"{name} 被 .gitignore 忽略了，但它应当进仓库。\n"
            f"请检查是否误写成了 `.env*` 这类过宽的规则。"
        )
