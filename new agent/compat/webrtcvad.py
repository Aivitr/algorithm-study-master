# -*- coding: utf-8 -*-
"""Pure-Python stand-in for the `webrtcvad` C extension.

Why this file exists
--------------------
`resemblyzer` (imported by `voiceprint_manager`) does `import webrtcvad` at
module import time, and the real `webrtcvad` package has no wheel for CPython
3.12+ on Windows, so `pip install webrtcvad` fails with::

    error: Microsoft Visual C++ 14.0 or greater is required.

Only two API pieces are actually used by this project:

* ``webrtcvad.Vad(mode=0..3).is_speech(pcm16_bytes, sample_rate)``
* ``webrtcvad.valid_rate_and_frame_length(rate, frame_length)``

This module implements those with an adaptive energy + zero-crossing-rate
heuristic over 10/20/30 ms 16-bit mono frames. It is NOT the WebRTC reference
detector: the speech/silence decision is coarser, so the long-silence trimming
inside ``resemblyzer.preprocess_wav`` is slightly less precise. Voiceprint
embedding quality itself is unaffected.

Install (whenever the venv is rebuilt)::

    copy compat\webrtcvad.py venv\Lib\site-packages\webrtcvad.py
"""

import math
import struct

SUPPORTED_RATES = (8000, 16000, 32000, 48000)
FRAME_LENGTHS_MS = (10, 20, 30)

# dBFS threshold clamp. Speech in this project is normalised to about
# -30 dBFS before VAD runs, silence sits far below -60 dBFS, so keeping the
# verdict threshold inside this band avoids both over-trimming and passing
# the noise floor through as speech.
MIN_THRESHOLD_DBFS = -70.0
MAX_THRESHOLD_DBFS = -35.0
INITIAL_NOISE_FLOOR_DBFS = -70.0


def _frame_samples(sample_rate, frame_length_ms):
    return sample_rate * frame_length_ms // 1000


def valid_rate_and_frame_length(rate, frame_length):
    """Mirror of the upstream helper: is this (rate, frame) pair supported?"""
    if rate not in SUPPORTED_RATES:
        return False
    return any(frame_length == _frame_samples(rate, ms) for ms in FRAME_LENGTHS_MS)


class Vad(object):
    """Drop-in replacement for ``webrtcvad.Vad`` (energy/ZCR heuristic)."""

    #: Extra dB above the noise floor required before a frame counts as speech.
    _MARGIN_DB = {0: 3.0, 1: 5.0, 2: 7.0, 3: 9.0}

    def __init__(self, mode=None):
        self._mode = 3 if mode is None else int(mode)
        if not 0 <= self._mode <= 3:
            raise ValueError("mode must be an integer between 0 and 3")
        self._noise_floor_dbfs = INITIAL_NOISE_FLOOR_DBFS
        self._seen_frames = 0

    def set_mode(self, mode):
        mode = int(mode)
        if not 0 <= mode <= 3:
            raise ValueError("mode must be an integer between 0 and 3")
        self._mode = mode

    def is_speech(self, buf, sample_rate, length=None):
        if sample_rate not in SUPPORTED_RATES:
            raise ValueError("sample_rate must be one of %s" % (SUPPORTED_RATES,))
        if buf is None:
            raise ValueError("buf must be a bytes-like object of 16-bit PCM")

        available = len(buf) // 2
        expected = [_frame_samples(sample_rate, ms) for ms in FRAME_LENGTHS_MS]
        samples = available if length is None else int(length)
        if samples not in expected or samples == 0:
            raise ValueError(
                "frame length must be 10, 20 or 30 ms for sample_rate %d "
                "(got %d samples)" % (sample_rate, samples)
            )
        if samples > available:
            raise IndexError(
                "buffer has %d frames, but length argument was %d" % (available, samples)
            )

        data = struct.unpack("<%dh" % samples, bytes(buf[: samples * 2]))

        total = 0
        crossings = 0
        previous = data[0]
        for value in data:
            total += value * value
            if (value >= 0) != (previous >= 0):
                crossings += 1
            previous = value

        rms = math.sqrt(total / samples) if total else 0.0
        dbfs = 20.0 * math.log10(rms / 32768.0) if rms > 0 else -120.0
        zcr = crossings / float(samples)

        self._seen_frames += 1
        if dbfs < self._noise_floor_dbfs:
            # Track the floor downwards quickly so real silence is absorbed.
            self._noise_floor_dbfs = 0.7 * self._noise_floor_dbfs + 0.3 * dbfs
        elif self._seen_frames > 1:
            # Rise only very slowly: a loud utterance must not drag the floor
            # up with it and silence the whole recording.
            self._noise_floor_dbfs += 0.01 * (dbfs - self._noise_floor_dbfs)

        threshold = self._noise_floor_dbfs + self._MARGIN_DB[self._mode]
        threshold = min(max(threshold, MIN_THRESHOLD_DBFS), MAX_THRESHOLD_DBFS)

        if dbfs <= threshold:
            return False
        # Unvoiced fricatives stay below ~60% sign changes per frame; steady
        # broadband noise usually crosses more often.
        return zcr <= 0.6
