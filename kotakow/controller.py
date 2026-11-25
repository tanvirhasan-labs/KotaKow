"""Central dictation state machine bridging hotkey hook, audio, chimes, pill, AI, and auto-paste.

State Machine:
- ``IDLE``: waiting for hotkey.
- ``PENDING_HOLD``: hotkey pressed; silent pre-buffer started. If held >= 300ms ->
  ``RECORDING_PTT``. If released < 300ms -> buffer discarded silently (never sent to API)
  and enters ``WAITING_DOUBLE_TAP`` for 400ms.
- ``WAITING_DOUBLE_TAP``: if hotkey pressed again within 400ms -> ``RECORDING_HANDS_FREE``.
  Otherwise expires back to ``IDLE`` with zero API calls.
- ``RECORDING_PTT``: releasing hotkey stops, processes, and auto-pastes.
- ``RECORDING_HANDS_FREE``: once second tap's keys are released, pressing hotkey once again
  OR clicking ``✓`` stops, processes, and auto-pastes.
- ``PROCESSING``: floating pill shows minimal loading animation while DualAIEngine runs.
- Pressing ``Esc`` or clicking ``✕`` in any active state cancels and discards immediately.
"""

from __future__ import annotations

import enum
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from kotakow.ai_engine import AIEngineError, DualAIEngine, TranscriptionResult
from kotakow.audio_capture import AudioRecorder, RecordingResult
from kotakow.autopaste import get_active_app_name, paste_unicode_text
from kotakow.chimes import ChimePlayer
from kotakow.config import AppConfig, ConfigManager
from kotakow.database import Database
from kotakow.hotkey_hook import GlobalHotkeyHook

HOLD_THRESHOLD_MS = 300
DOUBLE_TAP_WINDOW_MS = 400
MIN_AUDIO_DURATION_SEC = 0.30
MIN_AUDIO_PEAK_LEVEL = 0.006


class DictationState(enum.Enum):
    IDLE = "idle"
    PENDING_HOLD = "pending_hold"
    WAITING_DOUBLE_TAP = "waiting_double_tap"
    RECORDING_PTT = "recording_ptt"
    RECORDING_HANDS_FREE = "recording_hands_free"
    PROCESSING = "processing"


class AppController(QObject):
    """Coordinates all Kota Kow runtime components on the Qt main thread."""

    # Internal thread-bridge signals (emitted from hook/audio/worker threads)
    _sig_combo_down = Signal()
    _sig_combo_up = Signal()
    _sig_escape = Signal()
    _sig_audio_level = Signal(float)
    _sig_max_duration = Signal()
    _sig_transcription_done = Signal(int, object, float, str)  # seq, TranscriptionResult, duration, app
    _sig_transcription_error = Signal(int, str)
    _sig_hotkey_captured = Signal(object, str)

    # Public UI signals
    pill_show_recording = Signal()
    pill_show_processing = Signal()
    pill_hide = Signal()
    pill_audio_level = Signal(float)

    state_changed = Signal(str)
    paused_changed = Signal(bool)
    config_changed = Signal(object)  # AppConfig
    history_updated = Signal()
    dictionary_updated = Signal()
    toast_message = Signal(str, str)  # title, message
    hotkey_captured = Signal(object, str)  # list[int] | None, label

    def __init__(self, config_manager: ConfigManager, db: Database) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.db = db
        self.ai_engine = DualAIEngine()

        cfg = self.config_manager.config
        self.chimes = ChimePlayer(enabled=cfg.sound_enabled, volume=cfg.sound_volume)
        self.recorder = AudioRecorder(
            on_level=self._sig_audio_level.emit,
            on_max_duration=self._sig_max_duration.emit,
        )
        self.recorder.set_device(cfg.microphone_device)

        self._state = DictationState.IDLE
        self._paused = False
        self._hands_free_armed = False
        self._ignore_next_combo_up = False
        self._active_app_name = "Unknown"
        self._session_seq = 0
        self._shutdown_done = False

        # Timers run strictly on Qt main thread
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._on_hold_threshold_reached)

        self._double_tap_timer = QTimer(self)
        self._double_tap_timer.setSingleShot(True)
        self._double_tap_timer.timeout.connect(self._on_double_tap_expired)

        # Connect thread-bridge signals (Qt.AutoConnection -> Queued from worker threads)
        self._sig_combo_down.connect(self._handle_combo_down)
        self._sig_combo_up.connect(self._handle_combo_up)
        self._sig_escape.connect(self.cancel_dictation)
        self._sig_audio_level.connect(self._handle_audio_level)
        self._sig_max_duration.connect(self._handle_max_duration)
        self._sig_transcription_done.connect(self._handle_transcription_done)
        self._sig_transcription_error.connect(self._handle_transcription_error)
        self._sig_hotkey_captured.connect(self.hotkey_captured.emit)

        self.hotkey_hook = GlobalHotkeyHook(
            hotkey_vks=cfg.hotkey_vks,
            on_combo_down=self._sig_combo_down.emit,
            on_combo_up=self._sig_combo_up.emit,
            on_escape=self._sig_escape.emit,
            is_escape_active=self._is_escape_active,
        )

    @property
    def config(self) -> AppConfig:
        return self.config_manager.config

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        self.hotkey_hook.start()

    @Slot()
    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._hold_timer.stop()
        self._double_tap_timer.stop()
        self.hotkey_hook.stop()
        self.recorder.cancel()
        self.chimes.shutdown()
        self.db.close()

    def _is_escape_active(self) -> bool:
        return self._state in (
            DictationState.RECORDING_PTT,
            DictationState.RECORDING_HANDS_FREE,
            DictationState.PROCESSING,
        )

    def _set_state(self, new_state: DictationState) -> None:
        self._state = new_state
        self.state_changed.emit(new_state.value)

    # ------------------------------------------------------------------
    # Configuration Updates & Controls
    # ------------------------------------------------------------------

    def apply_config(self, cfg: AppConfig) -> None:
        self.config_manager.save(cfg)
        self.chimes.configure(enabled=cfg.sound_enabled, volume=cfg.sound_volume)
        self.recorder.set_device(cfg.microphone_device)
        self.hotkey_hook.set_hotkey(cfg.hotkey_vks)
        self.config_changed.emit(cfg)

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self.hotkey_hook.set_paused(self._paused)
        if self._paused and self._state != DictationState.IDLE:
            self.cancel_dictation(play_sound=False)
        self.paused_changed.emit(self._paused)

    @Slot()
    def toggle_paused(self) -> None:
        self.set_paused(not self._paused)

    def start_hotkey_capture(self) -> None:
        self.hotkey_hook.start_capture(
            lambda vks, label: self._sig_hotkey_captured.emit(vks, label)
        )

    def cancel_hotkey_capture(self) -> None:
        self.hotkey_hook.cancel_capture()

    @Slot()
    def test_chime(self) -> None:
        self.chimes.play("start", force=True)

    # ------------------------------------------------------------------
    # Hotkey & Pill State Machine
    # ------------------------------------------------------------------

    @Slot()
    def _handle_combo_down(self) -> None:
        if self._paused:
            return

        if self._state == DictationState.IDLE:
            if not self.config.has_any_api_key():
                self.toast_message.emit(
                    "API Key Required",
                    "Add a Gemini or Groq API key in Settings before dictating.",
                )
                return

            self._active_app_name = get_active_app_name()
            self._ignore_next_combo_up = False
            try:
                # Start silent pre-buffering immediately so first syllables are never clipped
                self.recorder.start()
            except Exception as exc:
                self.toast_message.emit("Microphone Error", str(exc))
                return

            self._set_state(DictationState.PENDING_HOLD)
            self._hold_timer.start(HOLD_THRESHOLD_MS)
            return

        if self._state == DictationState.WAITING_DOUBLE_TAP:
            # Second tap within 400ms -> Hands-Free Lock ON!
            self._double_tap_timer.stop()
            self._active_app_name = get_active_app_name()
            try:
                self.recorder.start()
            except Exception as exc:
                self._set_state(DictationState.IDLE)
                self.toast_message.emit("Microphone Error", str(exc))
                return

            self._hands_free_armed = False
            self._ignore_next_combo_up = False
            self._set_state(DictationState.RECORDING_HANDS_FREE)
            self.chimes.play("start")
            self.pill_show_recording.emit()
            return

        if self._state == DictationState.RECORDING_HANDS_FREE and self._hands_free_armed:
            # Pressing hotkey once again in Hands-Free mode stops & pastes
            self._ignore_next_combo_up = True
            self.confirm_and_stop()

    @Slot()
    def _handle_combo_up(self) -> None:
        if self._ignore_next_combo_up:
            self._ignore_next_combo_up = False
            return

        if self._state == DictationState.PENDING_HOLD:
            # Released before 300ms -> quick tap! Discard pre-buffer silently (NO API call!)
            self._hold_timer.stop()
            self.recorder.cancel()
            self._set_state(DictationState.WAITING_DOUBLE_TAP)
            self._double_tap_timer.start(DOUBLE_TAP_WINDOW_MS)
            return

        if self._state == DictationState.RECORDING_PTT:
            self.confirm_and_stop()
            return

        if self._state == DictationState.RECORDING_HANDS_FREE:
            # Double-tap keys released; now armed for single-press stop
            self._hands_free_armed = True

    @Slot()
    def _on_hold_threshold_reached(self) -> None:
        if self._state != DictationState.PENDING_HOLD:
            return
        self._set_state(DictationState.RECORDING_PTT)
        self.chimes.play("start")
        self.pill_show_recording.emit()

    @Slot()
    def _on_double_tap_expired(self) -> None:
        if self._state == DictationState.WAITING_DOUBLE_TAP:
            self._set_state(DictationState.IDLE)

    @Slot(float)
    def _handle_audio_level(self, level: float) -> None:
        if self._state in (DictationState.RECORDING_PTT, DictationState.RECORDING_HANDS_FREE):
            self.pill_audio_level.emit(level)

    @Slot()
    def _handle_max_duration(self) -> None:
        if self._state in (DictationState.RECORDING_PTT, DictationState.RECORDING_HANDS_FREE):
            self.toast_message.emit("5-Minute Limit Reached", "Processing your dictation now.")
            self.confirm_and_stop()

    @Slot()
    def confirm_and_stop(self) -> None:
        """Stop recording, play stop chime, and send in-memory WAV to Dual AI Engine."""
        if self._state not in (DictationState.RECORDING_PTT, DictationState.RECORDING_HANDS_FREE):
            return

        self._hold_timer.stop()
        self._double_tap_timer.stop()
        self._hands_free_armed = False

        result: RecordingResult = self.recorder.stop()

        # Guard against empty/near-silent clips
        if (
            not result.wav_bytes
            or result.duration_sec < MIN_AUDIO_DURATION_SEC
            or result.peak_level < MIN_AUDIO_PEAK_LEVEL
        ):
            self.chimes.play("cancel")
            self.pill_hide.emit()
            self._set_state(DictationState.IDLE)
            return

        self.chimes.play("stop")
        self._set_state(DictationState.PROCESSING)
        self.pill_show_processing.emit()

        self._session_seq += 1
        seq = self._session_seq
        cfg_snapshot = AppConfig.from_dict(self.config.to_dict())
        dict_terms = self.db.get_dictionary_term_strings()
        target_app = self._active_app_name or "Unknown"
        wav_bytes = result.wav_bytes
        duration_sec = result.duration_sec

        def _worker() -> None:
            try:
                tx_result = self.ai_engine.transcribe(
                    wav_bytes=wav_bytes,
                    config=cfg_snapshot,
                    dictionary_terms=dict_terms,
                )
                self._sig_transcription_done.emit(seq, tx_result, duration_sec, target_app)
            except AIEngineError as exc:
                self._sig_transcription_error.emit(seq, str(exc))
            except Exception as exc:
                self._sig_transcription_error.emit(seq, f"Unexpected error: {exc}")

        threading.Thread(target=_worker, name="KotaKow-AIWorker", daemon=True).start()

    @Slot()
    def cancel_dictation(self, play_sound: bool = True) -> None:
        """Cancel active recording or discard in-flight transcription."""
        if self._state == DictationState.IDLE:
            return
        self._hold_timer.stop()
        self._double_tap_timer.stop()
        self._hands_free_armed = False
        self._session_seq += 1  # Invalidates any in-flight worker result
        self.recorder.cancel()
        if play_sound:
            self.chimes.play("cancel")
        self.pill_hide.emit()
        self._set_state(DictationState.IDLE)

    # ------------------------------------------------------------------
    # Transcription Completion -> Auto-Paste & SQLite Logging
    # ------------------------------------------------------------------

    @Slot(int, object, float, str)
    def _handle_transcription_done(
        self,
        seq: int,
        tx_result: TranscriptionResult,
        duration_sec: float,
        target_app: str,
    ) -> None:
        if seq != self._session_seq:
            return  # User cancelled while processing

        self.pill_hide.emit()
        self._set_state(DictationState.IDLE)

        # Record API usage regardless of empty output (an API request was made)
        self.db.increment_api_usage(tx_result.engine)

        final_text = (tx_result.text or "").strip()
        if not final_text:
            self.history_updated.emit()
            return

        # Re-check active app right before pasting if initial was Unknown/Kota Kow
        current_app = get_active_app_name()
        app_to_log = current_app if current_app not in ("Unknown", "Desktop", "Kota Kow") else target_app

        # Perform Unicode auto-paste off the Qt UI thread so 60ms sleep never blocks UI
        def _do_paste() -> None:
            time.sleep(0.025)  # Tiny grace window after pill hides
            paste_unicode_text(final_text)

        threading.Thread(target=_do_paste, name="KotaKow-AutoPaste", daemon=True).start()

        self.db.add_dictation(
            text=final_text,
            duration_sec=duration_sec,
            app_name=app_to_log,
            engine=tx_result.engine,
            language_mode=self.config.language_mode,
        )
        self.history_updated.emit()

    @Slot(int, str)
    def _handle_transcription_error(self, seq: int, error_msg: str) -> None:
        if seq != self._session_seq:
            return
        self.pill_hide.emit()
        self._set_state(DictationState.IDLE)
        self.chimes.play("cancel")
        self.toast_message.emit("Dictation Error", error_msg)
