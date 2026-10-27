"""
中文预处理测试（集成负责人补充；日常维护负责人：岳柔）。

覆盖 gca_engine/preprocessing/chinese.py 的 normalize_text / tokenize：
基础清洗、全角空格、空白压缩、口语词过滤、jieba 缺失时的降级行为。
断言兼容"有 jieba / 无 jieba"两种环境。
"""

import importlib.util
import unittest

from gca_engine.preprocessing.chinese import normalize_text, tokenize

_HAS_JIEBA = importlib.util.find_spec("jieba") is not None


class TestNormalizeText(unittest.TestCase):

    def test_none_returns_empty(self):
        self.assertEqual(normalize_text(None), "")

    def test_fullwidth_space_converted(self):
        self.assertEqual(normalize_text("大家　好"), "大家 好")

    def test_whitespace_collapsed_and_stripped(self):
        self.assertEqual(normalize_text("  我  同意  "), "我 同意")

    def test_non_string_coerced(self):
        self.assertEqual(normalize_text(123), "123")


class TestTokenize(unittest.TestCase):

    def test_none_and_blank_return_empty(self):
        self.assertEqual(tokenize(None), [])
        self.assertEqual(tokenize("   "), [])

    def test_filler_words_filtered(self):
        # "嗯"、"那个" 在极简口语词表里；jieba / 空白切两条路径结论一致
        self.assertEqual(tokenize("嗯 那个 好"), ["好"])

    def test_normal_text_tokenizes(self):
        tokens = tokenize("大家好")
        if _HAS_JIEBA:
            self.assertEqual(tokens, ["大家", "好"])
        else:
            self.assertEqual(tokens, ["大家好"])

    def test_tokens_are_clean_nonempty_strings(self):
        tokens = tokenize("我 觉得 这个 方案 可行")
        self.assertEqual(len(tokens), 5)
        for t in tokens:
            self.assertIsInstance(t, str)
            self.assertTrue(t.strip())


if __name__ == "__main__":
    unittest.main()
