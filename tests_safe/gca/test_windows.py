"""
时间窗口测试（负责人：雷梦琪）。

分两层：

1. windows.py 单元层：用假 analyzer，只验证"切窗口/算统计/出错降级"，
   不依赖 LSA 拟合，跑得快。
2. engine 集成层：验证 analyze_utterances 真的把 timeline 接出去了，
   并且空课堂、单人课堂、短课堂都不会崩。
"""

import unittest

import numpy as np

from gca_engine.config import EngineConfig
from gca_engine.engine import analyze_utterances
from gca_engine.schemas import SIX_METRICS, AnalysisStatus, Utterance
from gca_engine.windows import (
    build_fixed_windows,
    build_sliding_windows,
    build_timeline,
    duration_seconds,
)


def _u(spk, ts, text="some words here", mid="m"):
    return Utterance(mid, spk, text, float(ts), f"u{ts}-{spk}")


def _metrics(value: float = 0.5) -> dict[str, float]:
    return {name: value for name in SIX_METRICS}


def _fake_analyzer(subset):
    """按子集里的发言人生成六指标（每人固定值），用于验证窗口口径。"""
    return {u.speaker_id: _metrics(1.0) for u in subset}


class TestDuration(unittest.TestCase):

    def test_duration_uses_timestamp_when_no_end_time(self):
        us = [_u("a", 10), _u("b", 250)]
        self.assertEqual(duration_seconds(us), 250.0)

    def test_duration_prefers_end_time(self):
        us = [
            Utterance("m", "a", "hi", 10.0, "u1", end_time=42.0),
            Utterance("m", "b", "yo", 200.0, "u2", end_time=None),
        ]
        self.assertEqual(duration_seconds(us), 200.0)

    def test_duration_empty(self):
        self.assertEqual(duration_seconds([]), 0.0)


class TestFixedWindows(unittest.TestCase):

    def test_splits_by_five_minutes(self):
        us = [_u("a", 10), _u("b", 290), _u("c", 310), _u("a", 470)]
        windows = build_fixed_windows(us, analyzer=_fake_analyzer)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0]["start_second"], 0)
        self.assertEqual(windows[0]["end_second"], 300)
        self.assertEqual(windows[1]["start_second"], 300)
        self.assertEqual(windows[1]["end_second"], 600)
        # 第一段两个人（a、b），第二段两个人（c、a）
        self.assertEqual(windows[0]["group_metrics"]["participation"]["count"], 2)
        self.assertEqual(windows[1]["group_metrics"]["participation"]["count"], 2)

    def test_utterance_on_boundary_goes_to_later_window(self):
        us = [_u("a", 300)]  # 正好落在 300
        windows = build_fixed_windows(us, analyzer=_fake_analyzer, duration=300)
        self.assertEqual(windows[0]["group_metrics"], {})
        self.assertEqual(windows[0]["start_second"], 0)

        us2 = [_u("a", 0), _u("b", 300)]
        windows2 = build_fixed_windows(us2, analyzer=_fake_analyzer, duration=600)
        self.assertEqual(windows2[0]["group_metrics"]["participation"]["count"], 1)
        self.assertEqual(windows2[1]["group_metrics"]["participation"]["count"], 1)

    def test_empty_window_has_empty_group_metrics(self):
        us = [_u("a", 10), _u("b", 700)]
        windows = build_fixed_windows(us, analyzer=_fake_analyzer)
        self.assertEqual(len(windows), 3)  # 0-300, 300-600, 600-900
        self.assertEqual(windows[1]["group_metrics"], {})  # 300-600 没人说话
        self.assertEqual(windows[2]["group_metrics"]["participation"]["count"], 1)

    def test_short_class_single_window(self):
        us = [_u("a", 10), _u("b", 20)]
        windows = build_fixed_windows(us, analyzer=_fake_analyzer)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["start_second"], 0)
        self.assertEqual(windows[0]["end_second"], 300)

    def test_no_utterances_still_one_window(self):
        windows = build_fixed_windows([], analyzer=_fake_analyzer)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["group_metrics"], {})

    def test_analyzer_not_called_for_empty_window(self):
        calls = []

        def analyzer(subset):
            calls.append(len(subset))
            return _fake_analyzer(subset)

        build_fixed_windows([_u("a", 10)], analyzer=analyzer, duration=700)
        # 只有第一个窗口有发言，后两个窗口不该调用 analyzer
        self.assertEqual(calls, [1])

    def test_analyzer_failure_is_recorded_not_raised(self):
        def boom(subset):
            raise RuntimeError("模拟向量异常")

        errors = []
        windows = build_fixed_windows(
            [_u("a", 10)], analyzer=boom, errors=errors
        )
        self.assertEqual(windows[0]["group_metrics"], {})
        self.assertEqual(len(errors), 1)
        self.assertIn("RuntimeError", errors[0]["error"])

    def test_invalid_window_seconds(self):
        with self.assertRaises(ValueError):
            build_fixed_windows([], window_seconds=0)


class TestSlidingWindows(unittest.TestCase):

    def test_update_points_every_30_seconds(self):
        us = [_u("a", 10), _u("b", 100)]
        windows = build_sliding_windows(us, analyzer=_fake_analyzer, duration=150)
        centers = [w["center_second"] for w in windows]
        self.assertEqual(centers, [30, 60, 90, 120, 150])

    def test_tail_point_added_when_duration_not_multiple_of_step(self):
        windows = build_sliding_windows(
            [_u("a", 10)], analyzer=_fake_analyzer, duration=100
        )
        centers = [w["center_second"] for w in windows]
        self.assertEqual(centers, [30, 60, 90, 100])

    def test_window_covers_last_five_minutes(self):
        # center=600 时，窗口是 (300, 600]，300 那条不算、301 那条算
        us = [_u("a", 300), _u("b", 301), _u("c", 600)]
        windows = build_sliding_windows(us, analyzer=_fake_analyzer, duration=600)
        at_600 = [w for w in windows if w["center_second"] == 600][0]
        self.assertEqual(at_600["group_metrics"]["participation"]["count"], 2)

    def test_empty_windows_before_speech_are_kept(self):
        us = [_u("a", 100)]
        windows = build_sliding_windows(us, analyzer=_fake_analyzer, duration=120)
        self.assertEqual(windows[0]["center_second"], 30)
        self.assertEqual(windows[0]["group_metrics"], {})
        self.assertNotEqual(windows[-1]["group_metrics"], {})

    def test_class_shorter_than_one_step(self):
        us = [_u("a", 5)]
        self.assertEqual(build_sliding_windows(us, analyzer=_fake_analyzer), [])

    def test_step_larger_than_window_rejected(self):
        with self.assertRaises(ValueError):
            build_sliding_windows([], window_seconds=30, step_seconds=60)


class TestTimeline(unittest.TestCase):

    def test_timeline_has_both_sections(self):
        us = [_u("a", 10), _u("b", 100), _u("c", 400)]
        timeline, warnings, errors = build_timeline(us, _fake_analyzer, duration=400)
        self.assertIn("fixed_5min", timeline)
        self.assertIn("sliding_5min", timeline)
        self.assertEqual(len(timeline["fixed_5min"]), 2)
        self.assertEqual(errors, [])
        self.assertIsInstance(warnings, list)

    def test_warns_about_empty_fixed_window(self):
        us = [_u("a", 10), _u("b", 700)]
        timeline, warnings, _ = build_timeline(us, _fake_analyzer)
        self.assertTrue(any("没有发言" in w for w in warnings))

    def test_warns_when_class_shorter_than_step(self):
        timeline, warnings, _ = build_timeline([_u("a", 5)], _fake_analyzer)
        self.assertEqual(timeline["sliding_5min"], [])
        self.assertTrue(any("不足一个滑动更新点" in w for w in warnings))


class TestEngineTimeline(unittest.TestCase):
    """engine 层：真实 LSA + GCA 跑窗口，验证接线和降级。"""

    def _no_nan(self, obj) -> bool:
        def walk(o):
            if isinstance(o, dict):
                return all(walk(v) for v in o.values())
            if isinstance(o, (list, tuple)):
                return all(walk(v) for v in o)
            if isinstance(o, float):
                return not np.isnan(o)
            return True

        return walk(obj)

    def _class_of_six(self, mid="m-win"):
        return [
            Utterance(mid, "a", "I think the plan works well", 10.0, "u1"),
            Utterance(mid, "b", "I agree but time is short", 40.0, "u2"),
            Utterance(mid, "c", "We can split the work", 90.0, "u3"),
            Utterance(mid, "a", "Let us build the core first", 150.0, "u4"),
            Utterance(mid, "c", "I will handle the data part", 320.0, "u5"),
            Utterance(mid, "b", "I will write the tests", 380.0, "u6"),
            Utterance(mid, "a", "Then we review together", 700.0, "u7"),
        ]

    def test_engine_returns_timeline(self):
        r = analyze_utterances("m-win", self._class_of_six())
        self.assertEqual(r.status, AnalysisStatus.SUCCESS)
        self.assertIsNotNone(r.timeline)
        self.assertIn("fixed_5min", r.timeline)
        self.assertIn("sliding_5min", r.timeline)
        self.assertEqual(len(r.timeline["fixed_5min"]), 3)  # 0-300/300-600/600-900
        self.assertTrue(r.timeline["sliding_5min"])
        self.assertTrue(self._no_nan(r.to_dict()))

    def test_engine_no_timeline_warning_any_more(self):
        r = analyze_utterances("m-win", self._class_of_six())
        self.assertFalse(any("timeline 尚未实现" in w for w in r.warnings))

    def test_engine_metadata_records_window_config(self):
        r = analyze_utterances("m-win", self._class_of_six())
        meta = r.metadata["timeline"]
        self.assertEqual(meta["fixed_window_seconds"], 300)
        self.assertEqual(meta["sliding_window_seconds"], 300)
        self.assertEqual(meta["sliding_step_seconds"], 30)
        self.assertEqual(meta["n_fixed_windows"], 3)
        self.assertEqual(meta["n_sliding_windows"], len(r.timeline["sliding_5min"]))

    def test_engine_timeline_can_be_disabled(self):
        r = analyze_utterances(
            "m-win", self._class_of_six(), config=EngineConfig(timeline_enabled=False)
        )
        self.assertIsNone(r.timeline)
        self.assertTrue(any("timeline 已按" in w for w in r.warnings))

    def test_single_speaker_still_gets_timeline(self):
        us = [
            Utterance("solo", "a", "I speak alone here", 10.0, "u1"),
            Utterance("solo", "a", "and I continue talking", 60.0, "u2"),
        ]
        r = analyze_utterances("solo", us)
        self.assertEqual(r.status, AnalysisStatus.SINGLE_SPEAKER)
        self.assertIsNotNone(r.timeline)
        self.assertTrue(self._no_nan(r.to_dict()))

    def test_short_class_timeline_no_crash(self):
        us = [
            Utterance("short", "a", "hello there", 5.0, "u1"),
            Utterance("short", "b", "hi there too", 20.0, "u2"),
        ]
        r = analyze_utterances("short", us)
        self.assertEqual(len(r.timeline["fixed_5min"]), 1)
        self.assertEqual(r.timeline["sliding_5min"], [])
        self.assertTrue(any("不足" in w for w in r.warnings))

    def test_window_group_metrics_have_all_six(self):
        r = analyze_utterances("m-win", self._class_of_six())
        for w in r.timeline["fixed_5min"]:
            if w["group_metrics"]:
                self.assertEqual(set(w["group_metrics"]), set(SIX_METRICS))
                for stats in w["group_metrics"].values():
                    self.assertEqual(
                        set(stats), {"mean", "min", "max", "std", "count"}
                    )


if __name__ == "__main__":
    unittest.main()
