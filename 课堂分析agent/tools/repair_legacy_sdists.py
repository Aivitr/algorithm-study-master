# -*- coding: utf-8 -*-
"""修复 pip 对若干旧源码包的错误构建（重建 venv 后可重复执行）。

背景：oss2 / jieba / agora-token-builder / python-speech-features 的 sdist 在
新版 setuptools 下构建出的 wheel 不含实际模块文件，只剩 dist-info；crcmod 1.7
依赖构建期 2to3 转换，新版 setuptools 不再执行，导致 Python 2 语法残留。

用法（仓库根目录）：
    venv\\Scripts\\python.exe tools\\repair_legacy_sdists.py
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

SITE = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(
    subprocess.check_output(
        [sys.executable, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        text=True,
    ).strip()
)

PACKAGES = [
    ("oss2==2.19.1", "oss2"),
    ("jieba==0.42.1", "jieba"),
    ("crcmod==1.7", "crcmod"),
    ("agora-token-builder==1.0.0", "agora_token_builder"),
    ("python-speech-features==0.6", "python_speech_features"),
]


def extract(archive: pathlib.Path, dest: pathlib.Path) -> None:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(archive) as tf:
            try:
                tf.extractall(dest, filter="data")
            except TypeError:
                tf.extractall(dest)


def copy_package(spec: str, target: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "download", "--no-deps", "--no-binary", ":all:",
             "-d", str(tmp_path), spec]
        )
        archive = next(p for p in tmp_path.iterdir() if p.suffix in {".gz", ".zip"})
        unpacked = tmp_path / "unpacked"
        unpacked.mkdir()
        extract(archive, unpacked)
        found = next((p for p in unpacked.rglob(target) if p.name == target), None)
        if found is None:
            raise RuntimeError("源码包里找不到 %s" % target)
        destination = SITE / found.name
        if found.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(found, destination)
        else:
            shutil.copy2(found, destination)
    print("已补齐 %s" % target)


def patch_crcmod() -> None:
    package = SITE / "crcmod"
    if not package.exists():
        return

    for name in ("crcmod.py", "_crcfunpy.py", "predefined.py"):
        path = package / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"\b(\d+)L\b", r"\1", text)
        text = re.sub(r"0x([0-9A-Fa-f]+)L", r"0x\1", text)
        text = text.replace("ord(x)", "x")
        text = re.sub(r"\blong\(", "int(", text)
        text = re.sub(r"\bxrange\(", "range(", text)
        text = re.sub(r"\bbasestring\b", "str", text)
        text = text.replace("sys.maxint", "sys.maxsize")
        text = text.replace("import _crcfunext as _crcfun", "from . import _crcfunext as _crcfun")
        text = text.replace("import _crcfunpy as _crcfun", "from . import _crcfunpy as _crcfun")
        path.write_text(text, encoding="utf-8", newline="\n")

    (package / "__init__.py").write_text(
        "from crcmod.crcmod import *\nimport crcmod.predefined\n__doc__ = crcmod.__doc__\n",
        encoding="utf-8",
        newline="\n",
    )
    print("已修补 crcmod 的 Python 3 兼容性")


for spec, target in PACKAGES:
    copy_package(spec, target)
patch_crcmod()

import crcmod  # noqa: E402
import jieba  # noqa: E402
import oss2  # noqa: E402

check = crcmod.Crc(0x142F0E1EBA9EA3693, initCrc=0, rev=False, xorOut=0)
check.update(b"123456789")
assert check.crcValue == 0x6C40DF5F0B497347
print("校验通过：oss2 %s / jieba %s / crcmod ECMA-182" % (oss2.__version__, jieba.__version__))
