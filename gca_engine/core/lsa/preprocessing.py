"""
Text preprocessing —— 从 ami_parser 原样迁移（旧基线）。

Deliberately minimal and transparent: HTML-entity decoding, lowercasing,
punctuation removal, whitespace normalization.  No stemming, no
lemmatization, no stop-word removal here (stop words are a vectorizer-level
option, off by default).

Raw conversation text is never mutated: callers keep ``raw_text`` and store
the result of :func:`clean_text` separately as ``processed_text``.
"""

import html
import logging
import re

logger = logging.getLogger(__name__)

# Applied to lowercased text: remove anything that is not a word character
# (unicode letters/digits/underscore) or whitespace.  Apostrophes and other
# punctuation become spaces, so "you've" -> "you ve".
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(
    text: str | None,
    lowercase: bool = True,
    remove_punctuation: bool = True,
) -> str:
    """Normalize one raw utterance text for LSA.

    Args:
        text:                Raw text (None is treated as empty).
        lowercase:           Lowercase the text.
        remove_punctuation:  Replace punctuation characters with spaces.

    Returns:
        Cleaned text with single-space token separation.  Returns ``""``
        for None or empty input.
    """
    if text is None:
        return ""

    t = html.unescape(text)
    if lowercase:
        t = t.lower()
    if remove_punctuation:
        t = _PUNCT_RE.sub(" ", t)
    t = _WHITESPACE_RE.sub(" ", t).strip()
    return t


def tokenize(
    text: str | None,
    lowercase: bool = True,
    remove_punctuation: bool = True,
) -> list[str]:
    """Tokenize one raw utterance text.

    Returns:
        List of tokens (possibly empty if the text had no content).
    """
    cleaned = clean_text(text, lowercase=lowercase, remove_punctuation=remove_punctuation)
    if not cleaned:
        return []
    return cleaned.split(" ")
