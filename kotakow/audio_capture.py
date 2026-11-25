"""In-memory 16kHz 16-bit mono WAV microphone recorder (zero FFmpeg, zero disk files).

Audio frames are captured directly into RAM via ``sounddevice`` + ``numpy``
and encoded with Python's built-in ``wave`` module into an ``io.BytesIO``
buffer. Buffers are explicitly wiped as soon as recording stops or cancels so
audio is never persisted to disk.
"""

from __future__ import annotations

import io
import math
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None  # type: ignore[assignment]


SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORDING_SECONDS = 300.0  # 5 minutes


@dataclass
class AudioDeviceInfo:
    index: int | None
    name: str
    hostapi: str = ""


def list_input_devices() -> list[AudioDeviceInfo]:
    """Return available Windows microphone input devices with System Default first."""
    devices = [AudioDeviceInfo(index=None, name="System Default")]
    if sd is None:
        return devices

    try:
        all_devs = sd.query_devices()
        hostapis = sd.query_hostapis()
        default_api = sd.default.hostapi
    except Exception:
        return devices

    seen_names: set[str] = set()
    # Prefer devices from the default host API first, then others
    ordered_indices = sorted(
        range(len(all_devs)),
        key=lambda i: (0 if all_devs[i].get("hostapi") == default_api else 1, i),
    )

    for idx in ordered_indices:
        dev = all_devs[idx]
        if int(dev.get("max_input_channels", 0)) <= 0:
            continue
        raw_name = str(dev.get("name", "")).strip()
        if not raw_name:
            continue
        # Skip generic Windows sound-mapper pseudo entries
        if raw_name.lower() in ("microsoft sound mapper - input", "primary sound capture driver"):
            continue
        api_idx = int(dev.get("hostapi", 0))
        api_name = str(hostapis[api_idx].get("name", "")) if 0 <= api_idx < len(hostapis) else ""
        norm_key = raw_name.lower()
        if norm_key in seen_names:
            continue
        seen_names.add(norm_key)
        devices.append(AudioDeviceInfo(index=idx, name=raw_name, hostapi=api_name))

    return devices


def resolve_device_index(device_name: str) -> int | None:
    """Resolve a saved microphone device name to its current sounddevice index."""
    clean = (device_name or "").strip()
    if not clean or clean.lower() == "system default" or sd is None:
        return None
    for dev in list_input_devices():
        if dev.name == clean:
            return dev.index
    return None


@dataclass
class RecordingResult:
    wav_bytes: bytes
    duration_sec: float
    peak_level: float


class AudioRecorder:
    """Records 16kHz 16-bit mono PCM entirely in memory."""

    def __init__(
        self,
        on_level: Callable[[float], None] | None = None,
        on_max_duration: Callable[[], None] | None = None,
    ) -> None:
        self._on_level = on_level
        self._on_max_duration = on_max_duration
        self._lock = threading.Lock()
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._start_time = 0.0
        self._peak_level = 0.0
        self._max_triggered = False
        self._device_name = ""

    def set_device(self, device_name: str) -> None:
        self._device_name = device_name or ""

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is unavailable on this system.")

        with self._lock:
            if self._recording:
                return
            self._chunks = []
            self._peak_level = 0.0
            self._max_triggered = False
            self._start_time = time.monotonic()
            device_idx = resolve_device_index(self._device_name)

            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=512,  # ~32ms frames -> smooth ~31Hz waveform updates
                    device=device_idx,
                    callback=self._audio_callback,
                )
                stream.start()
            except Exception:
                # Fallback to system default device if saved microphone was unplugged
                if device_idx is not None:
                    stream = sd.InputStream(
                        samplerate=SAMPLE_RATE,
                        channels=CHANNELS,
                        dtype="int16",
                        blocksize=512,
                        device=None,
                        callback=self._audio_callback,
                    )
                    stream.start()
                else:
                    raise

            self._stream = stream
            self._recording = True

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        chunk = indata.copy()
        should_notify_max = False
        with self._lock:
            if not self._recording:
                return
            self._chunks.append(chunk)
            elapsed = time.monotonic() - self._start_time
            if elapsed >= MAX_RECORDING_SECONDS and not self._max_triggered:
                self._max_triggered = True
                should_notify_max = True

        # Compute perceptual RMS level in 0.0..1.0 for live waveform bars
        float_samples = chunk.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(float_samples * float_samples))) if len(float_samples) else 0.0
        # Gentle perceptual boost so normal speech fills 0.25..0.90 nicely
        level = min(1.0, math.sqrt(max(0.0, rms) * 6.5))
        if level > self._peak_level:
            self._peak_level = level

        if self._on_level is not None:
            try:
                self._on_level(level)
            except Exception:
                pass

        if should_notify_max and self._on_max_duration is not None:
            threading.Thread(target=self._on_max_duration, daemon=True).start()

    def stop(self) -> RecordingResult:
        """Stop capture, encode WAV in memory, and wipe raw PCM buffers immediately."""
        with self._lock:
            stream = self._stream
            self._stream = None
            self._recording = False
            chunks = self._chunks
            self._chunks = []
            duration = max(0.0, time.monotonic() - self._start_time) if self._start_time else 0.0
            peak = self._peak_level
            self._peak_level = 0.0

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        if not chunks:
            return RecordingResult(wav_bytes=b"", duration_sec=duration, peak_level=0.0)

        pcm = np.concatenate(chunks, axis=0)
        chunks.clear()
        actual_duration = len(pcm) / float(SAMPLE_RATE)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit signed PCM
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())

        wav_bytes = buf.getvalue()
        buf.close()
        del pcm
        return RecordingResult(
            wav_bytes=wav_bytes,
            duration_sec=max(actual_duration, duration),
            peak_level=peak,
        )

    def cancel(self) -> None:
        """Stop capture and immediately discard all audio from RAM."""
        with self._lock:
            stream = self._stream
            self._stream = None
            self._recording = False
            self._chunks.clear()
            self._peak_level = 0.0

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
