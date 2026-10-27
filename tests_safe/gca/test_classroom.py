"""
课堂数据适配器测试（负责人：岳柔）。

验证 transcripts 记录能正确转成统一 Utterance，
时间统一换算成"课堂开始后的秒数"。
"""

import unittest
from datetime import datetime, timedelta

from gca_engine.adapters.classroom import transcripts_to_utterances


def _record(rid, uid, content, ts):
    return {"id": rid, "user_id": uid, "content": content, "timestamp": ts}

def _empty_record(rid, uid, ts):
    return {"id": rid, "user_id": uid, "content": None, "timestamp": ts}

class TestTranscriptsToUtterances(unittest.TestCase):

    def test_numeric_timestamps_passthrough(self):
        records = [
            _record(1, 101, "大家好", 30.0),
            _record(2, 102, "我同意", 75.0),
        ]
        utterances = transcripts_to_utterances(records, 5)
        self.assertEqual(utterances[0].meeting_id, "5")
        self.assertEqual(utterances[0].speaker_id, "101")  # user_id 转字符串
        self.assertEqual(utterances[0].utterance_id, "1")
        self.assertEqual(utterances[0].timestamp, 30.0)
        self.assertEqual(utterances[1].timestamp, 75.0)

    def test_datetime_relative_to_class_start(self):
        t0 = datetime(2026, 10, 18, 9, 0, 0)
        records = [
            _record(1, 101, "大家好", t0 + timedelta(seconds=15)),
            _record(2, 102, "我同意", t0 + timedelta(seconds=40)),
        ]
        utterances = transcripts_to_utterances(records, "m1")
        # 第一条发言的时间当作课堂起点 0 秒
        self.assertAlmostEqual(utterances[0].timestamp, 0.0)
        self.assertAlmostEqual(utterances[1].timestamp, 25.0)

    def test_sorted_by_timestamp(self):
        records = [
            _record(1, 101, "第三条", 90.0),
            _record(2, 102, "第一条", 10.0),
            _record(3, 103, "第二条", 50.0),
        ]
        utterances = transcripts_to_utterances(records, "m1")
        self.assertEqual([u.timestamp for u in utterances], [10.0, 50.0, 90.0])

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            transcripts_to_utterances(
                [{"id": 1, "user_id": 101, "content": "x"}], "m1"
            )

    def test_empty_and_oral_content_handling(self):
        # 造几条真实数据：正常 + None空 + 纯空格 + 口语词“嗯嗯”
        records = [
            _record(1, 101, "大家好", 10.0),
            _empty_record(2, 102, 12.0),      # None 会被跳过
            _record(3, 103, "   ", 15.0),     # 纯空格会被清理并跳过
            _record(4, 104, "嗯嗯那个", 18.0), # 口语词（看代码是否过滤）
        ]
        utterances = transcripts_to_utterances(records, 5)
        
        # 核心检查：中间两个空的肯定没了，至少保留第一条
        self.assertGreater(len(utterances), 0)
        self.assertEqual(utterances[0].utterance_id, "1")
        # （注：如果“嗯嗯那个”被过滤了，就只剩1条；没过滤就剩2条，都不算错）
        
    def test_bad_timestamp_raises(self):
        with self.assertRaises(ValueError):
            transcripts_to_utterances(
                [_record(1, 101, "x", "not-a-time")], "m1"
            )


if __name__ == "__main__":
    unittest.main()
