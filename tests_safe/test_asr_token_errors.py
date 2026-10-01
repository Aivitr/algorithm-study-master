"""阿里云 NLS Token 拿不到时，必须把接口给出的**拒绝原因**打印出来。

背景：`refresh_aliyun_token()` 原来只写了成功
分支（`if 'Token' in d:`）。阿里云对 CreateToken 的拒绝是 HTTP 4xx 且**不带
Token 字段**的，于是函数静默落到末尾返回 None，调用方
`RealtimeTranscriber.start()` 只能报一句"无法获取阿里云Token"——
与真实病因无关。

第一次踩到时接口回的明明是
`InvalidAccessKeyId.Inactive / Specified access key is disabled.`，
容器日志里却一个字也没有（既没有 `[OK] 阿里云Token刷新成功`，也没有
`[ERROR] Token刷新失败`），排查只能靠进容器手工重发请求。

这一组测试**不联网**：`requests.get` 被换成假的响应对象。
"""

import pytest

import app.services.ai_core as ai_core

# 真实踩到的那次响应，原样留作样例（RequestId 换成了占位值）
ALIYUN_DISABLED_KEY_BODY = {
    "RequestId": "00000000-0000-0000-0000-000000000000",
    "Message": "Specified access key is disabled.",
    "Code": "InvalidAccessKeyId.Inactive",
    "HostId": "nls-meta.cn-shanghai.aliyuncs.com",
}

_OK_BODY = {
    "Token": {"Id": "fake-token-id", "ExpireTime": 4102444800},
    "RequestId": "00000000-0000-0000-0000-000000000001",
}


class _FakeResponse:
    """只实现被测代码真正用到的两个成员：`status_code` 与 `json()`。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.fixture
def fresh_token_cache(monkeypatch):
    """清掉模块级 Token 缓存。

    `refresh_aliyun_token` 用的是**模块级共享**的 `_shared_token` /
    `_shared_token_expire`，不清就会串味：上一个用例留下的 token 会让这一个
    直接命中缓存、根本不发请求，测试于是变成空转。
    """
    monkeypatch.setattr(ai_core, "_shared_token", None)
    monkeypatch.setattr(ai_core, "_shared_token_expire", 0)
    return ai_core


def _patch_get(monkeypatch, response):
    """把 ai_core 里的 requests.get 换成返回固定响应的假函数。"""
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(ai_core.requests, "get", fake_get)
    return calls


def test_disabled_key_reason_is_printed(monkeypatch, capsys, fresh_token_cache):
    """密钥被禁用时，Code 与 Message 必须出现在日志里。"""
    calls = _patch_get(
        monkeypatch, _FakeResponse(ALIYUN_DISABLED_KEY_BODY, status_code=400)
    )

    token = ai_core.refresh_aliyun_token()
    out = capsys.readouterr().out

    assert len(calls) == 1, "本用例应当真的走到发请求这一步"
    assert token is None, "拒绝响应不该被当成有效 Token"
    assert "InvalidAccessKeyId.Inactive" in out, f"日志里没有错误码：{out!r}"
    assert "Specified access key is disabled." in out, f"日志里没有错误描述：{out!r}"
    assert "400" in out, f"日志里没有 HTTP 状态码：{out!r}"


def test_non_dict_body_is_not_swallowed(monkeypatch, capsys, fresh_token_cache):
    """网关返回 HTML 之类非 JSON 对象时，同样不能静默返回 None。"""
    _patch_get(monkeypatch, _FakeResponse("<html>502 Bad Gateway</html>", 502))

    token = ai_core.refresh_aliyun_token()
    out = capsys.readouterr().out

    assert token is None
    assert out.strip(), "非预期响应也必须留痕——静默失败正是本组测试要防的"


def test_success_path_still_returns_token(monkeypatch, capsys, fresh_token_cache):
    """成功那一支不能因为补日志而改变：仍返回 Token 并打 `[OK]`。"""
    _patch_get(monkeypatch, _FakeResponse(_OK_BODY))

    token = ai_core.refresh_aliyun_token()
    out = capsys.readouterr().out

    assert token == "fake-token-id"
    assert "阿里云Token刷新成功" in out


def test_token_is_cached_after_success(monkeypatch, capsys, fresh_token_cache):
    """成功后第二次调用应命中缓存，不再发请求（原有行为，顺带锁住）。"""
    calls = _patch_get(monkeypatch, _FakeResponse(_OK_BODY))

    first = ai_core.refresh_aliyun_token()
    second = ai_core.refresh_aliyun_token()

    assert first == second == "fake-token-id"
    assert len(calls) == 1, "第二次应当命中模块级缓存"
