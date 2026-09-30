"""闸门：遗留目录绝不可被收集，活跃数据库绝不可指向生产。

为什么需要这个文件
------------------
安全依仗的是 `pytest.ini` 里的 `testpaths = tests_safe`。**那是配置，配置会被
误改**——一次手滑的 `pytest tests/`，或一次"顺手把 testpaths 放宽"的改动，就会
让 `tests/test_api_endpoints.py:2` 的 `from server import app` 生效，进而触发
`database.py:246` 的模块级 `_ensure_transcripts_columns()`，对生产库发出
`ALTER TABLE transcripts ADD ...`。

详见 `docs/legacy-assets-audit.md` §1.1。

本文件的断言全部**不导入遗留模块**——它们只读配置、查 `sys.modules`、
检查引擎 URL，因此自身不会触发上述风险。
"""

import configparser
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DIRS = ["tests", "test"]


def _testpaths() -> set:
    """读出 pytest.ini 中 testpaths 的取值。"""
    ini = REPO_ROOT / "pytest.ini"
    assert ini.exists(), f"缺少 {ini}——隔离依赖它，不能缺失"

    parser = configparser.ConfigParser()
    parser.read(ini, encoding="utf-8")
    raw = parser.get("pytest", "testpaths", fallback="")
    return {p.strip() for p in raw.replace("\n", " ").split() if p.strip()}


@pytest.mark.parametrize("legacy", LEGACY_DIRS)
def test_legacy_dir_is_not_in_testpaths(legacy):
    """遗留目录不得出现在 testpaths 中。

    这是整套隔离的第一道闸门。`tests/` 下有 6 个会 `from server import app`
    的文件，被收集即触发生产库 DDL 尝试。
    """
    if not (REPO_ROOT / legacy).is_dir():
        pytest.skip(f"{legacy}/ 已不存在")

    paths = _testpaths()
    assert legacy not in paths and f"{legacy}/" not in paths, (
        f"pytest.ini 的 testpaths 包含了 {legacy}/——"
        f"它会被收集，从而 import server → 触发生产库 DDL 尝试。"
        f"当前 testpaths = {sorted(paths)}"
    )


def test_legacy_test_modules_are_not_imported():
    """遗留测试模块不得被导入进本进程。

    比上一条更深一层：即使 testpaths 被人改成包含两者，只要遗留模块没被 import，
    风险就没有兑现。反之，这里出现任何一个名字，都说明闸门已经失守。
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


def test_active_database_is_local_sqlite(local_app):
    """当前进程实际使用的数据库必须是本地 sqlite。

    这是隔离是否生效的终局判据——不看意图，看实际连的是什么。
    """
    import database

    url = str(database.engine.url)
    assert url.startswith("sqlite"), (
        f"活跃数据库不是 sqlite：{url}\n"
        f"conftest 的 §1 隔离未生效，测试可能正在读写生产库。"
    )
    assert "aliyuncs" not in url and "mssql" not in url, (
        f"活跃数据库 URL 中出现生产标识：{url}"
    )


def test_settings_agree_with_engine(local_app):
    """`config.settings.db.url` 与 ORM 引擎必须指向同一处。

    两者若不一致，说明存在"配置说本地、实际连生产"（或反之）的错位——
    这种错位不会报错，只会让测试在错误的数据上通过。
    """
    import config
    import database

    engine_url = str(database.engine.url)
    settings_url = str(config.settings.db.url)

    # sqlite 的 URL 表示形式在两侧可能略有差异（相对/绝对路径），只比对类别
    assert settings_url.startswith("sqlite") == engine_url.startswith("sqlite"), (
        f"配置与引擎指向不同类别：config={settings_url!r} engine={engine_url!r}"
    )
