"""`.env.example` 必须与代码实际读取的环境变量**逐键同步**。

防的是什么
----------
「配置错误会静默生效」的文档侧表现：

- 代码新增一个 `_get_env("NEW_KEY")`，而模板没跟上 → 部署者不知道要配它，
  程序**不报错**，取默认值继续跑，直到某个功能在某台机器上悄悄失效；
- 模板里留着一个没人读的键 → 部署者填了它，以为配好了，实际没有任何效果。

两种都是"不出声的错"。本文件把它们变成红色的测试。

怎么枚举"代码实际读取的键"
--------------------------
两处**必须都扫**，漏一处就会误判：

1. 直接的 `os.getenv("X")` / `os.environ.get("X")` / `os.environ["X"]`
   —— server.py、database.py 等在用；
2. `app/core/config.py` 里的 `_get_env("X")` / `_get_int` / `_get_bool` /
   `_get_float` —— 配置层把键名藏在辅助函数的参数里。**只扫第 1 种会漏掉
   42 个键中的绝大部分**（本文件初版就踩了这个坑，把 config.py 整层漏掉了）。

只做静态解析，不导入任何模块——因此不会触发导入期副作用（例如
`app.core.database` 的建表语句）。
"""

import ast
from pathlib import Path

import pytest

from app.core.paths import PROJECT_ROOT

# 与仓库其他静态守卫保持一致：跳过第三方、归档与缓存
_SKIP_DIRS = {"venv", "archive", "__pycache__", "_tmp_agora_token_builder", ".git", ".codegraph"}

# 直接取值的方式
_DIRECT_CALLS = ("getenv", "get")
# config.py 的间接方式（键名是这些函数的第一个参数）
_HELPER_CALLS = ("_get_env", "_get_int", "_get_bool", "_get_float")


def _iter_source_files():
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def _keys_read_by_code() -> dict[str, set[str]]:
    """返回 `{键: {读取它的文件}}`，覆盖直接与间接两种写法。"""
    found: dict[str, set[str]] = {}

    def record(key: str, where: str) -> None:
        if key and key.isupper():
            found.setdefault(key, set()).add(where)

    for path in _iter_source_files():
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    name = func.attr
                elif isinstance(func, ast.Name):
                    name = func.id
                else:
                    continue
                if name in _DIRECT_CALLS + _HELPER_CALLS and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        record(arg.value, rel)

            # os.environ["X"]
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "environ"):
                slice_ = node.slice
                if isinstance(slice_, ast.Constant) and isinstance(slice_.value, str):
                    record(slice_.value, rel)

    return found


def _keys_in_example() -> set[str]:
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    keys = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


_READ = _keys_read_by_code()
_DOCUMENTED = _keys_in_example()


def test_enumeration_actually_finds_keys():
    """阳性对照：枚举器必须真的扫到东西。

    若哪天 `_keys_read_by_code()` 被改坏（例如 AST 条件写错而恒返回空集），
    下面两条断言都会"通过"——空集与任何集合都不冲突的那部分。这条先钉住
    "枚举器没坏"，让那种失效以失败的形式暴露，而不是变成一条永远绿的测试。
    """
    assert len(_READ) > 40, f"只枚举到 {len(_READ)} 个键，枚举器可能坏了"
    assert "DATABASE_URL" in _READ, "连 DATABASE_URL 都没扫到，枚举器坏了"
    assert "APP_ENV" in _READ, "没扫到 config.py 的间接写法，辅助函数分支坏了"
    assert "DB_HOST" in _READ, "没扫到 server.py 的直接写法"


@pytest.mark.parametrize("key", sorted(set(_READ) - _DOCUMENTED))
def test_every_key_read_by_code_is_documented(key):
    """代码读的每个键，模板里都必须有。

    缺失时给出读取位置，方便判断这是新配置项还是拼写错误。
    """
    where = ", ".join(sorted(_READ[key]))
    pytest.fail(
        f"`{key}` 被代码读取，但 .env.example 中没有列出。\n"
        f"读取位置：{where}\n"
        f"部署者不会知道要配它，程序会静默使用默认值。"
    )


@pytest.mark.parametrize("key", sorted(_DOCUMENTED - set(_READ)))
def test_no_documented_key_is_unused(key):
    """反向：模板里列出的键，代码里必须真的有人读。

    这条防的是"填了以为生效、实际无效"。历史上 `HF_TOKEN` 就是这种——
    模板里有，但真正被读的是 `RESEARCH_HF_TOKEN`。
    """
    pytest.fail(
        f"`{key}` 在 .env.example 中列出，但全仓库没有一处读取它。\n"
        f"填了不会生效，会误导部署者。请核实真实键名或删除该行。"
    )


# --------------------------------------------------------------------------
# 模板本身的安全性：它是**要进仓库**的，所以里面不能有真东西。
# --------------------------------------------------------------------------

_SECRET_HINTS = ("KEY", "SECRET", "PASSWORD", "TOKEN", "CERTIFICATE")
# 允许非空的安全值：这些是"格式示例"或与凭据无关的标识
_SECRET_ALLOWLIST = {
    "OSS_ACCESS_KEY_ID": {"YOUR_OSS_ACCESS_KEY_ID"},
    "ALIYUN_ACCESS_KEY_ID": {"YOUR_ALIYUN_ACCESS_KEY_ID"},
}


def test_example_has_no_filled_in_secrets():
    """任何名字带 KEY/SECRET/PASSWORD/TOKEN/CERTIFICATE 的项，模板里都必须是空的。

    `.env.example` 不被 .gitignore 忽略，它就是要进仓库的。只要有一行漏填了
    真实值，那份凭据就进了版本历史。
    """
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    offenders = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip()
        if not any(h in key for h in _SECRET_HINTS):
            continue
        if value and value not in _SECRET_ALLOWLIST.get(key, set()):
            offenders.append(f"{key}={value}")

    assert not offenders, (
        "模板里出现了填好的机密值——这个文件会进仓库：\n  "
        + "\n  ".join(offenders)
    )
