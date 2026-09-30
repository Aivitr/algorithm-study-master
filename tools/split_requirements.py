"""把 requirements.txt 按「是否需要从 PyTorch CPU 索引安装」切成两份。

为什么需要它
------------
镜像分两层装依赖：

  1. torch / torchvision / torchaudio ← 必须走 `--index-url .../whl/cpu`
  2. 其余全部                        ← 走普通 PyPI

第 1 条不是优化，是**正确性**：在 Linux 上，`pip install torch` 默认拉的是
CUDA 版，连同十余个 nvidia-* 运行时库，镜像凭空涨到好几 GB——而这台机器
没有 GPU，装了也只用 CPU 版。Windows 上恰好默认就是 CPU 版，所以在开发机
的 venv 里看不出这个问题，只有容器里才会暴露。

第 2 条必须在第 1 条**之后**装：`insightface`、`pyannote.audio`、`resemblyzer`
在安装期就要 import torch。

为什么不另立一份清单
--------------------
最省事的写法是在 Dockerfile 里抄一份 torch 三件套的名单。那样就有了**两处定义**，
而本仓库吃过太多次这个亏（见 `app/core/oss.py` 的文件头）：两份清单不会同时改，
分叉后不报错，只表现为"某个包里装着两个版本的 torch"或"某个包莫名没装"。

所以这里从 requirements.txt **现算**，只有 `HEAVY_PACKAGES` 这一处是"知识"，
且 `tests_safe/test_docker_assets.py` 会断言它声明的每一个包都**真的**在
requirements.txt 里——名单一旦过期，测试红，而不是静默漏装。

用法
----
    python tools/split_requirements.py requirements.txt /tmp/heavy.txt /tmp/light.txt
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


def package_name(line: str) -> str:
    """从一行 requirement 里取出包名（小写，去掉 extras 与版本约束）。

    不是一行 requirement 时返回空串——调用方据此跳过注释与空行。
    """
    if not line.strip() or line.lstrip().startswith("#"):
        return ""
    match = _NAME_RE.match(line)
    return match.group(1).lower() if match else ""


def split_requirements(source: str) -> tuple[list[str], list[str]]:
    """切成 `(heavy, light)`。

    两份合起来是原文条的**划分**：每一项恰好落到一边，且各自保持原文顺序。
    注释与空行不进任何一边（它们没有安装语义，跟着走只会让两边的 diff 变脏）。
    这一点由 `tests_safe/test_docker_assets.py` 钉住。
    """
    heavy_names = set(HEAVY_PACKAGES)
    heavy: list[str] = []
    light: list[str] = []

    for raw in source.splitlines():
        name = package_name(raw)
        if not name:
            continue
        (heavy if name in heavy_names else light).append(raw.strip())

    return heavy, light


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="requirements.txt 的路径")
    parser.add_argument("heavy_out", type=Path, help="torch 三件套写到哪")
    parser.add_argument("light_out", type=Path, help="其余依赖写到哪")
    args = parser.parse_args()

    try:
        source = args.source.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"读不到 {args.source}：{exc}", file=sys.stderr)
        return 1

    heavy, light = split_requirements(source)
    if not heavy:
        # 空的重型层也算"成功"，但几乎肯定是 HEAVY_PACKAGES 与 requirements.txt
        # 对不上了——那时镜像会在 Linux 上悄悄装成 CUDA 版。出声。
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
