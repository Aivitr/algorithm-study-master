"""
旧 AMI 语料适配器测试（负责人：陈虹宇）。

验证 conversation_json 旧格式能正确转成统一 Utterance。
"""

import json
import tempfile
import unittest
from pathlib import Path

from gca_engine.adapters.conversation_json import (
    load_conversation_json,
    records_to_utterances,
)


class TestRecordsToUtterances(unittest.TestCase):

    def test_field_mapping(self):
        records = [
            {"dataset": "AMI", "meeting": "EN2002a", "group": "EN2002a",
             "speaker": "A", "start": 0.0, "end": 1.5,
             "message": "Hello, world!", "source": "human"},
            {"dataset": "AMI", "meeting": "EN2002a", "group": "EN2002a",
             "speaker": "B", "start": 2.0, "end": 3.0,
             "message": "Bye!!", "source": "human"},
        ]
        utterances = records_to_utterances(records)
        self.assertEqual(len(utterances), 2)

        u0, u1 = utterances
        self.assertEqual(u0.meeting_id, "EN2002a")
        self.assertEqual(u0.speaker_id, "A")
        self.assertEqual(u0.text, "Hello, world!")
        self.assertEqual(u0.timestamp, 0.0)
        self.assertEqual(u0.end_time, 1.5)
        self.assertEqual(u0.utterance_id, "EN2002a:0000")
        self.assertEqual(u1.utterance_id, "EN2002a:0001")
        self.assertEqual(u1.speaker_id, "B")

    def test_missing_key_raises(self):
        with self.assertRaises(ValueError):
            records_to_utterances([{"meeting": "M1", "speaker": "A"}])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            records_to_utterances({"meeting": "M1"})


class TestLoadConversationJson(unittest.TestCase):

    def test_load_file(self):
        records = [
            {"meeting": "M1", "speaker": "A", "start": 0.0, "end": 1.0,
             "message": "hello"},
            {"meeting": "M1", "speaker": "B", "start": 1.0, "end": 2.0,
             "message": "world"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conversation.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            utterances = load_conversation_json(path)
        self.assertEqual(len(utterances), 2)
        self.assertEqual(utterances[0].meeting_id, "M1")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_conversation_json("no/such/file.json")

    def test_non_list_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conversation.json"
            path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_conversation_json(path)


if __name__ == "__main__":
    unittest.main()
