"""路由行为基线（golden master）。

目的：把「重构不改变行为」从一句承诺变成可自动验证的事实。
方式：在本地库 + 合成数据上遍历路由，记录响应签名；重构后重新比对。

覆盖范围：仅**纯本地且只读**的路由。
  - 会打外部服务的路由不在此列（LLM / OSS / Agora / ASR / 声纹）——见
    docs/route-inventory.md
  - **写操作路由也不在此列**：它们会改变库状态，不属于"行为不变"的验证对象，
    且顺序耦合会让基线不稳定
  - `/api/register`、`/api/login` 为**覆盖盲区**：它们绕过 ORM 直连 MSSQL，
    无法在本地库上运行（见 `docs/route-inventory.md` 的「已知盲区」）
  - **唯一的例外**：`GET /api/download-exercises/1` 会往 `storage/exercises/`
    落一个文件（见 `WRITES_A_FILE`）。它**不写库**，所以签名稳定、可以进基线；
    但"只读"这个说法对它不准确。基线遍历结束后会把**本次新产生的**删掉。
    2026-10-01 之前这件事没做，该目录已经攒了 200 多个文件。

记录：`pytest --record-baseline` 重新录制；默认与已录基线比对。
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from fixtures import BASE_TIME

BASELINE_FILE = Path(__file__).resolve().parent / "baselines" / "routes.json"

# `/api/snapshot` 与 `/api/get-video-context` 用 `datetime.fromtimestamp()` 把入参按
# **本地时区**还原成时刻，再去 `EmotionLog.created_at` 的 ±N 秒窗口里查。
# 因此时间戳不能硬编码——从 BASE_TIME 反推，才能保证任何时区下都落在同一条记录上。
_TS_SECONDS = int(BASE_TIME.timestamp())
_TS_MILLIS = _TS_SECONDS * 1000

# 纯本地、只读的路由（ID 取自 fixtures.py 的固定约定）
READ_ONLY_ROUTES = [
    ("GET", "/", {}),
    ("GET", "/pcm-processor.js", {}),
    ("GET", "/api/meeting/1", {}),
    ("GET", "/api/transcripts/1", {}),
    ("GET", "/api/knowledge-graph/1", {}),
    ("GET", "/api/reports/2", {}),
    ("GET", "/api/meeting-reports/1", {}),
    ("GET", "/api/exercises/1", {}),
    ("GET", "/api/class-history/2", {}),
    ("GET", "/api/student-home-stats/2", {}),
    ("GET", "/api/active-groups/1", {}),
    ("GET", "/api/realtime-stats/1", {}),
    # minutes 默认 15，会把 2026-01-01 的合成数据按"最近15分钟"滤空；
    # 0 = 整节课，才会走到聚合分支
    ("GET", "/api/emotion-details/1", {"minutes": 0}),
    # 以下三条需要必填参数，缺参数只会得到 422
    ("GET", "/api/snapshot/1", {"username": "李同学", "timestamp": _TS_MILLIS}),
    ("GET", "/api/get-video-context", {
        "meeting_id": 1, "timestamp": _TS_SECONDS, "user_id": 2,
    }),
    # ⚠ 这一条**会写文件**，是 `READ_ONLY_ROUTES` 里唯一的例外。
    # 处理器每次调用都往 storage/exercises/ 落一个 `exercises_{id}_{时间戳}.txt`
    # 且从不清理（app/routers/quiz.py:50-55）。不写库 ⇒ 签名稳定 ⇒ 可进基线；
    # 但"只读"对它不准确。遍历结束后由 _cleanup_new_exercise_files() 收尾。
    # 不改处理器本身：它每次生成新文件名，很可能是**故意的**（避免覆盖上一次导出）。
    ("GET", "/api/download-exercises/1", {}),
    ("GET", "/api/student-quiz-history/2", {}),
    ("GET", "/api/teacher-templates/1", {}),
    ("GET", "/api/teacher-stats/1", {}),
    ("GET", "/api/teacher-classes/1", {}),
    ("GET", "/api/class-groups/1", {}),
    ("GET", "/api/all-student-reports/1", {}),
    # --- 以下三条经实测判定可纳入（见 docs/route-inventory.md 判定流程）---
    # 本地读进程内运行时状态；副作用仅是按需创建 storage/ 下的目录（该目录已被 gitignore）
    ("GET", "/api/research-runtime", {}),
    ("GET", "/api/voiceprint/status/李同学", {}),
    ("GET", "/api/voiceprint/users", {}),
]
# 刻意**不**纳入基线、但容易被误加的两条：
#   /summary            —— 处理器内调用 LLM（实测外连 116.196.150.245:443，被 socket 兜底拦下 8 次）
#   /api/agora-token    —— 响应取自 .env 中的 AGORA_* 配置；若该机配齐凭据，则响应含带时效的
#                          Token 且每次不同。既不可复现，也会把凭据写进随仓库提交的基线文件。
#                          本机只是恰好缺 AGORA_APP_CERTIFICATE 才显得"确定"，不能依赖。


def _signature(response) -> dict:
    """把响应压成可稳定比对的签名。"""
    body = response.content
    ctype = response.headers.get("content-type", "").split(";")[0]
    sig = {
        "status": response.status_code,
        "content_type": ctype,
        "length": len(body),
    }
    # JSON 响应再取一次结构摘要（键集合 + 顶层类型），比长度更能反映形状变化
    if ctype == "application/json":
        try:
            data = response.json()
            sig["shape"] = _json_shape(data)
        except Exception:
            sig["shape"] = "<unparseable>"
    sig["digest"] = hashlib.sha256(body).hexdigest()[:16]
    return sig


def _json_shape(data, depth=0):
    """结构摘要：只保留类型骨架，丢弃具体取值（避免时间戳等易变内容）。"""
    if depth > 4:
        return "..."
    if isinstance(data, dict):
        return {k: _json_shape(v, depth + 1) for k, v in sorted(data.items())}
    if isinstance(data, list):
        return [f"list[{len(data)}]", _json_shape(data[0], depth + 1) if data else None]
    if data is None:
        return "null"
    return type(data).__name__


_EXERCISE_DIR = Path(__file__).resolve().parent.parent / "storage" / "exercises"


def _exercise_files() -> set[Path]:
    if not _EXERCISE_DIR.is_dir():
        return set()
    return set(_EXERCISE_DIR.glob("exercises_*.txt"))


def _cleanup_new_exercise_files(before: set[Path]) -> None:
    """删掉**本次遍历新产生**的导出文件。

    按"遍历前就有的"做差集，所以不可能碰到任何一个**先前已存在**的文件——
    包括那 200 多个历史遗留。
    """
    for path in _exercise_files() - before:
        try:
            path.unlink()
        except OSError:
            pass


# 遍历前后的目录快照。收尾是否真的生效由它裁决。
_BASELINE_RUN: dict[str, set[str]] = {}


@pytest.fixture(scope="session")
def raw_responses(client, seeded_ids):
    """遍历只读路由，保留原始响应（签名与凭据检查都从它派生）。

    收尾用 `finally`：`WRITES_A_FILE` 那条即使中途抛错，也不该把文件留在盘上。
    """
    result = {}
    before = _exercise_files()
    try:
        for method, path, params in READ_ONLY_ROUTES:
            response = client.request(method, path, **({"params": params} if params else {}))
            result[f"{method} {path}"] = response
    finally:
        _cleanup_new_exercise_files(before)
        # 快照放在**收尾之后**：这样"清理没生效"与"清理函数根本没动手"
        # 都会被下面那条断言一起抓到。
        # 判据取"遍历前后是否一致"，而不是"有没有删不掉的文件"——
        # 后者有个洞：清理函数若什么都不做，它同样返回空，照样绿。
        _BASELINE_RUN["before"] = {p.name for p in before}
        _BASELINE_RUN["after"] = {p.name for p in _exercise_files()}
    return result


def test_baseline_run_leaves_no_export_files_behind(raw_responses):
    """跑一遍基线不该在仓库里留下导出文件：遍历前后目录必须一模一样。

    依赖 `raw_responses` 只为保证顺序——得等那次遍历跑完再看。

    背景：`GET /api/download-exercises/1` 每次调用都往
    `storage/exercises/` 落一个文件且从不清理，而它被列在 `READ_ONLY_ROUTES`
    里。2026-10-01 之前这件事没人管，该目录攒了 234 个文件（几乎全由测试产生，
    当天一天就长了约 200 个）。现在遍历结束即收尾，由本断言盯着收尾是否生效。
    """
    before = _BASELINE_RUN.get("before")
    after = _BASELINE_RUN.get("after")
    assert before is not None and after is not None, (
        "没取到遍历前后的快照——`raw_responses` 没跑到收尾就被丢弃了。"
    )

    assert after == before, (
        f"基线遍历前后 {_EXERCISE_DIR} 变了：\n"
        f"  新增：{sorted(after - before)}\n"
        f"  减少：{sorted(before - after)}\n"
        "（新增说明收尾没生效；减少说明清理**删过头**了，碰到了遍历前就存在的文件。）"
    )


@pytest.fixture(scope="session")
def current_baseline(raw_responses):
    """当前行为签名。"""
    return {key: _signature(r) for key, r in raw_responses.items()}


_SECRET_KEY = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CERT)", re.I)


def _env_secrets() -> dict:
    """从仓库根的 .env 里取出疑似凭据的键值（只读键名与取值，用于比对）。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return {}

    secrets = {}
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # 短值容易与正常内容偶合，不参与比对
        if value and len(value) >= 8 and _SECRET_KEY.search(key):
            secrets[key] = value
    return secrets


def test_responses_do_not_leak_env_secrets(raw_responses):
    """基线文件是要提交进仓库的，响应里绝不能夹带 .env 中的凭据。

    背景：`/api/agora-token` 的响应取自 `.env` 的 `AGORA_*`。本机恰好缺
    `AGORA_APP_CERTIFICATE`，它才显得确定；若在凭据配齐的机器上录制，基线里
    就会落进一个带时效的真实 Token。该路由已排除，这条断言防止同类路由再被误加。

    注意：socket 兜底只拦网络，拦不住"把凭据读出来写进响应"。
    """
    secrets = _env_secrets()
    if not secrets:
        pytest.skip("未找到 .env 或其中无可用凭据样本")

    leaks = []
    for key, response in raw_responses.items():
        body = response.content.decode("utf-8", errors="replace")
        for env_key, value in secrets.items():
            if value in body:
                leaks.append(f"{key} 的响应中出现了 {env_key} 的取值")

    assert not leaks, "基线响应疑似泄露 .env 凭据：\n  " + "\n  ".join(sorted(leaks))


def test_route_baseline(request, current_baseline):
    """当前行为应与已录基线一致；`--record-baseline` 时录制。"""
    if request.config.getoption("--record-baseline"):
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(
            json.dumps(current_baseline, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
            # 必须是纯 LF。`Path.write_text` 默认做平台换行转换，在 Windows 上写出
            # 的就是 CRLF；入库时被 `.gitattributes` 归一成 LF，于是**每次在
            # Windows 上重录都会留下一条纯换行的假 diff**。
            # 假 diff 本身无害，有害的是它让"重录一次、看仓库有没有变"这个自证
            # 手法失效，而且失效得悄无声息。`static/vendor/SOURCES.json` 吃过
            # 同一个亏（见 test_frontend_assets.py::test_manifest_is_lf_only）。
            newline="\n",
        )
        pytest.skip(f"已重新录制基线：{BASELINE_FILE}")

    if not BASELINE_FILE.exists():
        pytest.fail(
            f"基线文件不存在：{BASELINE_FILE}\n"
            f"先以 `pytest --record-baseline` 录制一次。"
        )

    recorded = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

    missing = set(recorded) - set(current_baseline)
    added = set(current_baseline) - set(recorded)
    assert not missing, f"基线中存在但当前未覆盖的路由：{sorted(missing)}"
    assert not added, f"新增了未录基线的路由：{sorted(added)}"

    diffs = {
        key: {"recorded": recorded[key], "current": current_baseline[key]}
        for key in recorded
        if recorded[key] != current_baseline[key]
    }
    assert not diffs, "路由行为与基线不一致：\n" + json.dumps(
        diffs, ensure_ascii=False, indent=2
    )


def test_baseline_is_lf_only():
    """基线必须是纯 LF —— 它的**自证方式**依赖这一点。

    本仓库用"重录一次，看仓库有没有变"来证明基线是算出来的、不是手抄的。
    而 `Path.write_text` 默认做平台换行转换：在 Windows 上录出的是 CRLF，
    入库时被 `.gitattributes` 的 `* text=auto eol=lf` 归一成 LF，于是
    **每次在 Windows 上重录都会留下一条纯换行的假 diff**。

    假 diff 本身无害，有害的是它让上面那个自证手法失效，且失效得悄无声息。
    `static/vendor/SOURCES.json` 已经吃过一次这个亏
    （见 `test_frontend_assets.py::test_manifest_is_lf_only`），这里是同一个坑的
    第二处——2026-10 做 ②b 组件拆分时重录 `GET /` 才被 CRLF 警告带出来。
    """
    raw = BASELINE_FILE.read_bytes()
    assert b"\r" not in raw, (
        f"{BASELINE_FILE.name} 里出现了 CR（{raw.count(b'\\r')} 个）。"
        f"录制处的 write_text 需要 newline=\"\\n\"。"
    )
