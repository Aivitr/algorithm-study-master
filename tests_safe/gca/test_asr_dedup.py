"""
ASR 去重专项测试（ASR 去重策略修复：陈虹宇；日常维护：岳柔）。

覆盖 gca_engine/preprocessing/chinese.py 的：
    dedup_asr_repeats / normalize_text(dedup=...) / tokenize(dedup=...)

设计原则：宁可漏删，不可误删。
- 去重默认关闭：Adapter / LSA / GCA 课堂分析链路结果不变；
- 显式开启（ASR 场景）：只收缩连续 3 次及以上的可靠重复；
- 已知限制集中在 TestKnownLimitations 记录，不得因个别示例放宽规则。
"""

import sys
import unittest
from unittest.mock import patch

from gca_engine.adapters.classroom import transcripts_to_utterances
from gca_engine.preprocessing.chinese import (
    dedup_asr_repeats,
    normalize_text,
    tokenize,
)


class TestReduplicatedWordsPreserved(unittest.TestCase):
    """类别 1：正常单字叠词（2 连）必须保留原文。"""

    def test_mama_baba_gege_tiantian_preserved(self):
        for text in ["妈妈今天很开心", "爸爸", "哥哥", "天天向上"]:
            self.assertEqual(normalize_text(text, dedup=True), text)


class TestAbabExpressionsPreserved(unittest.TestCase):
    """类别 2：合法 ABAB 表达（2 组）必须保留原文。"""

    def test_abab_preserved(self):
        for text in ["我们讨论讨论这个问题", "研究研究", "非常非常好"]:
            self.assertEqual(normalize_text(text, dedup=True), text)


class TestEmphasisCollapse(unittest.TestCase):
    """类别 3：情绪/强调表达在开启去重时的收缩行为。

    注意：3 连单字（哈哈哈）在 ASR 场景下收缩为 2 个（哈哈），
    3 组两字词（非常非常非常）收缩为 2 组（非常非常）。
    语义基本不变；默认关闭去重时完全保留（见开关测试）。
    """

    def test_hahaha_collapses_to_haha(self):
        self.assertEqual(normalize_text("哈哈哈", dedup=True), "哈哈")

    def test_feichang_x3_collapses_to_two_groups(self):
        self.assertEqual(normalize_text("非常非常非常", dedup=True), "非常非常")


class TestAsrStutterCollapse(unittest.TestCase):
    """类别 4：ASR 口吃/卡壳的可靠重复收缩。"""

    def test_ninini_collapses_to_nini(self):
        self.assertEqual(normalize_text("你你你", dedup=True), "你你")

    def test_haode_x4_collapses_to_two_groups(self):
        self.assertEqual(normalize_text("好的好的好的好的", dedup=True), "好的好的")


class TestXiexieChains(unittest.TestCase):
    """类别 5：谢谢谢谢及更长重复串（循环迭代收敛）。"""

    def test_xiexie_x2_collapses(self):
        self.assertEqual(normalize_text("谢谢谢谢", dedup=True), "谢谢")

    def test_long_chain_converges(self):
        self.assertEqual(normalize_text("谢谢谢谢谢谢谢谢", dedup=True), "谢谢")

    def test_extreme_chain_converges(self):
        self.assertEqual(normalize_text("谢" * 50, dedup=True), "谢谢")


class TestEnglishRepeats(unittest.TestCase):
    """类别 6：英文重复——3 连收缩，2 连保留。"""

    def test_hello_x3_collapses(self):
        self.assertEqual(normalize_text("hello hello hello", dedup=True), "hello")

    def test_hello_x2_preserved(self):
        self.assertEqual(normalize_text("hello hello", dedup=True), "hello hello")

    def test_word_internal_doubles_not_touched(self):
        # 单词内部的重复字母（hello 的 ll）不能被单词边界规则破坏
        self.assertEqual(normalize_text("hello", dedup=True), "hello")


class TestNumberRepeats(unittest.TestCase):
    """类别 7：数字重复收缩，正常数字表达保留。"""

    def test_number_x3_collapses(self):
        self.assertEqual(normalize_text("123 123 123", dedup=True), "123")

    def test_number_x2_preserved(self):
        self.assertEqual(normalize_text("123 123", dedup=True), "123 123")

    def test_date_like_text_preserved(self):
        # 无空白分隔的数字不参与重复判断
        self.assertEqual(normalize_text("2024年11月11日", dedup=True), "2024年11月11日")


class TestMixedChineseEnglish(unittest.TestCase):
    """类别 8：中英文混合。"""

    def test_cn_and_en_repeats_collapse_independently(self):
        self.assertEqual(
            normalize_text("我们我们我们 are are are happy", dedup=True),
            "我们我们 are happy",
        )

    def test_non_adjacent_repeats_preserved(self):
        self.assertEqual(
            normalize_text("hello你好hello你好", dedup=True),
            "hello你好hello你好",
        )


class TestNoiseMarkers(unittest.TestCase):
    """类别 9：ASR 噪声标记清洗（无论去重开关都生效）。"""

    def test_spk_and_noise_removed(self):
        self.assertEqual(normalize_text("[spk1]你好[噪音]<unk>"), "你好")

    def test_only_noise_becomes_empty(self):
        self.assertEqual(normalize_text("[spk1][spk2]"), "")

    def test_fullwidth_space_and_whitespace(self):
        self.assertEqual(normalize_text("大家　好"), "大家 好")
        self.assertEqual(normalize_text("  我  同意  "), "我 同意")


class TestEmptyAndNonString(unittest.TestCase):
    """类别 10：空文本、None、非字符串输入的契约。"""

    def test_normalize_empty_and_none(self):
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text(None), "")

    def test_normalize_non_string_coerced(self):
        self.assertEqual(normalize_text(123), "123")
        self.assertEqual(normalize_text(3.14), "3.14")

    def test_dedup_empty_and_non_string(self):
        self.assertEqual(dedup_asr_repeats(""), "")
        self.assertEqual(dedup_asr_repeats(None), "")
        self.assertEqual(dedup_asr_repeats(123), "")

    def test_tokenize_empty(self):
        self.assertEqual(tokenize(None), [])
        self.assertEqual(tokenize("   "), [])


class TestJiebaFallback(unittest.TestCase):
    """类别 11：jieba 不可用时的降级路径。"""

    def _with_jieba_blocked(self):
        return patch.dict(sys.modules, {"jieba": None})

    def test_fallback_splits_on_whitespace(self):
        with self._with_jieba_blocked():
            self.assertEqual(tokenize("我们 讨论 问题"), ["我们", "讨论", "问题"])

    def test_fallback_whole_sentence_is_one_token(self):
        with self._with_jieba_blocked():
            self.assertEqual(tokenize("你好世界"), ["你好世界"])

    def test_fallback_still_filters_fillers(self):
        with self._with_jieba_blocked():
            self.assertEqual(tokenize("嗯 讨论"), ["讨论"])

    def test_fallback_still_supports_dedup(self):
        with self._with_jieba_blocked():
            self.assertEqual(
                tokenize("hello hello hello", dedup=True), ["hello"]
            )


class TestNormalizeDedupSwitch(unittest.TestCase):
    """类别 12：normalize_text 去重开关——默认关闭不改原文。"""

    def test_default_off_preserves_repeats(self):
        self.assertEqual(normalize_text("哈哈哈哈"), "哈哈哈哈")
        self.assertEqual(normalize_text("谢谢谢谢谢谢"), "谢谢谢谢谢谢")
        self.assertEqual(normalize_text("hello hello hello"), "hello hello hello")

    def test_explicit_on_collapses(self):
        self.assertEqual(normalize_text("哈哈哈哈", dedup=True), "哈哈")
        self.assertEqual(normalize_text("hello hello hello", dedup=True), "hello")


class TestTokenizeDedupSwitch(unittest.TestCase):
    """类别 13：tokenize 去重开关透传。"""

    def test_default_off_keeps_three_tokens(self):
        tokens = tokenize("hello hello hello", remove_filler=False)
        self.assertEqual(tokens, ["hello", "hello", "hello"])

    def test_explicit_on_single_token(self):
        tokens = tokenize("hello hello hello", remove_filler=False, dedup=True)
        self.assertEqual(tokens, ["hello"])

    def test_on_with_chinese_word_groups(self):
        # 断言去重结果（4 组 → 2 组），不钉死 jieba 的内部切词方式
        on = "".join(tokenize("好的好的好的好的", dedup=True))
        off = "".join(tokenize("好的好的好的好的"))
        self.assertEqual(on, "好的好的")
        self.assertEqual(off, "好的好的好的好的")


class TestAdapterCompatibility(unittest.TestCase):
    """类别 14：Classroom Adapter 兼容性。

    Adapter 调用 normalize_text 不传 dedup → 默认关闭：
    重复文本保持原样，只有噪声标记被清洗、纯噪声记录被跳过。
    """

    def test_adapter_keeps_repeats_and_cleans_noise(self):
        records = [
            {"id": 1, "user_id": 10, "content": "我们讨论讨论这个问题", "timestamp": 0},
            {"id": 2, "user_id": 11, "content": "谢谢谢谢谢谢", "timestamp": 5},
            {"id": 3, "user_id": 12, "content": "[spk1]我同意", "timestamp": 10},
            {"id": 4, "user_id": 13, "content": "[噪音]", "timestamp": 15},
        ]
        utterances = transcripts_to_utterances(records, "m1")
        self.assertEqual(
            [u.text for u in utterances],
            ["我们讨论讨论这个问题", "谢谢谢谢谢谢", "我同意"],
        )

    def test_adapter_text_unchanged_vs_default_normalize(self):
        content = "大家好，我们 开始 讨论"
        records = [{"id": 1, "user_id": 1, "content": content, "timestamp": 0}]
        utterances = transcripts_to_utterances(records, "m1")
        self.assertEqual(utterances[0].text, normalize_text(content))


class TestKnownLimitations(unittest.TestCase):
    """算法限制记录：无法可靠区分正常重复与 ASR 重复时保留原文。"""

    def test_punctuated_repeats_preserved(self):
        # 带标点分隔的重复不处理（可能是强调，如 "谢谢！谢谢！"）
        self.assertEqual(normalize_text("谢谢！谢谢！", dedup=True), "谢谢！谢谢！")

    def test_mixed_cn_number_no_space_preserved(self):
        # 无空白分隔的中英/数字混合重复无法识别，保守保留
        self.assertEqual(
            normalize_text("第1组第1组第1组", dedup=True), "第1组第1组第1组"
        )

    def test_double_chinese_groups_preserved(self):
        # 2 组两字词与合法 ABAB 无法区分（讨论讨论），保留
        self.assertEqual(normalize_text("讨论讨论", dedup=True), "讨论讨论")


class TestLongAndExtremeInput(unittest.TestCase):
    """类别 16：长文本与极端重复输入的稳定性。"""

    def test_long_paragraph_terminates_and_is_stable(self):
        paragraph = (
            "今天我们讨论这个方案，我觉得很有道理。"
            "然后我们继续讨论，大家都同意。"
            "所以最终决定按计划执行。"
        )
        self.assertEqual(normalize_text(paragraph, dedup=True), paragraph)

    def test_hundred_groups_converge_fast(self):
        text = "好的" * 100
        self.assertEqual(normalize_text(text, dedup=True), "好的好的")

    def test_dedup_false_never_changes_normal_text(self):
        # 无噪声标记、无多余空白的文本：默认关闭时必须逐字不变
        texts = ["哈哈哈哈", "好的好的好的好的", "hello hello hello",
                 "我们讨论讨论这个问题", "2024年11月11日"]
        for t in texts:
            self.assertEqual(normalize_text(t), t)


if __name__ == "__main__":
    unittest.main()
