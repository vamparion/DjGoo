from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import sounddevice as sd

try:
    from scipy.signal import butter, resample_poly, sosfilt
except ImportError:  # pragma: no cover - fallback for an incomplete local install
    butter = None
    resample_poly = None
    sosfilt = None


WHISPER_SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class AudioMetrics:
    seconds: float
    rms: float
    peak: float
    source_sample_rate: int


class PushToTalkAudioCapture:
    """Keep one input stream open so hotkey boundaries never drop syllables."""

    def __init__(
        self,
        *,
        device: int | str | None,
        block_seconds: float = 0.02,
        preroll_seconds: float = 0.25,
        release_tail_seconds: float = 0.18,
    ) -> None:
        info = sd.query_devices(device, "input")
        self.device = device
        self.sample_rate = int(float(info.get("default_samplerate") or WHISPER_SAMPLE_RATE))
        self.block_seconds = max(0.01, float(block_seconds))
        self.block_frames = max(1, int(self.sample_rate * self.block_seconds))
        self.release_tail_seconds = max(0.0, float(release_tail_seconds))
        preroll_blocks = max(1, math.ceil(max(0.0, preroll_seconds) / self.block_seconds))
        self._preroll: deque[np.ndarray] = deque(maxlen=preroll_blocks)
        self._captured: list[np.ndarray] = []
        self._recording = False
        self._lock = threading.RLock()
        self._stream: sd.InputStream | None = None
        self.last_status = ""

    def __enter__(self) -> "PushToTalkAudioCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_frames,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        stream.stop()
        stream.close()

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        del frames, time_info
        chunk = np.asarray(indata[:, 0], dtype=np.float32).copy()
        with self._lock:
            if status:
                self.last_status = str(status)
            self._preroll.append(chunk)
            if self._recording:
                self._captured.append(chunk)

    def begin(self) -> None:
        with self._lock:
            self._captured = [chunk.copy() for chunk in self._preroll]
            self._recording = True

    def finish(self) -> np.ndarray:
        if self.release_tail_seconds:
            time.sleep(self.release_tail_seconds)
        with self._lock:
            self._recording = False
            chunks = self._captured
            self._captured = []
        if not chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def record_for(self, seconds: float) -> np.ndarray:
        self.begin()
        time.sleep(max(self.block_seconds, float(seconds)))
        return self.finish()


def prepare_for_whisper(
    audio: np.ndarray,
    source_sample_rate: int,
    *,
    target_sample_rate: int = WHISPER_SAMPLE_RATE,
) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return samples

    samples = samples - float(np.mean(samples))
    if source_sample_rate != target_sample_rate:
        if resample_poly is not None:
            divisor = math.gcd(int(source_sample_rate), int(target_sample_rate))
            samples = resample_poly(
                samples,
                target_sample_rate // divisor,
                source_sample_rate // divisor,
            ).astype(np.float32, copy=False)
        else:
            target_size = max(1, int(samples.size * target_sample_rate / source_sample_rate))
            source_axis = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
            target_axis = np.linspace(0.0, 1.0, num=target_size, endpoint=False)
            samples = np.interp(target_axis, source_axis, samples).astype(np.float32)

    if butter is not None and sosfilt is not None and samples.size >= 256:
        high_pass = butter(2, 80, btype="highpass", fs=target_sample_rate, output="sos")
        samples = sosfilt(high_pass, samples).astype(np.float32, copy=False)

    peak = float(np.quantile(np.abs(samples), 0.995)) if samples.size else 0.0
    if peak > 0:
        gain = min(8.0, 0.90 / peak)
        samples = np.clip(samples * gain, -1.0, 1.0)
    return samples.astype(np.float32, copy=False)


def audio_metrics(audio: np.ndarray, sample_rate: int) -> AudioMetrics:
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return AudioMetrics(0.0, 0.0, 0.0, sample_rate)
    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples)))
    return AudioMetrics(samples.size / float(sample_rate), rms, peak, sample_rate)
