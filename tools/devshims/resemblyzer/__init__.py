"""本地开发用的 resemblyzer 占位实现（无 torch / 无预训练权重时的导入替身）。

仓库里 `app/services/voiceprint_manager.py` 在**模块导入期**就构造
`VoiceEncoder()`，而真身 resemblyzer 会连带拉 torch（Windows 轮子近 1GB）+
下载预训练权重。本地只跑页面与 GCA/Agent 链路时不需要声纹，所以用本占位包
让导入通过；真的调用声纹接口时抛错，而不是静默给出假结果。

放在 sys.path 里由 tools/dev_server.py 注入，不装进 site-packages——
真实部署走 requirements.txt 装官方 resemblyzer，这个文件不参与。
"""


class VoiceEncoder:
    """占位编码器：构造可用，取证时明确报错。"""

    def __init__(self, *args, **kwargs):
        self._placeholder = True

    def _unavailable(self, *args, **kwargs):
        raise RuntimeError(
            "resemblyzer 未安装（tools/devshims 占位）：声纹识别在本地开发模式下不可用。"
            "需要该能力时按 requirements.txt 安装官方 resemblyzer 与 torch。"
        )

    def embed_utterance(self, *args, **kwargs):
        return self._unavailable()

    def embed_speaker(self, *args, **kwargs):
        return self._unavailable()

    def embed_utterances(self, *args, **kwargs):
        return self._unavailable()


def preprocess_wav(*args, **kwargs):
    raise RuntimeError(
        "resemblyzer.preprocess_wav 不可用（tools/devshims 占位）：请安装官方 resemblyzer。"
    )
