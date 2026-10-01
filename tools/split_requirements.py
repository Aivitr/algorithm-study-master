"""把 requirements.txt 按「是否需要从 PyTorch CPU 索引安装」切成两份。

为什么需要它
------------
镜像分两层装依赖：

  1. torch / torchvision / torchaudio ← 必须走 `--index-url .../whl/cpu`
  2. 其余全部                        ← 走普通 PyPI

第 1 条不是优化，是**正确性**：在 Linux 上，`pip install torch` 默认拉的是
CUDA 版，连同十余个 nvidia-* 运行时库，镜像凭空涨到好几 GB——而这台机器
没有 GPU，装了也只用 CPU 版。

第 2 条必须在第 1 条**之后**装：`insightface`、`pyannote.audio`、`resemblyzer`
在安装期就要 import torch。

清单从 requirements.txt **现算**，不另立一份：只有 `HEAVY_PACKAGES` 这一处是
"知识"，且 `tests_safe/test_docker_assets.py` 会断言它声明的每一个包都**真的**在
requirements.txt 里——名单一旦过期，测试红，而不是静默漏装。

用法
----
    python tools/split_requirements.py requirements-dev.txt /tmp/heavy.txt /tmp/light.txt

开发镜像喂的是 `requirements-dev.txt`（测试工具也得有），它首行是
`-r requirements.txt`，所以本工具会**跟随 `-r` 引用**把被引用的清单展开进来。

跟随引用时只展开、**不把 `-r` 那一行本身当成包**（它没有包名）。不展开的话，
torch 会因为藏在被引用的文件里而整个漏掉——Linux 上就会装成 CUDA 版且不报错。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 走 PyTorch CPU 索引的三个包。三者版本必须彼此兼容（torchaudio/torchvision
# 都是按 torch 的版本配套发布的），所以要么一起走 CPU 索引，要么一起别走。
HEAVY_PACKAGES: tuple[str, ...] = ("torch", "torchvision", "torchaudio")

# `torch>=2.0`、`torch==2.14.0`、`uvicorn[standard]`、`setuptools<81` 都取主干名
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

# pip 的 -r / --requirement 引用
_INCLUDE_RE = re.compile(r"^\s*(?:-r|--requirement)[=\s]+(\S+)\s*$")


def package_name(line: str) -> str:
    """从一行 requirement 里取出包名（小写，去掉 extras 与版本约束）。

    不是一行 requirement 时返回空串——调用方据此跳过注释、空行与 `-r` 引用。
    """
    if not line.strip() or line.lstrip().startswith("#"):
        return ""
    match = _NAME_RE.match(line)
    return match.group(1).lower() if match else ""


def expand_requirements(source: str, base_dir: Path | None = None) -> list[str]:
    """展开 `-r` 引用，按顺序返回所有 requirement 行（注释与空行已剔除）。

    只做**一层层就地展开**，不重排：`-r requirements.txt` 出现在哪一行，
    被引用的内容就插在哪一行。`base_dir` 是被引用文件的相对基准目录。
    """
    base_dir = Path(".") if base_dir is None else base_dir
    return _expand(source, base_dir, seen=set())


def _expand(source: str, base_dir: Path, seen: set[Path]) -> list[str]:
    lines: list[str] = []
    for raw in source.splitlines():
        include = _INCLUDE_RE.match(raw)
        if include:
            target = (base_dir / include.group(1).strip()).resolve()
            if target in seen:
                continue  # 循环引用：跳过而不是递归到栈溢出
            seen.add(target)
            try:
                nested = target.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"警告：展开 {target} 失败（{exc}），该处引用被忽略", file=sys.stderr)
                continue
            lines.extend(_expand(nested, target.parent, seen))
            continue

        if package_name(raw):
            lines.append(raw.strip())
    return lines


def split_requirements(
    source: str, base_dir: Path | None = None
) -> tuple[list[str], list[str]]:
    """切成 `(heavy, light)`。

    `source` 可以含 `-r` 引用，会先展开（见 `expand_requirements`）。
    两份合起来是展开后清单的**划分**：每一项恰好落到一边，且各自保持原文顺序。
    注释与空行不进任何一边（它们没有安装语义，跟着走只会让两边的 diff 变脏）。
    这一点由 `tests_safe/test_docker_assets.py` 钉住。
    """
    heavy_names = set(HEAVY_PACKAGES)
    heavy: list[str] = []
    light: list[str] = []

    for line in expand_requirements(source, base_dir):
        name = package_name(line)
        (heavy if name in heavy_names else light).append(line)

    return heavy, light


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="requirements 清单的路径")
    parser.add_argument("heavy_out", type=Path, help="torch 三件套写到哪")
    parser.add_argument("light_out", type=Path, help="其余依赖写到哪")
    args = parser.parse_args()

    try:
        source = args.source.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"读不到 {args.source}：{exc}", file=sys.stderr)
        return 1

    heavy, light = split_requirements(source, args.source.parent)
    if not heavy:
        # 空的重型层也算"成功"，但几乎肯定是 HEAVY_PACKAGES 与 requirements.txt
        # 对不上了——那时 Linux 上会悄悄装成 CUDA 版。出声。
        print(
            f"警告：{args.source} 里一个 PyTorch 包都没找到，"
            f"但 HEAVY_PACKAGES 声明了 {HEAVY_PACKAGES}。请核对。",
            file=sys.stderr,
        )

    args.heavy_out.parent.mkdir(parents=True, exist_ok=True)
    args.light_out.parent.mkdir(parents=True, exist_ok=True)
    args.heavy_out.write_text("\n".join(heavy) + "\n", encoding="utf-8")
    args.light_out.write_text("\n".join(light) + "\n", encoding="utf-8")

    print(f"重型层 {len(heavy)} 项 → {args.heavy_out}")
    print(f"其余   {len(light)} 项 → {args.light_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
