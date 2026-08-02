from __future__ import annotations

import numpy as np

from voice.audio_capture import pad_audio_to_minimum
from voice.listener_settings import voice_settings


def test_legacy_push_to_talk_values_receive_balanced_effective_tuning(tmp_path) -> None:
    settings = voice_settings(
        {
            "beam_size": 8,
            "vad_filter": True,
            "min_record_seconds": 0.25,
        },
        tmp_path,
    )

    assert settings["beam_size"] == 8
    assert settings["hotkey_beam_size"] == 3
    assert settings["recognition_retry_beam_size"] == 5
    assert settings["hotkey_vad_filter"] is False
    assert settings["hotkey_min_record_seconds"] == 0.90
    assert settings["short_audio_pad_seconds"] == 1.25


def test_explicit_hotkey_tuning_is_respected(tmp_path) -> None:
    settings = voice_settings(
        {
            "beam_size": 6,
            "hotkey_beam_size": 2,
            "recognition_retry_beam_size": 4,
            "hotkey_vad_filter": True,
            "min_record_seconds": 1.1,
            "hotkey_min_record_seconds": 0.5,
            "short_audio_pad_seconds": 1.5,
        },
        tmp_path,
    )

    assert settings["hotkey_beam_size"] == 2
    assert settings["recognition_retry_beam_size"] == 4
    assert settings["hotkey_vad_filter"] is True
    assert settings["hotkey_min_record_seconds"] == 1.1
    assert settings["short_audio_pad_seconds"] == 1.5


def test_short_audio_is_padded_symmetrically_without_changing_signal() -> None:
    audio = np.array([0.25, -0.5, 0.75, -1.0], dtype=np.float32)

    padded = pad_audio_to_minimum(audio, sample_rate=8, minimum_seconds=1.0)

    assert padded.dtype == np.float32
    assert padded.shape == (8,)
    np.testing.assert_array_equal(padded[2:6], audio)
    np.testing.assert_array_equal(padded[:2], np.zeros(2, dtype=np.float32))
    np.testing.assert_array_equal(padded[6:], np.zeros(2, dtype=np.float32))


def test_long_audio_is_not_copied_or_padded() -> None:
    audio = np.ones(16, dtype=np.float32)

    padded = pad_audio_to_minimum(audio, sample_rate=8, minimum_seconds=1.0)

    assert padded is audio
