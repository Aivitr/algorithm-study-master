"""数据适配器：把不同来源的数据转成统一 Utterance（schemas.py）。"""

from gca_engine.adapters.classroom import transcripts_to_utterances
from gca_engine.adapters.conversation_json import (
    load_conversation_json,
    records_to_utterances,
)

__all__ = ["transcripts_to_utterances", "load_conversation_json", "records_to_utterances"]
