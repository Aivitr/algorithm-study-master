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
`server.py` 被拆成 13 个路由模块（按业务域，不按 URL 前缀）。
拆分过程中每个 `@app.post(...)` 装饰器都要挪一次位置，**地址字符串就在那行里**。
改错一个字符的前缀（`/api/` 写成 `/apis/`），应用照样能启动、绝大多数测试照样能过，
但 nginx 的反代会当场 404——线上表现为"整个功能消失"。

正因如此，「路由前缀契约……必须在测试中断言」。
本文件即该项。

59 这个数字
-----------
接口契约冻结的是「59 个接口」。实测枚举得 **56 条 HTTP + 3 条 WebSocket = 59**，
与 `docs/route-inventory.md` 一致。其余 5 条（`/storage` 挂载、`/docs`、
`/openapi.json`、`/redoc`、`/docs/oauth2-redirect`）是框架自带的，不计入 59，
但同样需要钉住——重构时误删 `app.mount("/storage", ...)` 会让所有 OSS 素材 404。
"""

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount, WebSocketRoute

# nginx 硬编码的前缀。生产 nginx 配置按这三个前缀做反代，
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


def _leaf_routes(routes):
    """展开路由树，产出 `(真实路由对象, 生效路径, 生效方法集)`。

    为什么不能只遍历 `app.routes`
    -----------------------------
    FastAPI 0.141 起，`include_router()` **不再把子路由摊平**进 `app.routes`，
    而是放一个 `_IncludedRouter` 惰性节点（本仓库当前的顶层构成实测为：
    49 个 APIRoute + 4 个 Route + 3 个 APIWebSocketRoute + 1 个 Mount
    + 1 个 `_IncludedRouter`）。

    于是"把声纹路由拆进 app/routers/voiceprint.py"这个纯结构改动，会让那 7 条
    路由从 `app.routes` 的平铺视图里**整体消失**——本契约会误报"路由被删"，
    而它们其实好好的（OpenAPI schema 里 7 条全在）。这正是本文件要防的那类
    故障的反面：不是路由没了，是**看路由的方式过期了**。

    这里改跟 FastAPI 自己的视图走：`effective_route_contexts()` 是它做路由匹配
    时实际使用的展开结果，**已把前缀合进去**。两个字段的坑（实测）：

        APIRoute  : ctx.path 是对的，ctx.starlette_route 为 None
        WS/Route  : ctx.path 是空串，路径在 ctx.starlette_route.path 上

    因此按 `starlette_route.path → ctx.path → original_route.path` 依次取。
    """
    for route in routes:
        expand = getattr(route, "effective_route_contexts", None)
        if callable(expand):
            for ctx in expand():
                path = (
                    getattr(ctx.starlette_route, "path", None)
                    or getattr(ctx, "path", "")
                    or getattr(ctx.original_route, "path", "")
                )
                methods = getattr(ctx, "methods", None) or getattr(
                    ctx.original_route, "methods", set()
                )
                yield ctx.original_route, path, methods
        else:
            yield route, getattr(route, "path", "?"), getattr(route, "methods", set())


def _enumerate(app):
    """把 `app.routes` 压成可稳定比对的 (kind, methods, path) 三元组集合。

    `HEAD` 从方法里剔除：FastAPI 在某些声明下会自动补上它，属于框架行为而非
    本项目的接口契约，纳入比对会引入与重构无关的噪声。
    """
    rows = set()
    for route, path, methods in _leaf_routes(app.routes):
        if isinstance(route, APIRoute):
            rows.add(("HTTP", ",".join(sorted(set(methods) - {"HEAD"})), path))
        elif isinstance(route, WebSocketRoute):
            rows.add(("WS", "", path))
        elif isinstance(route, Mount):
            rows.add(("MOUNT", "", path))
        else:
            rows.add((type(route).__name__, "", path))
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

# 框架自带（不计入冻结的 59，但误删同样是故障）
FRAMEWORK_ROUTES = [
    ("Route", "", "/docs"),
    ("Route", "", "/docs/oauth2-redirect"),
    ("Route", "", "/openapi.json"),
    ("Route", "", "/redoc"),
    ("MOUNT", "", "/storage"),
    # 阶段 6：本地化的前端资源。误删它不会让 /api 出错，而是让页面**白屏**——
    # 与 /storage 同属"删了照样能启动、测试不红就没人发现"的那一类。
    ("MOUNT", "", "/static"),
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
    """契约冻结的「59 个接口」= 56 条 HTTP + 3 条 WebSocket。

    这条断言把冻结的数字与契约表本身绑在一起：若有人往契约表里加/删一条业务
    路由，这里会先失败，逼他确认"59"这个对外承诺是否也要改。
    """
    assert len(HTTP_ROUTES) + len(WS_ROUTES) == 59, (
        f"契约冻结 59 个接口，当前契约表有 {len(HTTP_ROUTES)} HTTP + "
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


def test_enumeration_agrees_with_openapi(actual_routes, local_app):
    """独立第二视角：枚举出的 HTTP 路由必须与 OpenAPI schema 逐条一致。

    为什么需要这条
    --------------
    上一条断言的全部力量，都建立在"`_enumerate()` 能看见所有路由"之上。
    而 `_enumerate()` 读的是 `app.routes` 与 FastAPI 的私有展开结构——**若哪天
    它读漏了，被漏掉的路由就从断言里静默消失，契约退化成一条永远绿的测试**。
    本仓库反复出现的就是这类失效（守卫本身坏掉却不出声）。

    OpenAPI schema 由 FastAPI 独立生成，不经过本文件的任何代码。两个视角一致，
    才说明枚举器没有漏读：

        app.routes + 私有展开  ←→  app.openapi()["paths"]

    （WebSocket 与 Mount 不在 schema 里，故只比 HTTP 这一面。）
    """
    schema = local_app.openapi()
    from_schema = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
    }
    from_routes = {(m, p) for kind, m, p in actual_routes if kind == "HTTP"}

    only_schema = from_schema - from_routes
    only_routes = from_routes - from_schema

    assert not only_schema and not only_routes, (
        "两个独立视角给出的 HTTP 路由不一致——枚举器可能读漏了路由树。\n"
        f"  只在 OpenAPI 中：{sorted(only_schema)}\n"
        f"  只在路由树中：{sorted(only_routes)}\n"
        "若这是「路由设了 include_in_schema=False」，请在此显式登记；\n"
        "若是枚举器的问题，那它会静默削弱上一条断言的力量。"
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
        f"该前缀消失等于线上对应功能整体 404。"
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
