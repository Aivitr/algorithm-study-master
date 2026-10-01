"""LLM 服务中**纯逻辑**部分的测试——无外部依赖、无网络、无数据库。

来源
----
移植自 `tests/test_llm_adapter.py`，但**不是原样搬运**。该文件 25 条里只有
JSON 清洗与缓存两组值得一提，其余（fallback / provider 配置 / 限流）针对的是
`llm_service.py` 中**并不存在**的 API：

    _chat_once、_fallback_chat、_chat_with_fallback、_chat_json_with_fallback

（已逐个 grep 确认为 0 处定义）因此 `patch.object(llm, "_chat_once")` 只会抛
`AttributeError`，用例直接 error。详见 `docs/legacy-assets-audit.md` §1.3。

订正：原文 5 条断言写成"无效输入返回空字典 `{}`"，与实现相反。
`llm_service.py:84-109` 的 `_clean_json` 解析失败时**末行 `return None`**。
本文件按实测行为重写，并把该契约显式钉死——原断言若照搬，会是一个永远
失败的用例，或者更糟：被改成 `assert isinstance(result, dict)` 之后
看起来"通过"，实则从未验证过任何东西。

本文件全部取值均先经实测确认，未凭阅读源码推断。
"""

import threading

import pytest


@pytest.fixture(scope="module")
def llm():
    """`llm_service` 中的全局单例。

    导入会构造 `OpenAI(...)` 客户端，但**不发起请求**——构造本身不触网。
    """
    from app.services.llm_service import llm as _llm

    return _llm


# --------------------------------------------------------------- JSON 清洗


def test_clean_json_accepts_valid_json_string(llm):
    """合法 JSON 字符串原样解析。"""
    assert llm._clean_json('{"key": "value", "count": 42}') == {"key": "value", "count": 42}


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"a": 1, "b": 2}\n```',
        '```\n{"a": 1, "b": 2}\n```',
        'Here is the result:\n```json\n{"a": 1, "b": 2}\n```\nDone!',
    ],
    ids=["json-fence", "plain-fence", "surrounded-by-prose"],
)
def test_clean_json_strips_markdown_code_fence(llm, raw):
    """模型常把 JSON 包在 Markdown 代码块里返回，三种包裹形态都要能剥掉。

    第三种（前后还有散文）走的是「截取最外层 {}」那条兜底分支，
    与前两种走的「直接 replace 反引号」分支不是同一段代码。
    """
    assert llm._clean_json(raw) == {"a": 1, "b": 2}


def test_clean_json_keeps_nested_structure(llm):
    """嵌套对象与数组不得被展平或截断。"""
    result = llm._clean_json(
        '```json\n{"user": {"name": "Alice", "age": 30}, "items": [1, 2, 3]}\n```'
    )
    assert result["user"]["name"] == "Alice"
    assert result["user"]["age"] == 30
    assert result["items"] == [1, 2, 3]


def test_clean_json_preserves_escaped_quotes(llm):
    """转义引号不得被反引号清洗步骤破坏。

    这是 `replace("```", "")` 与 JSON 转义的交叉风险点。
    """
    assert llm._clean_json('{"message": "She said \\"Hello\\""}') == {
        "message": 'She said "Hello"'
    }


@pytest.mark.parametrize(
    "raw",
    ["not a json at all", "", None],
    ids=["garbage", "empty", "none"],
)
def test_clean_json_returns_none_when_unparseable(llm, raw):
    """**契约**：解析失败返回 `None`，不是空字典。

    原文断言的是 `isinstance(result, dict)`——与实现相反。若照搬会永远失败；
    若"顺手放松"成只判类型，则连"返回了什么"都没在验证。
    """
    assert llm._clean_json(raw) is None


def test_clean_json_does_not_accept_single_quotes(llm):
    """单引号 JSON **不被接受**，返回 `None`。

    `json.loads` 严格遵循 JSON 规范，不做 Python 字面量兼容，兜底分支也不转换。
    记录这条边界，避免今后误以为它能容错。
    """
    assert llm._clean_json("{'key': 'value'}") is None


def test_clean_json_can_return_non_dict(llm):
    """**契约**：返回类型取决于输入，不保证是字典。

    `_clean_json` 的返回标注是 `Optional[Any]`，顶层是数组就返回 list、是数字就
    返回 int。任何调用方若直接下标取值，都需要自己先判类型。
    """
    assert llm._clean_json("[1, 2, 3]") == [1, 2, 3]
    assert llm._clean_json("42") == 42


def test_clean_json_handles_large_payload(llm):
    """超大响应不得被截断——清洗路径上没有长度上限。"""
    payload = "x" * 10_000
    result = llm._clean_json('{"data": "' + payload + '"}')
    assert result == {"data": payload}


# ------------------------------------------------------------- 文本归一化


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        (123, "123"),
        ({"a": 1}, '{"a": 1}'),
        ("  a   b  ", "a b"),
        ("a\n\tb", "a b"),
    ],
    ids=["none", "int", "dict", "whitespace", "newline-tab"],
)
def test_normalize_text(llm, raw, expected):
    """非字符串先序列化，再将连续空白折叠为单个空格。

    该函数被几乎每条 LLM 调用用作入参清洗，长度与空白处理都影响**缓存键**，
    因此行为必须稳定。
    """
    assert llm._normalize_text(raw) == expected


def test_normalize_text_truncates_to_max_len(llm):
    """默认截断到 500 字符。"""
    assert len(llm._normalize_text("x" * 600)) == 500
    assert len(llm._normalize_text("x" * 600, max_len=10)) == 10


# ------------------------------------------------------------------ 缓存


@pytest.fixture
def cache():
    from app.services.llm_service import ExpiringLRUCache

    return ExpiringLRUCache(maxsize=10, expiry=3600)


def test_cache_get_set(cache):
    """基本读写。"""
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_cache_lru_eviction_removes_oldest():
    """超出容量时驱逐**最久未使用**的一条。"""
    from app.services.llm_service import ExpiringLRUCache

    cache = ExpiringLRUCache(maxsize=2, expiry=3600)
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    assert cache.get("key1") is None
    assert cache.get("key2") == "value2"
    assert cache.get("key3") == "value3"
    assert len(cache) == 2


def test_cache_get_refreshes_recency():
    """`get` 命中应当把该条移到队尾，从而免于被驱逐。

    原文只测了"写入顺序驱逐"，没测"读取会影响驱逐顺序"——而后者才是
    LRU 之所以叫 LRU 的那一半。缓存策略此前列为待验证项，这条补上。
    """
    from app.services.llm_service import ExpiringLRUCache

    cache = ExpiringLRUCache(maxsize=2, expiry=3600)
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.get("key1")  # key1 变为最近使用
    cache.set("key3", "value3")  # 应当驱逐 key2

    assert cache.get("key2") is None
    assert cache.get("key1") == "value1"
    assert cache.get("key3") == "value3"


def test_cache_delete(cache):
    """删除后读不到。"""
    cache.set("key1", "value1")
    cache.delete("key1")
    assert cache.get("key1") is None


def test_cache_delete_missing_key_is_noop(cache):
    """删除不存在的键不得抛异常。"""
    cache.delete("never-set")
    assert len(cache) == 0


def test_cache_clear(cache):
    """清空后长度归零。"""
    cache.set("key1", "value1")
    cache.clear()
    assert len(cache) == 0
    assert cache.get("key1") is None


def test_cache_expired_entry_is_dropped_and_counted():
    """过期条目在 `get` 时被删除，而不是留在字典里占位。

    用 `expiry=-1` 制造"必定已过期"，避免依赖 `sleep`——那会让测试变慢且
    在负载高时不稳定。
    """
    from app.services.llm_service import ExpiringLRUCache

    cache = ExpiringLRUCache(maxsize=10, expiry=-1)
    cache.set("key", "value")

    assert cache.get("key") is None
    assert len(cache) == 0, "过期条目应被就地删除"


def test_cache_none_value_is_indistinguishable_from_miss():
    """**已知歧义**：存入 `None` 后，`get` 无法区分"命中且值为 None"与"未命中"。

    `ExpiringLRUCache.get` 用 `None` 表示未命中，而 `None` 又是合法值。
    当前调用方（`llm_service` 内部）缓存的是字符串，暂时不受影响。
    记录为既有行为，不在本次重构中改动——改它会改变缓存语义。
    """
    from app.services.llm_service import ExpiringLRUCache

    cache = ExpiringLRUCache(maxsize=10, expiry=3600)
    cache.set("key", None)

    assert cache.get("key") is None
    assert len(cache) == 1, "条目确实在，只是取出来是 None"


def test_cache_is_thread_safe_under_concurrent_writers_and_readers():
    """并发读写不得抛异常，且容量上限始终成立。

    原文这条只写了 `assert True`——即"不抛异常就算过"，等于什么都没断言。
    此处补上真正的不变量：容量上限、以及抢先写入的键必然能读回。
    """
    from app.services.llm_service import ExpiringLRUCache

    maxsize = 50
    cache = ExpiringLRUCache(maxsize=maxsize, expiry=3600)
    errors = []

    def writer():
        try:
            for i in range(200):
                cache.set(f"key{i % 100}", f"value{i}")
        except Exception as exc:  # noqa: BLE001 —— 线程内异常不会传播到主线程
            errors.append(exc)

    def reader():
        try:
            for i in range(200):
                cache.get(f"key{i % 100}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    threads += [threading.Thread(target=reader) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发读写抛出异常：{errors}"
    assert len(cache) <= maxsize, f"容量上限被突破：{len(cache)} > {maxsize}"
