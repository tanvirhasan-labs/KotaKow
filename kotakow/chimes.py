"""In-memory synthesized chimes (Wispr Flow aesthetic) using numpy + sounddevice.

No external WAV/MP3 files are required. Tones are generated mathematically in
RAM and played asynchronously on a dedicated background daemon thread so
recording startup is never delayed.
"""

from __future__ import annotations

import queue
import threading
from typing import Literal

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None  # type: ignore[assignment]

ChimeKind = Literal["start", "stop", "cancel"]

_SAMPLE_RATE = 44100


def _soft_tone(freq_hz: float, duration_s: float, gain: float = 0.28) -> np.ndarray:
    """Synthesize a warm, click-free tone with gentle harmonic shimmer."""
    n = int(_SAMPLE_RATE * duration_s)
    t = np.linspace(0.0, duration_s, n, endpoint=False, dtype=np.float32)

    # Fundamental + subtle octave harmonic for glassy acoustic warmth
    wave = (
        0.82 * np.sin(2.0 * np.pi * freq_hz * t)
        + 0.18 * np.sin(2.0 * np.pi * (freq_hz * 2.0) * t)
    )

    # Smooth attack (10ms) and exponential-cosine release (zero clicks)
    attack_n = max(1, int(_SAMPLE_RATE * 0.010))
    env = np.ones(n, dtype=np.float32)
    env[:attack_n] = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0.0, 1.0, attack_n, dtype=np.float32)))
    decay = np.exp(-3.2 * (t / max(duration_s, 1e-4))).astype(np.float32)
    tail_n = max(1, int(_SAMPLE_RATE * 0.022))
    tail = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0.0, 1.0, tail_n, dtype=np.float32)))
    env[-tail_n:] *= tail

    return (wave * env * decay * gain).astype(np.float32)


def _overlap_tones(tones: list[tuple[float, np.ndarray]]) -> np.ndarray:
    """Mix (start_time_s, samples) pairs into a single float32 mono buffer."""
    total_len = max(int(offset * _SAMPLE_RATE) + len(buf) for offset, buf in tones)
    out = np.zeros(total_len, dtype=np.float32)
    for offset, buf in tones:
        start = int(offset * _SAMPLE_RATE)
        out[start : start + len(buf)] += buf
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0.95:
        out *= 0.95 / peak
    return out


def _build_chimes() -> dict[ChimeKind, np.ndarray]:
    # Start: bright, gentle rising two-note interval (C5 -> E5)
    start_buf = _overlap_tones(
        [
            (0.000, _soft_tone(523.25, 0.075, gain=0.26)),
            (0.048, _soft_tone(659.25, 0.115, gain=0.30)),
        ]
    )
    # Stop: soft confirming descending interval (E5 -> B4)
    stop_buf = _overlap_tones(
        [
            (0.000, _soft_tone(659.25, 0.070, gain=0.24)),
            (0.045, _soft_tone(493.88, 0.115, gain=0.26)),
        ]
    )
    # Cancel: muted, subtle low dismissal (D4 -> A3)
    cancel_buf = _overlap_tones(
        [
            (0.000, _soft_tone(293.66, 0.065, gain=0.22)),
            (0.042, _soft_tone(220.00, 0.095, gain=0.22)),
        ]
    )
    return {"start": start_buf, "stop": stop_buf, "cancel": cancel_buf}


class ChimePlayer:
    """Non-blocking synthesized chime player with enable & volume controls."""

    def __init__(self, enabled: bool = True, volume: int = 65) -> None:
        self.enabled = bool(enabled)
        self.volume = max(0, min(100, int(volume)))
        self._chimes = _build_chimes()
        self._queue: queue.Queue[tuple[ChimeKind, float]] = queue.Queue(maxsize=6)
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._loop, name="KotaKow-Chimes", daemon=True)
        self._worker.start()

    def configure(self, enabled: bool, volume: int) -> None:
        self.enabled = bool(enabled)
        self.volume = max(0, min(100, int(volume)))

    def play(self, kind: ChimeKind, force: bool = False) -> None:
        if not force and not self.enabled:
            return
        if self.volume <= 0 or sd is None:
            return
        gain = (self.volume / 100.0) ** 1.35  # Perceptual volume curve
        try:
            self._queue.put_nowait((kind, gain))
        except queue.Full:
            pass

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                kind, gain = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            buf = self._chimes.get(kind)
            if buf is None or sd is None:
                continue
            try:
                scaled = (buf * gain).reshape(-1, 1)
                with sd.OutputStream(
                    samplerate=_SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    latency="low",
                ) as stream:
                    stream.write(scaled)
            except Exception:
                # Never crash dictation if audio output device is temporarily busy
                pass

    def shutdown(self) -> None:
        self._stop_event.set()
