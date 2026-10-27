"""
端到端集成测试（集成负责人维护；跨模块，不属于任何单一负责人）。

把多个模块串起来验证：
Transcript -> classroom adapter -> register_meeting -> analyze_group
-> GroupAnalysisResult 的全链路，以及确定性、极小语料 warning、
窗口契约（10.22 状态锁定）。
"""

import unittest
import warnings
from datetime import datetime, timedelta

import numpy as np

from gca_engine.adapters.classroom import transcripts_to_utterances
from gca_engine.core.lsa.config import LSAConfig
from gca_engine.core.lsa.lsa_model import LSAModel
from gca_engine.engine import analyze_utterances
from gca_engine.schemas import AnalysisStatus, Utterance
from gca_engine.service import analyze_group, clear_meeting, list_meetings, register_meeting
from gca_engine.windows import build_fixed_windows, build_sliding_windows


def _record(rid, uid, content, ts):
    return {"id": rid, "user_id": uid, "content": content, "timestamp": ts}


def _no_nan(obj) -> bool:
    """递归检查任意嵌套结构里没有任何 NaN。"""

    def walk(o):
        if isinstance(o, dict):
            return all(walk(v) for v in o.values())
        if isinstance(o, (list, tuple)):
            return all(walk(v) for v in o)
        if isinstance(o, float):
            return not np.isnan(o)
        return True

    return walk(obj)


class TestEndToEndChain(unittest.TestCase):
    """Transcript -> Utterance -> analyze_group -> GroupAnalysisResult 全链路。"""

    def tearDown(self):
        for mid in list_meetings():
            clear_meeting(mid)

    def test_full_chain_from_transcript_records(self):
        t0 = datetime(2026, 10, 18, 9, 0, 0)
        records = [
            _record(1, 101, "我觉得这个方案可行", t0 + timedelta(seconds=30)),
            _record(2, 102, "我同意但是时间不够", t0 + timedelta(seconds=120)),
            _record(3, 103, "我们可以把工作拆开", t0 + timedelta(seconds=290)),
            _record(4, 101, "先做核心部分", t0 + timedelta(seconds=310)),
            _record(5, 103, "我来处理数据", t0 + timedelta(seconds=420)),
            _record(6, 102, "我来写测试", t0 + timedelta(seconds=500)),
        ]
        utterances = transcripts_to_utterances(records, "meeting-9")
        self.assertEqual(len(utterances), 6)
        # datetime 归一：最早发言为 0 秒
        self.assertAlmostEqual(utterances[0].timestamp, 0.0)

        register_meeting("meeting-9", utterances)
        result = analyze_group("meeting-9")

        self.assertEqual(result.status, AnalysisStatus.SUCCESS)
        self.assertEqual(set(result.student_metrics), {"101", "102", "103"})
        # 三人各 2/6 -> 参与度 1/3；所有指标无 NaN 且落在合理区间
        for m in result.student_metrics.values():
            self.assertAlmostEqual(m["participation"], 1 / 3)
            for v in m.values():
                self.assertFalse(np.isnan(v))
        self.assertEqual(result.group_metrics["participation"]["count"], 3)
        # 10.28 起 timeline 已实现：470 秒的课堂 = 2 个固定 5 分钟窗口
        self.assertIsNotNone(result.timeline)
        self.assertEqual(len(result.timeline["fixed_5min"]), 2)
        self.assertEqual(
            result.timeline["fixed_5min"][0]["start_second"], 0
        )
        self.assertEqual(
            result.timeline["fixed_5min"][1]["start_second"], 300
        )
        self.assertTrue(result.timeline["sliding_5min"])
        self.assertEqual(result.metadata["n_utterances"], 6)
        self.assertEqual(result.metadata["n_speakers"], 3)
        # 相对秒数：最早 30 -> 0，最晚 500 -> 470
        self.assertEqual(result.metadata["duration_seconds"], 470.0)
        self.assertTrue(_no_nan(result.to_dict()))

    def test_determinism_three_runs(self):
        lines = [
            ("u001", "I think this plan works", 10.0),
            ("u002", "I agree but time is short", 40.0),
            ("u003", "We can split the work into steps", 90.0),
            ("u001", "Yes let us build the core first", 150.0),
            ("u003", "I will handle the data part", 210.0),
            ("u002", "I will write the tests", 280.0),
        ]
        us = [
            Utterance("det-1", s, t, ts, f"t{i}")
            for i, (s, t, ts) in enumerate(lines)
        ]
        register_meeting("det-1", us)
        runs = [analyze_group("det-1").to_dict() for _ in range(3)]
        for key in ("status", "student_metrics", "group_metrics", "warnings"):
            self.assertEqual(runs[0][key], runs[1][key])
            self.assertEqual(runs[1][key], runs[2][key])
        # metadata.generated_at 每次不同；其余字段必须一致
        for key in ("n_utterances", "n_speakers", "duration_seconds", "lsa"):
            self.assertEqual(runs[0]["metadata"][key], runs[1]["metadata"][key])

    def test_empty_classroom_no_crash(self):
        records = [
            _record(1, 101, None, 10.0),
            _record(2, 102, "   ", 20.0),
            _record(3, 103, "", 30.0),
        ]
        utterances = transcripts_to_utterances(records, "empty-9")
        self.assertEqual(utterances, [])
        register_meeting("empty-9", utterances)
        result = analyze_group("empty-9")
        self.assertEqual(result.status, AnalysisStatus.EMPTY_TRANSCRIPT)

    def test_single_person_classroom_no_crash(self):
        records = [
            _record(1, 101, "大家好", 10.0),
            _record(2, 101, "我继续讲", 60.0),
            _record(3, 101, "最后总结", 120.0),
        ]
        utterances = transcripts_to_utterances(records, "solo-9")
        self.assertEqual({u.speaker_id for u in utterances}, {"101"})
        register_meeting("solo-9", utterances)
        result = analyze_group("solo-9")
        self.assertEqual(result.status, AnalysisStatus.SINGLE_SPEAKER)
        m = result.student_metrics["101"]
        self.assertAlmostEqual(m["overall_responsivity"], 0.0)
        self.assertAlmostEqual(m["social_impact"], 0.0)
        self.assertTrue(_no_nan(result.to_dict()))

    def test_same_timestamp_stable_order(self):
        records = [
            _record(3, 103, "third message here", 50.0),
            _record(1, 101, "first message here", 50.0),
            _record(2, 102, "second message here", 50.0),
        ]
        u1 = transcripts_to_utterances(records, "same-9")
        u2 = transcripts_to_utterances(records, "same-9")
        # 同时间戳按 utterance_id 稳定排序，两次转换结果一致
        self.assertEqual([u.utterance_id for u in u1], ["1", "2", "3"])
        self.assertEqual(
            [(u.utterance_id, u.timestamp) for u in u1],
            [(u.utterance_id, u.timestamp) for u in u2],
        )
        register_meeting("same-9", u1)
        r1 = analyze_group("same-9")
        r2 = analyze_group("same-9")
        self.assertEqual(r1.student_metrics, r2.student_metrics)


class TestAdapterEdges(unittest.TestCase):
    """classroom adapter 的边界场景。"""

    def test_mixed_datetime_and_numeric_timestamps_raise(self):
        # 混用 datetime 与数字时间戳无法确定统一原点，必须明确报错，
        # 不允许静默产生错误的相对秒数
        t0 = datetime(2026, 10, 18, 9, 0, 0)
        records = [
            _record(1, 101, "大家好", t0 + timedelta(seconds=15)),
            _record(2, 102, "我同意", 30.0),
        ]
        with self.assertRaises(ValueError):
            transcripts_to_utterances(records, "m1")


class TestTinyCorpusWarning(unittest.TestCase):
    """极小语料与 TruncatedSVD warning 的回归锁定。"""

    def test_one_doc_corpus_warning_but_vectors_clean(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            model = LSAModel(LSAConfig(n_components=300))
            info = model.fit(["only one document here"])
            vectors = model.transform(["only one document here"])
        self.assertEqual(info["actual_dimensions"], 1)
        self.assertFalse(np.isnan(vectors).any())
        self.assertFalse(np.isinf(vectors).any())
        # 已知无害 warning：explained_variance_ratio_ 除零（诊断属性，不进向量）
        self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))

    def test_two_identical_english_utterances_no_nan_through_engine(self):
        # 2 条相同英文 -> 列方差为 0 -> evr 除零 warning，但结果不得有 NaN
        us = [
            Utterance("tiny-1", "a", "I agree", 10.0, "u1"),
            Utterance("tiny-1", "b", "I agree", 20.0, "u2"),
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = analyze_utterances("tiny-1", us)
        self.assertEqual(r.status, AnalysisStatus.SUCCESS)
        self.assertEqual(r.metadata["lsa"]["actual_dimensions"], 1)
        self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))
        self.assertTrue(_no_nan(r.to_dict()))


class TestWindowsContract(unittest.TestCase):
    """窗口契约（10.28 雷梦琪实现 windows.py 后改写）。

    原来锁的是"未实现必须显式报错"；现在锁"必须真的产出 timeline"，
    并且空课堂/短课堂不能因为窗口计算而崩。
    """

    def test_window_builders_return_lists(self):
        def analyzer(subset):
            from gca_engine.schemas import SIX_METRICS

            return {u.speaker_id: {m: 0.5 for m in SIX_METRICS} for u in subset}

        us = [
            Utterance("w-1", "a", "hello world", 10.0, "u1"),
            Utterance("w-1", "b", "goodbye world", 700.0, "u2"),
        ]
        fixed = build_fixed_windows(us, analyzer=analyzer)
        sliding = build_sliding_windows(us, analyzer=analyzer)
        self.assertEqual(len(fixed), 3)          # 0-300 / 300-600 / 600-900
        self.assertTrue(sliding)
        self.assertEqual(sliding[0]["center_second"], 30)
        # 中间那个窗口没人发言，group_metrics 必须是空字典而不是 None
        self.assertEqual(fixed[1]["group_metrics"], {})

    def test_engine_timeline_present(self):
        us = [
            Utterance("w-1", "a", "hello world", 10.0, "u1"),
            Utterance("w-1", "b", "goodbye world", 20.0, "u2"),
        ]
        r = analyze_utterances("w-1", us)
        self.assertIsNotNone(r.timeline)
        self.assertEqual(len(r.timeline["fixed_5min"]), 1)
        self.assertFalse(any("timeline 尚未实现" in w for w in r.warnings))

    def test_empty_utterances_windows_no_crash(self):
        def analyzer(subset):  # 空子集不会被调用
            raise AssertionError("空子集不应调用 analyzer")

        self.assertEqual(
            build_fixed_windows([], analyzer=analyzer)[0]["group_metrics"], {}
        )
        self.assertEqual(build_sliding_windows([], analyzer=analyzer), [])


if __name__ == "__main__":
    unittest.main()
