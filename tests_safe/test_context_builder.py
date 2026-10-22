"""Context Builder 原语：上下文裁剪行为（与 llm_service 原实现逐字一致）。"""

from app.services.context_builder import normalize_context_lines, normalize_text
from app.services.llm_service import LLMService


def test_normalize_text_basics():
    assert normalize_text(None) == ""
    assert normalize_text("  a \n b\t c ") == "a b c"
    assert normalize_text({"k": "中文"}, 100) == '{"k": "中文"}'
    assert normalize_text("abcdef", 3) == "abc"


def test_normalize_context_lines_keeps_last_items():
    items = [f"第{i}条" for i in range(10)]
    result = normalize_context_lines(items, max_items=3, each_len=80, total_len=500)
    assert result == "第7条\n第8条\n第9条"


def test_normalize_context_lines_dict_variants():
    items = [
        {"username": "李同学", "content": "我认为需要光照"},
        {"student_name": "王同学", "text": "还有二氧化碳"},
        {"user": "张老师", "speech": "补充一点"},
        {"content": "没有用户名"},
    ]
    result = normalize_context_lines(items, max_items=8, each_len=80, total_len=500)
    assert result.splitlines() == [
        "李同学: 我认为需要光照",
        "王同学: 还有二氧化碳",
        "张老师: 补充一点",
        "用户: 没有用户名",
    ]


def test_normalize_context_lines_per_item_and_total_truncation():
    items = [{"username": "甲", "content": "x" * 100}]
    result = normalize_context_lines(items, max_items=8, each_len=5, total_len=500)
    assert result == "甲: xxxxx"

    items = [f"line{i}" for i in range(5)]
    result = normalize_context_lines(items, max_items=8, each_len=80, total_len=12)
    assert result == "line0\nline1\n"[:12]


def test_normalize_context_lines_skips_blank_lines():
    # 纯空字符串被跳过；「用户名 + 空内容」仍算一行（与原实现一致）
    items = ["", "  ", {"username": "甲", "content": ""}]
    assert normalize_context_lines(items) == "甲: "


def test_llm_service_delegates_to_the_same_primitive():
    svc = object.__new__(LLMService)  # 不触发 __init__ 的客户端构造
    items = [
        {"username": "甲", "content": "  多余   空白  "},
        "第二条",
    ]
    expected = normalize_context_lines(items, max_items=8, each_len=80, total_len=500)
    assert svc._normalize_context_lines(items) == expected
    assert svc._normalize_text("  a   b ", 10) == normalize_text("  a   b ", 10)
