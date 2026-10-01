"""闸门：遗留测试绝不可被收集，活跃数据库绝不可指向生产。

为什么需要这个文件
------------------
`server.py` → `app/core/database.py` 的**模块导入期**会执行
`_ensure_transcripts_columns()`，必要时对 `DATABASE_URL`
指向的库发出 `ALTER TABLE transcripts ADD ...`。而遗留测试文件顶部写着
`from server import app`——**收集它们就是尝试对生产库做 DDL。**

隔离现已分三层（详见各处的文件头）：
1. 仓库根 `conftest.py`——**任何调用方式**都会加载的环境隔离（安全网）
2. `archive/legacy-tests/conftest.py` 的 `pytest_configure`——对本目录硬中止
3. `pytest.ini` 的 `testpaths = tests_safe`——默认收集范围

本文件的断言全部**不导入遗留模块**——它们只读配置、查 `sys.modules`、
检查引擎 URL、或以子进程方式调用 pytest，因此自身不会触发上述风险。

历史上的两次"静默失效"
----------------------
本文件的存在本身来自第一次：原先只靠 `testpaths` 一层，而它会被显式路径参数
覆盖。第二次见 `test_archived_explicit_path_is_refused` 的 docstring——
`pytest_ignore_collect` 对显式参数同样无效，实测否定的过程记在
`archive/legacy-tests/conftest.py` 里。两次的共同教训是同一句话：
**闸门失效时不会报错，只会静默地什么都不做。** 所以这里的断言要看得见。
"""

import configparser
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 仓库根原名 → 归档后所在目录名
LEGACY_DIRS = {"tests": "tests-dir", "test": "test-dir"}

ARCHIVE = REPO_ROOT / "archive" / "legacy-tests"


def _testpaths() -> set:
    """读出 pytest.ini 中 testpaths 的取值。"""
    ini = REPO_ROOT / "pytest.ini"
    assert ini.exists(), f"缺少 {ini}——隔离依赖它，不能缺失"

    parser = configparser.ConfigParser()
    parser.read(ini, encoding="utf-8")
    raw = parser.get("pytest", "testpaths", fallback="")
    return {p.strip() for p in raw.replace("\n", " ").split() if p.strip()}


@pytest.mark.parametrize("legacy", sorted(LEGACY_DIRS))
def test_legacy_dir_no_longer_exists_in_repo_root(legacy):
    """`tests/` 与 `test/` 必须**不在**仓库根，且其归档副本必须存在。

    这条原先写的是「不在 testpaths 里即可，目录不存在就 skip」。归档之后那个
    skip 反而成了掩盖回归的东西：若哪天有人把这两个目录从 archive 挪回仓库根，
    老写法会**静默跳过**而不是报警。故改为两向的主动断言——
    仓库根必须没有，归档里必须还在（同一条断言同时挡住"被删掉"和"被挪回来"）。
    """
    assert not (REPO_ROOT / legacy).exists(), (
        f"{legacy}/ 又出现在仓库根了。它应当只存在于 archive/legacy-tests/ 下。\n"
        f"这些文件顶部 `from server import app`，一旦落入收集范围即触发生产库 "
        f"DDL 尝试（app/core/database.py 的 _ensure_transcripts_columns）。"
    )

    archived = ARCHIVE / LEGACY_DIRS[legacy]
    assert archived.is_dir(), (
        f"归档副本 {archived} 不存在——{legacy}/ 既不在仓库根、也不在归档里，"
        f"说明文件被删了。按「全量保留」的约定：不删除任何文件。"
    )


def test_root_conftest_gate_exists():
    """仓库根的 `conftest.py` 必须存在——它是唯一覆盖所有调用方式的闸门。

    单独断言它的存在，因为它的缺失**不会有任何症状**：测试照跑、照通过，
    只是隔离没了。真实事故就是这样发生的（回归测试见
    `test_archived_explicit_path_is_refused`）。
    """
    root_conftest = REPO_ROOT / "conftest.py"
    assert root_conftest.is_file(), (
        f"缺少 {root_conftest}。它是唯一在**任何** pytest 调用方式下都会加载的"
        f"隔离点；tests_safe/conftest.py 只在按默认方式运行时被加载。"
    )


def test_legacy_test_modules_are_not_imported():
    """遗留测试模块不得被导入进本进程。

    比上一条更深一层：即使目录回来了、testpaths 被人改宽，只要遗留模块没被
    import，风险就没有兑现。反之，这里出现任何一个名字，都说明闸门已经失守。
    """
    legacy_names = {
        "test_api_endpoints",
        "test_llm_adapter",
        "test_llm_core",
        "test_llm_endpoints",
        "regression_test",
        "load_test",
    }
    leaked = legacy_names & set(sys.modules)
    assert not leaked, (
        f"遗留测试模块已被导入：{sorted(leaked)}。"
        f"这些文件顶部有 `from server import app`，导入即可能对生产库执行 DDL。"
    )


def test_archived_explicit_path_is_refused():
    """事故回归测试：**显式点名**归档测试文件，必须被拒绝收集。

    这正是发生过的真实事故：

        $ pytest archive/legacy-tests/tests-dir/test_api_endpoints.py --collect-only
        3 tests collected in 3.59s        ← 真实 import 了 server/database

    当时认为 `collect_ignore` 和 `pytest_ignore_collect` 能挡住，**两者都不行**：
    pytest 把显式给出的参数登记为 *init path*，有意豁免它们的一切 ignore 检查。
    最终有效的做法是在 `archive/legacy-tests/conftest.py` 的 `pytest_configure`
    里直接检查参数。

    这个测试**必须真的起一个子进程**：本进程内的任何模拟都还原不出
    "init path 被豁免"这个行为，而那恰恰是事故的成因。

    安全性：子进程继承本进程的环境变量，其中 `DATABASE_URL` 已被根 conftest
    改成 sqlite、`DB_HOST` 已改成不可达值。**即便闸门与根 conftest 同时失效，
    子进程也连不到生产库。**
    """
    target = ARCHIVE / "tests-dir" / "test_api_endpoints.py"
    assert target.is_file(), f"回归测试的目标文件不见了：{target}"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"  # 避免中文输出在 GBK 控制台上炸掉

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(target.relative_to(REPO_ROOT)),
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    output = proc.stdout + proc.stderr

    # pytest 把 UsageError 记为退出码 4
    assert proc.returncode != 0, (
        f"显式点名归档测试文件竟然执行成功了——闸门失效。\n{output}"
    )
    assert "拒绝收集" in output, (
        f"退出码非 0，但不是本仓库闸门造成的（可能只是路径写错）。\n{output}"
    )
    # 未被收集 = 未发生 import server → database
    assert "test_ai_tutor" not in output, (
        f"归档测试被收集了，闸门失效，已发生 `import server`。\n{output}"
    )


def test_active_database_is_local_sqlite(local_app):
    """当前进程实际使用的数据库必须是本地 sqlite。

    这是隔离是否生效的终局判据——不看意图，看实际连的是什么。
    """
    from app.core import database

    url = str(database.engine.url)
    assert url.startswith("sqlite"), (
        f"活跃数据库不是 sqlite：{url}\n"
        f"根 conftest.py 的 §1 隔离未生效，测试可能正在读写生产库。"
    )
    assert "aliyuncs" not in url and "mssql" not in url, (
        f"活跃数据库 URL 中出现生产标识：{url}"
    )


def test_settings_agree_with_engine(local_app):
    """`config.settings.db.url` 与 ORM 引擎必须指向同一处。

    两者若不一致，说明存在"配置说本地、实际连生产"（或反之）的错位——
    这种错位不会报错，只会让测试在错误的数据上通过。
    """
    from app.core import config
    from app.core import database

    engine_url = str(database.engine.url)
    settings_url = str(config.settings.db.url)

    # sqlite 的 URL 表示形式在两侧可能略有差异（相对/绝对路径），只比对类别
    assert settings_url.startswith("sqlite") == engine_url.startswith("sqlite"), (
        f"配置与引擎指向不同类别：config={settings_url!r} engine={engine_url!r}"
    )
