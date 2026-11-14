"""
Hint 触发候选测试（组长：陈虹宇）。

覆盖：低参与（zero_speech / low_ratio / 连续更新点 / 窗口边界）、
讨论停滞（120 秒阈值 / 边界）、数据不足不误触发、冷却去重、
输入校验。阈值依据见 gca_engine/engagement/triggers.py 的 NOTES。
"""

import unittest

from gca_engine.engagement.protocols import HintCandidate
from gca_engine.engagement.triggers import (
    HintTriggerConfig,
    HintTriggerState,
    compute_hint_candidates,
    discussion_stall_candidates,
    low_participation_candidates,
)
from gca_engine.schemas import Utterance


def _u(speaker: str, ts: float, uid: str | None = None, end_time: float | None = None) -> Utterance:
    return Utterance(
        meeting_id="m1",
        speaker_id=speaker,
        text=f"{speaker} 的发言",
        timestamp=ts,
        utterance_id=uid or f"t-{speaker}-{ts}",
        end_time=end_time,
    )


class TestDiscussionStall(unittest.TestCase):

    def test_triggers_at_exactly_threshold(self):
        us = [_u("A", 10.0), _u("B", 100.0)]
        candidates = discussion_stall_candidates("m1", us, now_second=220.0)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.hint_type, "discussion_stall")
        self.assertEqual(c.target_type, "group")
        self.assertIsNone(c.target_user_id)
        self.assertEqual(c.data_status, "ok")
        self.assertEqual(c.evidence["silence_seconds"], 120.0)

    def test_no_trigger_just_below_threshold(self):
        us = [_u("A", 10.0), _u("B", 100.0)]
        candidates = discussion_stall_candidates("m1", us, now_second=219.9)
        self.assertEqual(candidates, [])

    def test_end_time_counts_for_last_speech(self):
        # end_time 比 timestamp 晚，按 max(end_time, timestamp) 算最后发言时间
        us = [_u("A", 10.0), _u("B", 100.0, end_time=150.0)]
        candidates = discussion_stall_candidates("m1", us, now_second=270.0)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].evidence["last_speech_second"], 150.0)

    def test_insufficient_data_no_trigger(self):
        us = [_u("A", 10.0)]
        self.assertEqual(discussion_stall_candidates("m1", us, now_second=1000.0), [])

    def test_default_now_is_last_utterance(self):
        us = [_u("A", 10.0), _u("B", 100.0)]
        self.assertEqual(discussion_stall_candidates("m1", us), [])

    def test_custom_threshold(self):
        us = [_u("A", 10.0), _u("B", 100.0)]
        config = HintTriggerConfig(stall_silence_seconds=60)
        self.assertEqual(len(discussion_stall_candidates("m1", us, now_second=160.0, config=config)), 1)
        self.assertEqual(discussion_stall_candidates("m1", us, now_second=159.0, config=config), [])


class TestLowParticipation(unittest.TestCase):

    def _three_speaker_scene(self):
        """A 最后发言在 300 秒，B/C 在 400-600 秒之间活跃。"""
        return [
            _u("A", 10.0), _u("A", 300.0),
            _u("B", 400.0), _u("B", 500.0),
            _u("C", 450.0), _u("C", 600.0),
        ]

    def test_zero_speech_rule_triggers(self):
        us = self._three_speaker_scene()
        candidates = low_participation_candidates("m1", us, now_second=660.0)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.target_type, "student")
        self.assertEqual(c.target_user_id, "A")
        self.assertEqual(c.evidence["rule"], "zero_speech")
        self.assertEqual(c.evidence["consecutive_points"], 2)
        self.assertEqual(c.window, {"start_second": 360.0, "end_second": 660.0})
        self.assertEqual(c.dedupe_key, "low_participation:m1:student:A")

    def test_low_ratio_rule_triggers(self):
        us = [
            _u("A", 500.0),
            _u("B", 400.0), _u("B", 410.0), _u("B", 420.0), _u("B", 430.0),
            _u("C", 450.0), _u("C", 460.0), _u("C", 470.0), _u("C", 480.0),
        ]
        candidates = low_participation_candidates("m1", us, now_second=660.0)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.target_user_id, "A")
        self.assertEqual(c.evidence["rule"], "low_ratio")
        self.assertEqual(c.evidence["peer_utterances_mean"], 4.0)

    def test_no_trigger_when_everyone_silent(self):
        # 大家都在最近窗口里没发言：不是某个人的低参与，不产出学生级候选
        us = [_u("A", 10.0), _u("B", 20.0), _u("C", 30.0)]
        self.assertEqual(low_participation_candidates("m1", us, now_second=660.0), [])

    def test_single_known_speaker_no_trigger(self):
        us = [_u("A", 10.0), _u("A", 20.0), _u("A", 30.0)]
        self.assertEqual(low_participation_candidates("m1", us, now_second=660.0), [])

    def test_consecutive_points_required(self):
        # 条件只在当前窗口满足、上一个评估点不满足（A 在上一窗口内还发过言）→ 不触发
        us = [
            _u("A", 10.0), _u("A", 400.0),
            _u("B", 600.0), _u("C", 610.0),
        ]
        self.assertEqual(low_participation_candidates("m1", us, now_second=660.0), [])

    def test_window_boundary_left_open(self):
        # 上一个评估点窗口 (0,300]：A 在 t=0 恰好落在边界上，左开右闭 → 不算
        us = [
            _u("A", 0.0),
            _u("B", 100.0), _u("B", 200.0),
            _u("C", 150.0), _u("C", 250.0),
        ]
        candidates = low_participation_candidates("m1", us, now_second=330.0)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].target_user_id, "A")

    def test_insufficient_total_no_trigger(self):
        self.assertEqual(low_participation_candidates("m1", [_u("A", 10.0)], now_second=660.0), [])


class TestComputeWithCooldown(unittest.TestCase):

    def _stall_scene(self):
        return [_u("A", 10.0), _u("B", 100.0)]

    def test_group_cooldown_suppresses_repeat(self):
        us = self._stall_scene()
        state = HintTriggerState()
        first = compute_hint_candidates("m1", us, now_second=300.0, state=state)
        self.assertEqual(len(first), 1)
        second = compute_hint_candidates("m1", us, now_second=300.0, state=state)
        self.assertEqual(second, [])
        # 冷却期（默认 300 秒）过后重新产出
        third = compute_hint_candidates("m1", us, now_second=600.0, state=state)
        self.assertEqual(len(third), 1)
        self.assertEqual(state.last_fired["discussion_stall:m1:group:all"], 600.0)

    def test_student_cooldown_suppresses_repeat(self):
        us = [
            _u("A", 10.0), _u("A", 300.0),
            _u("B", 400.0), _u("B", 500.0),
            _u("C", 450.0), _u("C", 600.0),
        ]
        state = HintTriggerState()
        first = compute_hint_candidates("m1", us, now_second=660.0, state=state)
        student_candidates = [c for c in first if c.hint_type == "low_participation"]
        self.assertEqual(len(student_candidates), 1)
        # 同一时刻重复评估不重复产出（120 秒学生级冷却）
        second = compute_hint_candidates("m1", us, now_second=660.0, state=state)
        self.assertEqual(
            [c for c in second if c.hint_type == "low_participation"], []
        )

    def test_stall_and_low_participation_can_coexist(self):
        # A 长时间沉默：既是个人低参与，也可能全组停滞（B/C 也停够久时）
        us = [
            _u("A", 10.0), _u("A", 60.0),
            _u("B", 200.0), _u("B", 210.0),
            _u("C", 220.0), _u("C", 230.0),
        ]
        candidates = compute_hint_candidates("m1", us, now_second=400.0)
        types = sorted({c.hint_type for c in candidates})
        # 400-230=170 >= 120 → 停滞；A 在 (100,400] 与 (70,370] 均为 0 发言
        # 且 B/C 有发言 → 低参与。两类候选可以同时产出。
        self.assertEqual(types, ["discussion_stall", "low_participation"])


class TestOnlineMembers(unittest.TestCase):
    """在线名单输入：未提供时从不误判未发言学生；提供时按在线口径判断。"""

    def _scene_with_silent_stranger(self):
        """D 从未发言；A/B/C 在窗口内活跃。"""
        return [
            _u("A", 400.0), _u("A", 500.0),
            _u("B", 420.0), _u("B", 520.0),
            _u("C", 440.0), _u("C", 540.0),
        ]

    def test_no_online_list_never_spoken_student_not_flagged(self):
        # 判断池是已知发言人 {A,B,C}；D 从未发言，不在池内，不会被误判
        us = self._scene_with_silent_stranger()
        candidates = low_participation_candidates("m1", us, now_second=660.0)
        self.assertEqual(candidates, [])

    def test_online_list_can_flag_never_spoken_member(self):
        # 提供在线名单（含 D）：与上游 get_quiet_members 口径一致，D 可被条件1命中
        us = self._scene_with_silent_stranger()
        candidates = low_participation_candidates(
            "m1", us, now_second=660.0, online_members=["A", "B", "C", "D"]
        )
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.target_user_id, "D")
        self.assertEqual(c.evidence["rule"], "zero_speech")

    def test_online_list_without_all_peers_spoken_no_flag(self):
        # D 未发言，但窗口内 B/C 也未发言 → 条件1/2 都不满足，不触发
        us = [
            _u("A", 400.0), _u("A", 500.0),
            _u("B", 100.0), _u("C", 200.0),
        ]
        candidates = low_participation_candidates(
            "m1", us, now_second=660.0, online_members=["A", "B", "C", "D"]
        )
        self.assertEqual(candidates, [])

    def test_empty_online_list_no_candidates(self):
        # 空列表 = 无人在线：不触发学生级候选
        us = self._scene_with_silent_stranger()
        self.assertEqual(
            low_participation_candidates("m1", us, now_second=660.0, online_members=[]),
            [],
        )

    def test_bad_online_members_raises(self):
        us = [_u("A", 10.0), _u("B", 20.0)]
        for bad in ("A,B", [1, 2], ["A", ""]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    low_participation_candidates(
                        "m1", us, now_second=660.0, online_members=bad
                    )

    def test_compute_passthrough_online_members(self):
        us = self._scene_with_silent_stranger()
        candidates = compute_hint_candidates(
            "m1", us, now_second=660.0, online_members=["A", "B", "C", "D"]
        )
        student = [c for c in candidates if c.hint_type == "low_participation"]
        self.assertEqual([c.target_user_id for c in student], ["D"])


class TestValidationAndConfig(unittest.TestCase):

    def test_bad_meeting_id_raises(self):
        with self.assertRaises(ValueError):
            compute_hint_candidates("", [_u("A", 1.0)])

    def test_non_utterance_raises(self):
        with self.assertRaises(ValueError):
            compute_hint_candidates("m1", [{"not": "utterance"}])

    def test_negative_now_raises(self):
        # now_second 是课堂相对秒数，负数属于非法输入，按契约抛 ValueError
        us = [_u("A", 10.0), _u("B", 20.0)]
        for fn in (
            low_participation_candidates,
            discussion_stall_candidates,
            compute_hint_candidates,
        ):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(ValueError):
                    fn("m1", us, now_second=-1.0)

    def test_nonfinite_now_raises(self):
        us = [_u("A", 10.0), _u("B", 20.0)]
        with self.assertRaises(ValueError):
            discussion_stall_candidates("m1", us, now_second=float("nan"))

    def test_bad_ratio_raises(self):
        for ratio in (0.0, 1.0, -0.1):
            with self.subTest(ratio=ratio):
                with self.assertRaises(ValueError):
                    HintTriggerConfig(low_participation_ratio=ratio)

    def test_bad_window_params_raise(self):
        with self.assertRaises(ValueError):
            HintTriggerConfig(sliding_step_seconds=400)

    def test_config_notes_documented(self):
        notes = HintTriggerConfig().NOTES
        self.assertIn("已有代码依据", notes["stall_silence_seconds"])
        self.assertIn("候选配置", notes["consecutive_points_required"])

    def test_candidates_are_protocol_instances(self):
        us = [_u("A", 10.0), _u("B", 100.0)]
        for c in discussion_stall_candidates("m1", us, now_second=300.0):
            self.assertIsInstance(c, HintCandidate)


if __name__ == "__main__":
    unittest.main()
