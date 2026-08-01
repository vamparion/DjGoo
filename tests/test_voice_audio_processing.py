from __future__ import annotations

import numpy as np

from voice.audio_capture import audio_metrics, prepare_for_whisper


def test_prepare_for_whisper_resamples_and_normalizes() -> None:
    source_rate = 48_000
    seconds = 0.5
    axis = np.arange(int(source_rate * seconds), dtype=np.float32) / source_rate
    audio = 0.02 * np.sin(2 * np.pi * 440 * axis) + 0.03
    prepared = prepare_for_whisper(audio, source_rate)
    metrics = audio_metrics(prepared, 16_000)
    assert 7_900 <= prepared.size <= 8_100
    assert abs(float(np.mean(prepared))) < 0.02
    assert 0.2 < metrics.peak <= 1.0


def test_empty_audio_is_safe() -> None:
    prepared = prepare_for_whisper(np.array([], dtype=np.float32), 48_000)
    assert prepared.size == 0
    assert audio_metrics(prepared, 16_000).rms == 0.0
