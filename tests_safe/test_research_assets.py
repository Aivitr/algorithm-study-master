"""`/api/research-runtime` 返回的脚本路径，必须仍然指向真实存在的文件。

为什么需要这个测试
------------------
`research_runtime` 曾这样取基准目录：

```python
def _setup_scripts_summary(self) -> Dict:
    repo_root = Path(__file__).resolve().parent      # ← 以「本文件所在目录」为准
    return {... str(repo_root / "setup_enhanced_runtime.ps1") ...}
```

这些字符串会**原样出现在 `/api/research-runtime` 的响应里**。也就是说：
**文件在哪，接口就报哪**——它们不是死字符串，是被接口承诺出去的路径。

危险在于 `Path(__file__).resolve().parent` 这一句。它当时恰好等于仓库根，
所以看起来没问题；但阶段 3 要把该文件迁进 `app/`，**一迁，`parent` 就变成
`app/`，这 5 条路径会同时指空——接口不报错，只是静静地返回 5 个不存在的路径。**

**本文件在搬迁之前就把这条契约钉死了，它按设计如实变红。** 阶段 3.3 搬迁
`research_runtime` 时确实先红后绿：
- 变红 → 提示锚点会漂；
- 改为 `from app.core.paths import PROJECT_ROOT` 后重新变绿
  （同时见 `test_paths_anchor.py` 里那条静态的 `Path(__file__)` 扫描）。

保留这两条断言的理由不变：**光把当前值改对没有用**，得让"下次再有人这么写"
同样会变红。

已知缺陷：`check_runtime` 本来就是缺的
------------------------------------
`docs/待验收事项.md` A12 发现二记录：`check_enhanced_runtime.ps1` **从未存在于
仓库根**（实际在 `test/check_enhanced_runtime.ps1`，现已归档到
`archive/legacy-tests/test-dir/`）。即这一条路径**已经**指空。

那是**与本次重构无关的既有缺陷**，且修它要改动该接口的响应内容，
而 C3 冻结了 59 个接口的输出——故不修，只在此登记。

因此本测试对 `check_runtime` 采用**反向断言**：它必须**仍然**是缺的。
将来若有人修好了它，这个断言会失败并要求同步更新——这是有意的，
免得"已知缺陷清单"变成一句没人维护的注释。
"""

from pathlib import Path

from app.core.paths import PROJECT_ROOT

# 契约：这 5 个键就是接口 `setup_scripts` 字段的全部内容。
EXPECTED_KEYS = {
    "prepare_layout",
    "setup_enhanced_runtime",
    "download_open_models",
    "check_runtime",
    "requirements_file",
}

# A12 发现二：既有缺陷，本次不修。见本文件头部。
KNOWN_MISSING = {"check_runtime"}


def _summary() -> dict:
    from app.services.research_runtime import research_runtime

    return research_runtime._setup_scripts_summary()


def test_summary_exposes_exactly_the_contracted_keys():
    """键集不能变——它直接构成 `/api/research-runtime` 的响应结构（C3）。"""
    assert set(_summary()) == EXPECTED_KEYS


def test_paths_are_anchored_to_project_root_not_module_dir():
    """5 条路径都必须落在**仓库根**下。

    这一条当初是搬迁的警报器：模块一旦移入 `app/`，`Path(__file__).resolve().parent`
    就变成 `app/`，本断言会立刻失败，提示必须改用 `PROJECT_ROOT`
    （否则接口静默返回 5 个空路径）。阶段 3.3 搬迁时它**确实**红了，改完重新变绿。

    现在它守的是另一件事：**别把锚点改回去**。文件已经不在根目录了，
    再出现"以本文件所在目录为准"的写法，这里会立刻发现。
    """
    for key, path in _summary().items():
        resolved = Path(path)
        assert resolved.parent == PROJECT_ROOT, (
            f"{key} 的路径基准不是仓库根：{path}\n"
            f"  期望父目录：{PROJECT_ROOT}\n"
            f"  实际父目录：{resolved.parent}\n"
            f"research_runtime.py 很可能被移动了，而 `Path(__file__).resolve().parent` "
            f"没有一并改成 PROJECT_ROOT。"
        )


def test_expected_assets_actually_exist():
    """除已知缺陷外，其余 4 条路径必须指向真实文件。"""
    for key, path in _summary().items():
        if key in KNOWN_MISSING:
            continue
        assert Path(path).exists(), (
            f"{key} 指向的文件不存在：{path}\n"
            f"该路径由 /api/research-runtime 返回，指空即为接口层面的静默失效。"
        )


def test_known_missing_check_runtime_is_still_missing():
    """已知缺陷登记：`check_runtime` 目前是缺的。

    这条**反向断言**的意义在于把「已知缺陷」写死成可执行的事实。
    若哪天它被修复（文件补上了），本测试失败，提醒同步更新 A12 与本文件——
    避免这份清单悄悄过期。
    """
    missing = Path(_summary()["check_runtime"])
    assert not missing.exists(), (
        f"`check_runtime` 指向的文件出现了：{missing}\n"
        f"若这是有意的修复，请同步更新本文件与 docs/待验收事项.md A12 发现二。"
    )
