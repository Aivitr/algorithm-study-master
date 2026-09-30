"""路由表契约：地址与方法的**集合**必须逐字节不变。

与 `test_route_baseline.py` 的分工
----------------------------------
两者防的是不同的东西，缺一不可：

| | 基线（baselines/routes.json） | 本文件（契约） |
|---|---|---|
| 对象 | 响应的**内容**（状态码、长度、结构摘要） | 路由的**存在与地址** |
| 手段 | 发请求、比对摘要 | 直接读 `app.routes`，不发请求 |
| 覆盖 | 只覆盖只读路由（写路由会改库） | **全部 64 条**，写路由也覆盖 |

基线只能够到"能被安全调用"的那部分路由——写路由、要外部服务的路由全都够不着。
而**路由被搬走或改地址**这件事，恰恰最容易发生在那些够不着的路由身上（例如
`/api/register`、`/api/cast-vote` 这类没有基线的）。本文件把它们全钉住。

为什么阶段 3 必须先有它
----------------------
设计文档 §4.1 要求把 `server.py` 拆成 13 个路由模块（按业务域，不按 URL 前缀）。
拆分过程中每个 `@app.post(...)` 装饰器都要挪一次位置，**地址字符串就在那行里**。
改错一个字符的前缀（`/api/` 写成 `/apis/`），应用照样能启动、绝大多数测试照样能过，
但 nginx 的反代会当场 404——线上表现为"整个功能消失"。

设计文档 §4.1 因此明确要求：「路由前缀契约……必须在测试中断言」。
本文件即该项。

59 这个数字
-----------
C3 冻结的是「59 个接口」。实测枚举得 **56 条 HTTP + 3 条 WebSocket = 59**，
与 `docs/route-inventory.md` 一致。其余 5 条（`/storage` 挂载、`/docs`、
`/openapi.json`、`/redoc`、`/docs/oauth2-redirect`）是框架自带的，不计入 59，
但同样需要钉住——重构时误删 `app.mount("/storage", ...)` 会让所有 OSS 素材 404。
"""

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount, WebSocketRoute

# nginx 硬编码的前缀（设计文档 §4.1）。生产 nginx 配置按这三个前缀做反代，
# 仓库里没有它的副本，改了前缀在本地**测不出来**——只能靠这条契约挡。
NGINX_PREFIXES = (
    "/api/",
    "/ws/",
    "/ws-asr/",
    "/ws-signal/",
    # 挂载点是 `/storage`（不带尾斜杠），请求 `/storage/xxx` 由它承接。
    # 写 `/storage/` 会匹配不到这个 Mount 本身——这正是本测试首次运行时抓到的问题。
    "/storage",
)


def _enumerate(app):
    """把 `app.routes` 压成可稳定比对的 (kind, methods, path) 三元组集合。

    `HEAD` 从方法里剔除：FastAPI 在某些声明下会自动补上它，属于框架行为而非
    本项目的接口契约，纳入比对会引入与重构无关的噪声。
    """
    rows = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            rows.add(("HTTP", ",".join(sorted(route.methods - {"HEAD"})), route.path))
        elif isinstance(route, WebSocketRoute):
            rows.add(("WS", "", route.path))
        elif isinstance(route, Mount):
            rows.add(("MOUNT", "", route.path))
        else:
            rows.add((type(route).__name__, "", getattr(route, "path", "?")))
    return rows


# ---------------------------------------------------------------------------
# 契约本体。改动此列表 = 改动对外接口，必须是有意为之。
# ---------------------------------------------------------------------------
HTTP_ROUTES = [
    ("GET", "/"),
    ("GET", "/api/active-groups/{teacher_id}"),
    ("GET", "/api/agora-token"),
    ("POST", "/api/ai-tutor"),
    ("POST", "/api/ai-tutor-stream"),
    ("GET", "/api/all-student-reports/{teacher_id}"),
    ("POST", "/api/browser-asr-final"),
    ("POST", "/api/cast-vote"),
    ("POST", "/api/check-quiet-members"),
    ("POST", "/api/check-silence"),
    ("GET", "/api/class-groups/{meeting_id}"),
    ("GET", "/api/class-history/{user_id}"),
    ("POST", "/api/close-vote"),
    ("POST", "/api/cluster-viewpoints"),
    ("POST", "/api/confirm-vote"),
    ("DELETE", "/api/delete-template/{template_id}"),
    ("GET", "/api/download-exercises/{report_id}"),
    ("GET", "/api/emotion-details/{meeting_id}"),
    ("POST", "/api/end-class"),
    ("GET", "/api/exercises/{report_id}"),
    ("POST", "/api/generate-pdf-report"),
    ("POST", "/api/generate-report"),
    ("POST", "/api/generate-report-stream"),
    ("GET", "/api/get-video-context"),
    ("POST", "/api/grade-short-answer"),
    ("GET", "/api/knowledge-graph/{meeting_id}"),
    ("POST", "/api/login"),
    ("GET", "/api/meeting-reports/{meeting_id}"),
    ("GET", "/api/meeting/{meeting_id}"),
    ("POST", "/api/quick-decompose"),
    ("POST", "/api/quiz-error-analysis"),
    ("GET", "/api/realtime-stats/{meeting_id}"),
    ("POST", "/api/register"),
    ("GET", "/api/reports/{user_id}"),
    ("GET", "/api/research-runtime"),
    ("POST", "/api/research-runtime/config"),
    ("POST", "/api/research-runtime/prepare-layout"),
    ("GET", "/api/snapshot/{meeting_id}"),
    ("GET", "/api/student-home-stats/{user_id}"),
    ("GET", "/api/student-quiz-history/{user_id}"),
    ("POST", "/api/submit-answer"),
    ("POST", "/api/suggest-topic"),
    ("GET", "/api/teacher-classes/{teacher_id}"),
    ("GET", "/api/teacher-stats/{teacher_id}"),
    ("GET", "/api/teacher-templates/{teacher_id}"),
    ("GET", "/api/transcripts/{meeting_id}"),
    ("POST", "/api/voiceprint/identify"),
    ("POST", "/api/voiceprint/register"),
    ("GET", "/api/voiceprint/status/{username}"),
    ("DELETE", "/api/voiceprint/unregister/{username}"),
    ("GET", "/api/voiceprint/users"),
    ("POST", "/api/voiceprint/verify"),
    ("POST", "/login"),
    ("GET", "/pcm-processor.js"),
    ("GET", "/summary"),
    ("GET", "/voiceprint_register"),
]

WS_ROUTES = [
    "/ws-asr/{username}/{meeting_id}",
    "/ws-signal/{username}/{meeting_id}",
    "/ws/{username}/{meeting_id}",
]

# 框架自带（不计入 C3 的 59，但误删同样是故障）
FRAMEWORK_ROUTES = [
    ("Route", "", "/docs"),
    ("Route", "", "/docs/oauth2-redirect"),
    ("Route", "", "/openapi.json"),
    ("Route", "", "/redoc"),
    ("MOUNT", "", "/storage"),
]


def _contract() -> set:
    return (
        {("HTTP", m, p) for m, p in HTTP_ROUTES}
        | {("WS", "", p) for p in WS_ROUTES}
        | set(FRAMEWORK_ROUTES)
    )


@pytest.fixture(scope="session")
def actual_routes(local_app):
    return _enumerate(local_app)


def test_frozen_interface_count_is_59():
    """C3 冻结的「59 个接口」= 56 条 HTTP + 3 条 WebSocket。

    这条断言把 C3 的数字与契约表本身绑在一起：若有人往契约表里加/删一条业务
    路由，这里会先失败，逼他确认"59"这个对外承诺是否也要改。
    """
    assert len(HTTP_ROUTES) + len(WS_ROUTES) == 59, (
        f"C3 冻结 59 个接口，当前契约表有 {len(HTTP_ROUTES)} HTTP + "
        f"{len(WS_ROUTES)} WS = {len(HTTP_ROUTES) + len(WS_ROUTES)}"
    )


def test_route_table_matches_contract(actual_routes):
    """应用实际注册的路由表必须与契约**完全一致**（多一条、少一条、改一个字都不行）。"""
    expected = _contract()

    missing = expected - actual_routes
    added = actual_routes - expected

    def _fmt(rows):
        return "\n  ".join(
            f"{k:7} {m:12} {p}" for k, m, p in sorted(rows, key=lambda r: (r[2], r[0]))
        )

    problems = []
    if missing:
        problems.append(
            "契约中存在、但应用未注册（路由被删或地址被改）：\n  " + _fmt(missing)
        )
    if added:
        problems.append(
            "应用注册了、但契约中没有（新增或改址后未更新契约）：\n  " + _fmt(added)
        )

    assert not problems, (
        "路由表与契约不一致——这是对外接口变更，会直接打断 nginx 反代。\n\n"
        + "\n\n".join(problems)
    )


@pytest.mark.parametrize("prefix", NGINX_PREFIXES)
def test_nginx_prefixes_are_intact(actual_routes, prefix):
    """nginx 硬编码的每个前缀，都必须在实际路由中原样出现。

    与上一条的区别：上一条是"集合相等"，本参数化是**按前缀逐条点名**。若哪天
    集合整体被替换（例如全部路由被同时改到 `/apis/` 下），上一条会给出一个
    64 行的差异，而这一条会直接指出「`/api/` 前缀整个不见了」——定位成本差很多。
    """
    matched = [p for _, _, p in actual_routes if p.startswith(prefix)]
    assert matched, (
        f"前缀 {prefix!r} 下一条路由都没有。nginx 按此前缀反代，"
        f"该前缀消失等于线上对应功能整体 404（设计文档 §4.1）。"
    )


def test_top_level_routes_are_unchanged(actual_routes):
    """不在任何 nginx 前缀下的路由，只能是不带前缀的页面路由。

    这条限制"逃逸"：重构时若某条 `/api/foo` 被误改成 `/foo`，它会掉出所有
    nginx 前缀，被上一条漏掉；在这里则会以"多了一个顶层路径"的形式暴露。
    """
    allowed = {"/", "/login", "/summary", "/pcm-processor.js", "/voiceprint_register"}
    allowed |= {p for _, _, p in FRAMEWORK_ROUTES}

    # 单段路径（只有开头一个斜杠）即顶层路由
    top_level = {p for _, _, p in actual_routes if p.count("/") == 1}

    unexpected = top_level - allowed
    assert not unexpected, (
        f"出现了预期之外的顶层路由：{sorted(unexpected)}。"
        f"若这是有意新增的页面，请一并更新本测试与 nginx 配置。"
    )
