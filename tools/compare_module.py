"""在**同一个进程、同一份环境**里，比对「搬迁前的模块」与「搬迁后的模块」。

为什么不能分两次跑
------------------
配置与数据模型的值都取决于输入——`os.environ`、`.env`、文件系统。分两次进程
跑，两次看到的输入可能不同，差异就会被误读成回归；反过来说，**两边输入不同时
"没有差异"更是假阳性**。所以比配置必须在同一进程里做。

做法
----
把搬迁前的文件**按源码加载**成一个临时模块（不碰 sys.path、不碰已安装的包），
再正常 import 搬迁后的模块，然后逐字段比对。两边共享同一个 `os.environ`，
`.env` 由 `_load_dotenv()` 的 setdefault 语义决定——对两边是同一件事。

    python tools/compare_module.py \
        --old-file /tmp/head_config.py --old-name config_head \
        --new-module app.core.config \
        [--config-path settings]

比对的内容
----------
- 公开名字的**集合**（只在一侧出现的名字会被指出）
- 标量：直接相等
- dataclass 实例：按字段路径递归展开后逐字段相等
- 函数/类：比对 `inspect.getsource` 的规范化文本（纯搬迁时应当逐字相同）

**不覆盖**：SQLAlchemy 声明式类之间的语义等价——那由 `schema_snapshot.py`
按表结构比对，比"类对象相不相等"有意义得多。

被比对的值里可能含密钥。因此差异输出对**看起来像密钥的字段**只打印摘要，
不打印原文（见 `_SENSITIVE`）。
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import importlib.util
import inspect
import re
import sys
from pathlib import Path

# 搬迁前的文件里可能有 `from app.core.paths import ...` 这类仓库内的绝对导入。
# 必须显式把仓库根放进 sys.path，否则加载旧文件会 ModuleNotFoundError
# （**加载失败**不是"比对通过"，不能被当成一致）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 名字里含这些片段的字段，差异只报摘要不报原值
_SENSITIVE = ("key", "secret", "password", "token", "url", "host", "user")


def load_from_file(name: str, path: str):
    """把某个 .py 文件加载成模块，不经过 sys.path。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法从 {path} 加载模块")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def flatten(prefix: str, obj, out: dict) -> None:
    """把 dataclass 递归摊平成 {字段路径: 值}；其余原样作为叶子。"""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for field in dataclasses.fields(obj):
            flatten(f"{prefix}.{field.name}" if prefix else field.name,
                    getattr(obj, field.name), out)
    else:
        out[prefix] = obj


def _sensitive(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _SENSITIVE)


def _show(path: str, value) -> str:
    """差异里的值怎么显示：敏感字段只给摘要。"""
    if _sensitive(path) and not isinstance(value, (bool, int, float)):
        digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
        return f"<{type(value).__name__}, sha256:{digest}>"
    return repr(value)


_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def _values_equal(a, b) -> bool:
    """叶子值是否相同。

    不能一律用 `==`：SQLAlchemy 的 `Engine` **没有定义 `__eq__`**，会退化成
    身份比较，两个配置相同、各自新建的 Engine 永远"不相等"。反过来也不能一律用
    `repr`：`sessionmaker` 的 repr 里有内存地址。

    所以按语义分流：类型自己定义了 `__eq__`（str/int/dataclass/...）就用 `==`；
    只有默认身份相等的对象（Engine 这类）才退到 repr，并把地址抹掉。
    """
    if type(a) is not type(b):
        return False
    if getattr(type(a), "__eq__", object.__eq__) is not object.__eq__:
        return a == b
    return _ADDRESS.sub("0x?", repr(a)) == _ADDRESS.sub("0x?", repr(b))


def _source_of(obj) -> str | None:
    try:
        return re.sub(r"\s+", " ", inspect.getsource(obj)).strip()
    except (OSError, TypeError):
        return None


def compare(old, new, only: str | None, moved_to=None) -> list[str]:
    problems: list[str] = []

    old_names = {n for n in dir(old) if not n.startswith("_")}
    new_names = {n for n in dir(new) if not n.startswith("_")}
    for name in sorted(old_names - new_names):
        if moved_to is not None and hasattr(moved_to, name):
            # 名字离开了本模块，但确实在指定模块里——不比对对象本身：
            # 两个模块各自定义的同名类本来就是不同的类对象，该比的是**结构**，
            # 那由 schema_snapshot.py 负责。这里只确认"没丢"。
            continue
        problems.append(f"搬迁后**丢失**了公开名字：{name}")
    for name in sorted(new_names - old_names):
        problems.append(f"搬迁后**新增**了公开名字：{name}（若非有意，需说明）")

    for name in sorted(old_names & new_names):
        a, b = getattr(old, name), getattr(new, name)
        if isinstance(a, type) and isinstance(b, type):
            if _source_of(a) != _source_of(b):
                problems.append(f"{name}：类的源码文本不同")
            continue
        if callable(a) and callable(b):
            if _source_of(a) != _source_of(b):
                problems.append(f"{name}：函数的源码文本不同")
            continue

        fa, fb = {}, {}
        flatten(name, a, fa)
        flatten(name, b, fb)
        for key in sorted(set(fa) | set(fb)):
            if only and not key.startswith(only):
                continue
            if not _values_equal(fa.get(key), fb.get(key)):
                problems.append(
                    f"{key}：\n      搬迁前: {_show(key, fa.get(key))}"
                    f"\n      搬迁后: {_show(key, fb.get(key))}"
                )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old-file", required=True, help="搬迁前的 .py 文件路径")
    ap.add_argument("--old-name", default="module_before_move",
                    help="加载旧文件时使用的临时模块名")
    ap.add_argument("--new-module", required=True, help="搬迁后的模块（点号路径）")
    ap.add_argument("--only", default=None, help="只比对字段路径以此开头的项")
    ap.add_argument("--allow-moved-to", default=None, metavar="MODULE",
                    help="本模块里少掉的名字，若存在于该模块则视为「搬走了」而非丢失")
    args = ap.parse_args()

    old = load_from_file(args.old_name, args.old_file)
    new = importlib.import_module(args.new_module)
    moved_to = importlib.import_module(args.allow_moved_to) if args.allow_moved_to else None

    problems = compare(old, new, args.only, moved_to)
    if problems:
        print(f"比对未通过，{len(problems)} 处：")
        for p in problems:
            print("  -", p)
        return 1
    print(f"比对通过：{args.old_name} 与 {args.new_module} 的公开接口逐项一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
