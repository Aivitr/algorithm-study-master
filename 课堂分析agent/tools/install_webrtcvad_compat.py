# -*- coding: utf-8 -*-
"""在 Windows 无 MSVC 的环境中安装 webrtcvad 兼容实现。

背景：webrtcvad==2.0.10 只发布源码包，安装时需要 MSVC 编译 `_webrtcvad`。
webrtcvad-wheels 提供同一模块（webrtcvad.py + _webrtcvad.pyd）的预编译 wheel，
但发行名不同，pip 不会用它满足 resemblyzer 的 `webrtcvad>=2.0.10` 依赖。

本脚本做两件事：
1. 安装 webrtcvad-wheels（提供可导入的 webrtcvad 模块）；
2. 写入一个最小的 webrtcvad-2.0.10.dist-info，使依赖判断成立。

用法（在仓库根目录执行）：
    venv\\Scripts\\python.exe tools\\install_webrtcvad_compat.py
"""

from __future__ import annotations

import importlib.metadata as metadata
import pathlib
import subprocess
import sys
import tempfile

COMPAT_VERSION = "2.0.14.post1"
DECLARED_VERSION = "2.0.10"


def dist_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def main() -> int:
    if dist_version("webrtcvad") == DECLARED_VERSION:
        import webrtcvad  # noqa: F401

        print("webrtcvad %s 已就绪（兼容实现）" % DECLARED_VERSION)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "download", "--no-deps", "-d", tmp,
             "webrtcvad-wheels==" + COMPAT_VERSION]
        )
        wheel = next(pathlib.Path(tmp).glob("webrtcvad_wheels-*.whl"))
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-deps", str(wheel)])

    site = pathlib.Path(
        subprocess.check_output(
            [sys.executable, "-c", "import site; print(site.getsitepackages()[0])"],
            text=True,
        ).strip()
    )
    info = site / ("webrtcvad-%s.dist-info" % DECLARED_VERSION)
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: webrtcvad\n"
        "Version: %s\n"
        "Summary: WebRTC VAD, provided by webrtcvad-wheels compatibility build\n"
        % DECLARED_VERSION,
        encoding="utf-8",
    )
    (info / "INSTALLER").write_text("webrtcvad-wheels compatibility\n", encoding="utf-8")
    (info / "RECORD").write_text("", encoding="utf-8")

    import webrtcvad

    vad = webrtcvad.Vad(3)
    vad.is_speech(b"\x00\x00" * 480, 16000)
    print("webrtcvad %s 兼容实现安装完成" % DECLARED_VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
