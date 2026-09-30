"""应用服务层（阶段 3.3 从仓库根搬入）。

**本文件刻意保持为空——不要在这里 re-export 任何子模块。**

原因不是风格洁癖，是导入时机
----------------------------
Python 在导入 `app.services.llm_service` 之前，**必定先执行本文件**。因此这里
每多一个 import，就等于给每一个子模块的导入都加上它——包括那些被**故意延迟**
到函数体里才导入的。

`server.py` 里有几处刻意的延迟导入，各有理由：

    server.py:152   from video_processor import VideoEmotionAnalyzer   # 首次用到才加载 cv2
    server.py:104   from oss_utils import get_oss_manager             # OSS 未配置时要能降级
    server.py:3410  from ai_core import RealtimeTranscriber           # 只在实时转写时加载

这些模块拖着 cv2、librosa、resemblyzer、oss2 等重依赖。若本文件把它们全导进来，
上面那几处延迟导入就全部失效——启动即加载全部重依赖，且其中任何一个装不上，
**整个应用起不来**，而不是"那个功能不可用"。

这条性质不会报错，只会让启动变慢、让可选依赖变成必需依赖，所以写在这里，
给下一个想"顺手补个 re-export 方便些"的人看。

需要整个服务集合的地方，请显式逐个导入。
"""
