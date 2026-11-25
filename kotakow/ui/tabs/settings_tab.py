"""Settings tab: BYOK API keys, dynamic model fetching, language modes, hotkey recorder, audio, accent & startup."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from kotakow.ai_engine import AIEngineError, fetch_gemini_models, fetch_groq_models
from kotakow.audio_capture import list_input_devices
from kotakow.config import (
    ACCENT_PRESETS,
    DEFAULT_ADVANCED_PROMPT,
    DEFAULT_HOTKEY_LABEL,
    DEFAULT_HOTKEY_VKS,
    is_startup_enabled,
    set_startup_enabled,
)
from kotakow.controller import AppController


class SettingsTab(QWidget):
    """Complete BYOK configuration screen for Kota Kow."""

    _sig_gemini_models = Signal(bool, object, str)  # ok, list[str], message
    _sig_groq_models = Signal(bool, object, str)    # ok, list[str], message

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self._loading_ui = True
        self._recording_hotkey = False
        self._accent_buttons: dict[str, QPushButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(26, 18, 26, 28)
        self._layout.setSpacing(16)
        scroll.setWidget(body)

        self._build_ai_section()
        self._build_language_section()
        self._build_hotkey_audio_section()
        self._build_appearance_system_section()
        self._build_advanced_prompt_section()
        self._layout.addStretch()

        # Connect async model-fetch callbacks & hotkey capture
        self._sig_gemini_models.connect(self._on_gemini_models_fetched)
        self._sig_groq_models.connect(self._on_groq_models_fetched)
        self.controller.hotkey_captured.connect(self._on_hotkey_captured)

        self._populate_from_config()
        self._loading_ui = False

    @staticmethod
    def _make_section_card(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(10)

        hdr = QLabel(title)
        hdr.setObjectName("SectionTitle")
        lay.addWidget(hdr)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("MutedLabel")
            sub.setWordWrap(True)
            sub.setStyleSheet("font-size: 12px;")
            lay.addWidget(sub)
        return card, lay

    # ------------------------------------------------------------------
    # 1. Dual AI Engine (BYOK)
    # ------------------------------------------------------------------

    def _build_ai_section(self) -> None:
        card, lay = self._make_section_card(
            "Dual AI Engine (Bring Your Own Key)",
            "Keys are stored strictly on this PC in %APPDATA%\\KotaKow. "
            "Use Gemini only, Groq only, or both for automatic 429/quota fallback.",
        )

        # Gemini API Key
        lay.addWidget(QLabel("Google Gemini API Key (Primary · Direct Audio-to-Text)"))
        gem_row = QHBoxLayout()
        gem_row.setSpacing(8)
        self._gemini_key = QLineEdit()
        self._gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._gemini_key.setPlaceholderText("AIza...")
        self._gemini_key.textChanged.connect(self._save_settings)

        self._gemini_eye = QPushButton("Show")
        self._gemini_eye.setFixedWidth(64)
        self._gemini_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gemini_eye.clicked.connect(lambda: self._toggle_mask(self._gemini_key, self._gemini_eye))

        self._gemini_test_btn = QPushButton("Fetch Models / Test")
        self._gemini_test_btn.setObjectName("PrimaryButton")
        self._gemini_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gemini_test_btn.clicked.connect(self._fetch_gemini)

        gem_row.addWidget(self._gemini_key, 1)
        gem_row.addWidget(self._gemini_eye)
        gem_row.addWidget(self._gemini_test_btn)
        lay.addLayout(gem_row)

        gem_model_row = QHBoxLayout()
        gem_model_row.setSpacing(10)
        gem_model_row.addWidget(QLabel("Gemini Model:"))
        self._gemini_model = QComboBox()
        self._gemini_model.setEditable(True)
        self._gemini_model.setMinimumWidth(260)
        self._gemini_model.currentTextChanged.connect(self._save_settings)
        gem_model_row.addWidget(self._gemini_model, 1)
        lay.addLayout(gem_model_row)

        self._gemini_status = QLabel("")
        self._gemini_status.setObjectName("MutedLabel")
        self._gemini_status.setWordWrap(True)
        self._gemini_status.setStyleSheet("font-size: 11px;")
        lay.addWidget(self._gemini_status)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("opacity: 0.25;")
        lay.addWidget(sep)

        # Groq API Key
        lay.addWidget(QLabel("Groq API Key (Optional Auto-Backup · Whisper Large v3 + Chat Cleanup)"))
        groq_row = QHBoxLayout()
        groq_row.setSpacing(8)
        self._groq_key = QLineEdit()
        self._groq_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._groq_key.setPlaceholderText("gsk_...")
        self._groq_key.textChanged.connect(self._save_settings)

        self._groq_eye = QPushButton("Show")
        self._groq_eye.setFixedWidth(64)
        self._groq_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self._groq_eye.clicked.connect(lambda: self._toggle_mask(self._groq_key, self._groq_eye))

        self._groq_test_btn = QPushButton("Fetch Models / Test")
        self._groq_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._groq_test_btn.clicked.connect(self._fetch_groq)

        groq_row.addWidget(self._groq_key, 1)
        groq_row.addWidget(self._groq_eye)
        groq_row.addWidget(self._groq_test_btn)
        lay.addLayout(groq_row)

        groq_model_row = QHBoxLayout()
        groq_model_row.setSpacing(10)
        groq_model_row.addWidget(QLabel("Groq Cleanup Model:"))
        self._groq_model = QComboBox()
        self._groq_model.setEditable(True)
        self._groq_model.setMinimumWidth(260)
        self._groq_model.currentTextChanged.connect(self._save_settings)
        groq_model_row.addWidget(self._groq_model, 1)
        lay.addLayout(groq_model_row)

        self._groq_status = QLabel("")
        self._groq_status.setObjectName("MutedLabel")
        self._groq_status.setWordWrap(True)
        self._groq_status.setStyleSheet("font-size: 11px;")
        lay.addWidget(self._groq_status)

        self._layout.addWidget(card)

    # ------------------------------------------------------------------
    # 2. Language Mode & Smart Formatting
    # ------------------------------------------------------------------

    def _build_language_section(self) -> None:
        card, lay = self._make_section_card(
            "Language Mode & Smart Formatting",
            "Choose how Kota Kow writes Bengali and English speech. Configured here to keep the floating pill distraction-free.",
        )

        self._lang_auto = QRadioButton("Auto (Default) — Natural Bengali Unicode + English script")
        self._lang_bn = QRadioButton("বাংলা (Bengali Only) — Strictly Bengali Unicode script (e.g., Chrome → ক্রোম)")
        self._lang_en = QRadioButton("English (English Only) — Strictly clean grammatical English")

        for rb in (self._lang_auto, self._lang_bn, self._lang_en):
            rb.toggled.connect(self._save_settings)
            lay.addWidget(rb)

        lay.addSpacing(4)
        self._smart_fmt_cb = QCheckBox(
            "Smart Formatting — Automatically format spoken lists into bullets/numbers and add natural paragraph breaks"
        )
        self._smart_fmt_cb.toggled.connect(self._save_settings)
        lay.addWidget(self._smart_fmt_cb)

        self._layout.addWidget(card)

    # ------------------------------------------------------------------
    # 3. Custom Hotkey, Microphone & Chime Audio
    # ------------------------------------------------------------------

    def _build_hotkey_audio_section(self) -> None:
        card, lay = self._make_section_card(
            "Global Hotkey & Audio",
            "Hold (>300ms) for Push-to-Talk, or double-tap (≤400ms) for Hands-Free lock. Press Esc anytime to cancel.",
        )

        hk_row = QHBoxLayout()
        hk_row.setSpacing(10)
        hk_row.addWidget(QLabel("Dictation Hotkey:"))
        self._hotkey_display = QLabel(DEFAULT_HOTKEY_LABEL)
        self._hotkey_display.setObjectName("AccentBadge")
        self._hotkey_display.setStyleSheet("font-size: 13px; padding: 5px 12px;")

        self._record_hk_btn = QPushButton("Record Hotkey")
        self._record_hk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._record_hk_btn.clicked.connect(self._toggle_record_hotkey)

        reset_hk_btn = QPushButton("Reset Default")
        reset_hk_btn.setObjectName("GhostButton")
        reset_hk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_hk_btn.clicked.connect(self._reset_hotkey)

        hk_row.addWidget(self._hotkey_display)
        hk_row.addStretch()
        hk_row.addWidget(self._record_hk_btn)
        hk_row.addWidget(reset_hk_btn)
        lay.addLayout(hk_row)

        # Microphone selector
        mic_row = QHBoxLayout()
        mic_row.setSpacing(10)
        mic_row.addWidget(QLabel("Microphone:"))
        self._mic_combo = QComboBox()
        self._mic_combo.currentIndexChanged.connect(self._save_settings)
        refresh_mic_btn = QPushButton("Refresh")
        refresh_mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_mic_btn.clicked.connect(self._refresh_microphones)
        mic_row.addWidget(self._mic_combo, 1)
        mic_row.addWidget(refresh_mic_btn)
        lay.addLayout(mic_row)

        # Sound chimes ON/OFF + Volume
        snd_row = QHBoxLayout()
        snd_row.setSpacing(12)
        self._sound_cb = QCheckBox("Enable Start / Stop / Cancel chimes")
        self._sound_cb.toggled.connect(self._save_settings)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setFixedWidth(150)
        self._vol_slider.valueChanged.connect(self._on_volume_changed)

        self._vol_lbl = QLabel("65%")
        self._vol_lbl.setFixedWidth(36)
        self._vol_lbl.setObjectName("MutedLabel")

        test_snd_btn = QPushButton("Test Chime")
        test_snd_btn.setObjectName("GhostButton")
        test_snd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_snd_btn.clicked.connect(self.controller.test_chime)

        snd_row.addWidget(self._sound_cb)
        snd_row.addStretch()
        snd_row.addWidget(QLabel("Volume:"))
        snd_row.addWidget(self._vol_slider)
        snd_row.addWidget(self._vol_lbl)
        snd_row.addWidget(test_snd_btn)
        lay.addLayout(snd_row)

        self._layout.addWidget(card)

    # ------------------------------------------------------------------
    # 4. Accent Color & Start with Windows
    # ------------------------------------------------------------------

    def _build_appearance_system_section(self) -> None:
        card, lay = self._make_section_card("Appearance & Startup")

        acc_row = QHBoxLayout()
        acc_row.setSpacing(10)
        acc_row.addWidget(QLabel("Accent Color:"))

        for key, spec in ACCENT_PRESETS.items():
            btn = QPushButton(spec["name"])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self._select_accent(k))
            self._accent_buttons[key] = btn
            acc_row.addWidget(btn)

        acc_row.addStretch()
        lay.addLayout(acc_row)

        lay.addSpacing(4)
        self._startup_cb = QCheckBox("Start Kota Kow automatically when Windows starts (minimized to System Tray)")
        self._startup_cb.toggled.connect(self._on_startup_toggled)
        lay.addWidget(self._startup_cb)

        self._layout.addWidget(card)

    # ------------------------------------------------------------------
    # 5. Advanced System Prompt
    # ------------------------------------------------------------------

    def _build_advanced_prompt_section(self) -> None:
        card, lay = self._make_section_card(
            "Advanced Dictation Prompt",
            "Customize the base instruction sent to Gemini and Groq. Language mode rules and your Custom Dictionary are always appended automatically.",
        )

        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setFixedHeight(104)
        lay.addWidget(self._prompt_edit)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setObjectName("GhostButton")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_prompt)

        save_btn = QPushButton("Save Prompt")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_prompt_clicked)

        self._prompt_saved_lbl = QLabel("")
        self._prompt_saved_lbl.setObjectName("MutedLabel")
        self._prompt_saved_lbl.setStyleSheet("font-size: 11px;")

        btn_row.addWidget(reset_btn)
        btn_row.addWidget(self._prompt_saved_lbl)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        self._layout.addWidget(card)

    # ------------------------------------------------------------------
    # Populate & Persist Helpers
    # ------------------------------------------------------------------

    def _populate_from_config(self) -> None:
        cfg = self.controller.config
        self._gemini_key.setText(cfg.gemini_api_key)
        self._groq_key.setText(cfg.groq_api_key)

        self._gemini_model.clear()
        gem_items = list(dict.fromkeys(([cfg.gemini_model] if cfg.gemini_model else []) + cfg.gemini_available_models))
        if not gem_items:
            gem_items = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-4-hydrogen"]
        self._gemini_model.addItems(gem_items)
        self._gemini_model.setCurrentText(cfg.gemini_model or gem_items[0])

        self._groq_model.clear()
        groq_items = list(dict.fromkeys(([cfg.groq_chat_model] if cfg.groq_chat_model else []) + cfg.groq_available_models))
        if not groq_items:
            groq_items = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        self._groq_model.addItems(groq_items)
        self._groq_model.setCurrentText(cfg.groq_chat_model or groq_items[0])

        if cfg.language_mode == "bn":
            self._lang_bn.setChecked(True)
        elif cfg.language_mode == "en":
            self._lang_en.setChecked(True)
        else:
            self._lang_auto.setChecked(True)

        self._smart_fmt_cb.setChecked(cfg.smart_formatting)
        self._hotkey_display.setText(cfg.hotkey_label)

        self._refresh_microphones()
        self._sound_cb.setChecked(cfg.sound_enabled)
        self._vol_slider.setValue(cfg.sound_volume)
        self._vol_lbl.setText(f"{cfg.sound_volume}%")

        self._style_accent_buttons(cfg.accent_color)
        self._startup_cb.setChecked(cfg.start_with_windows or is_startup_enabled())
        self._prompt_edit.setPlainText(cfg.advanced_prompt or DEFAULT_ADVANCED_PROMPT)

    @Slot()
    def _refresh_microphones(self) -> None:
        was_loading = self._loading_ui
        self._loading_ui = True
        saved = self.controller.config.microphone_device
        self._mic_combo.clear()
        devices = list_input_devices()
        target_idx = 0
        for idx, dev in enumerate(devices):
            label = dev.name if dev.index is None else f"{dev.name}"
            self._mic_combo.addItem(label, "" if dev.index is None else dev.name)
            if saved and dev.name == saved:
                target_idx = idx
        self._mic_combo.setCurrentIndex(target_idx)
        self._loading_ui = was_loading

    def _style_accent_buttons(self, selected_key: str) -> None:
        for key, btn in self._accent_buttons.items():
            color = ACCENT_PRESETS[key]["primary"]
            if key == selected_key:
                btn.setStyleSheet(
                    f"background-color: {color}; color: #FFFFFF; "
                    f"border: 2px solid #FFFFFF; border-radius: 16px; padding: 5px 14px; font-weight: 700;"
                )
            else:
                btn.setStyleSheet(
                    f"background-color: transparent; color: {color}; "
                    f"border: 2px solid {color}; border-radius: 16px; padding: 5px 14px; font-weight: 600;"
                )

    def _select_accent(self, key: str) -> None:
        cfg = self.controller.config
        cfg.accent_color = key
        self._style_accent_buttons(key)
        self.controller.apply_config(cfg)

    def _toggle_mask(self, edit: QLineEdit, btn: QPushButton) -> None:
        if edit.echoMode() == QLineEdit.EchoMode.Password:
            edit.setEchoMode(QLineEdit.EchoMode.Normal)
            btn.setText("Hide")
        else:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            btn.setText("Show")

    def _on_volume_changed(self, value: int) -> None:
        self._vol_lbl.setText(f"{value}%")
        self._save_settings()

    def _on_startup_toggled(self, checked: bool) -> None:
        if self._loading_ui:
            return
        set_startup_enabled(checked)
        self._save_settings()

    @Slot()
    def _save_settings(self, *_args) -> None:
        if self._loading_ui:
            return
        cfg = self.controller.config
        cfg.gemini_api_key = self._gemini_key.text().strip()
        cfg.gemini_model = self._gemini_model.currentText().strip() or cfg.gemini_model
        cfg.groq_api_key = self._groq_key.text().strip()
        cfg.groq_chat_model = self._groq_model.currentText().strip() or cfg.groq_chat_model

        if self._lang_bn.isChecked():
            cfg.language_mode = "bn"
        elif self._lang_en.isChecked():
            cfg.language_mode = "en"
        else:
            cfg.language_mode = "auto"

        cfg.smart_formatting = self._smart_fmt_cb.isChecked()
        cfg.microphone_device = str(self._mic_combo.currentData() or "")
        cfg.sound_enabled = self._sound_cb.isChecked()
        cfg.sound_volume = int(self._vol_slider.value())
        cfg.start_with_windows = self._startup_cb.isChecked()
        self.controller.apply_config(cfg)

    @Slot()
    def _save_prompt_clicked(self) -> None:
        cfg = self.controller.config
        cfg.advanced_prompt = self._prompt_edit.toPlainText().strip() or DEFAULT_ADVANCED_PROMPT
        self.controller.apply_config(cfg)
        self._prompt_saved_lbl.setText("Saved ✓")

    @Slot()
    def _reset_prompt(self) -> None:
        self._prompt_edit.setPlainText(DEFAULT_ADVANCED_PROMPT)
        self._save_prompt_clicked()

    # ------------------------------------------------------------------
    # Custom Hotkey Recorder
    # ------------------------------------------------------------------

    @Slot()
    def _toggle_record_hotkey(self) -> None:
        if self._recording_hotkey:
            self._recording_hotkey = False
            self.controller.cancel_hotkey_capture()
            self._record_hk_btn.setText("Record Hotkey")
            self._hotkey_display.setText(self.controller.config.hotkey_label)
            return

        self._recording_hotkey = True
        self._record_hk_btn.setText("Cancel (Esc)")
        self._hotkey_display.setText("Press desired key combo...")
        self.controller.start_hotkey_capture()

    @Slot(object, str)
    def _on_hotkey_captured(self, vks: list[int] | None, label: str) -> None:
        self._recording_hotkey = False
        self._record_hk_btn.setText("Record Hotkey")
        if not vks:
            self._hotkey_display.setText(self.controller.config.hotkey_label)
            return
        cfg = self.controller.config
        cfg.hotkey_vks = list(vks)
        cfg.hotkey_label = label
        self._hotkey_display.setText(label)
        self.controller.apply_config(cfg)

    @Slot()
    def _reset_hotkey(self) -> None:
        if self._recording_hotkey:
            self._recording_hotkey = False
            self.controller.cancel_hotkey_capture()
            self._record_hk_btn.setText("Record Hotkey")
        cfg = self.controller.config
        cfg.hotkey_vks = list(DEFAULT_HOTKEY_VKS)
        cfg.hotkey_label = DEFAULT_HOTKEY_LABEL
        self._hotkey_display.setText(DEFAULT_HOTKEY_LABEL)
        self.controller.apply_config(cfg)

    # ------------------------------------------------------------------
    # Async Dynamic Model Fetch / Connection Tests
    # ------------------------------------------------------------------

    @Slot()
    def _fetch_gemini(self) -> None:
        key = self._gemini_key.text().strip()
        self._save_settings()
        self._gemini_test_btn.setEnabled(False)
        self._gemini_status.setText("Connecting to Google Gemini & fetching available audio-capable models...")

        def _worker() -> None:
            try:
                models = fetch_gemini_models(key)
                self._sig_gemini_models.emit(True, models, f"Connected ✓  Found {len(models)} models. Selected fastest: {models[0]}")
            except AIEngineError as exc:
                self._sig_gemini_models.emit(False, [], str(exc))
            except Exception as exc:
                self._sig_gemini_models.emit(False, [], f"Error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(bool, object, str)
    def _on_gemini_models_fetched(self, ok: bool, models: list[str], message: str) -> None:
        self._gemini_test_btn.setEnabled(True)
        self._gemini_status.setText(message)
        if not ok or not models:
            return

        self._loading_ui = True
        self._gemini_model.clear()
        self._gemini_model.addItems(models)
        # Default to the fastest available Flash-Lite/Flash audio-capable model (models[0])
        self._gemini_model.setCurrentText(models[0])
        self._loading_ui = False

        cfg = self.controller.config
        cfg.gemini_available_models = models
        cfg.gemini_model = models[0]
        self.controller.apply_config(cfg)

    @Slot()
    def _fetch_groq(self) -> None:
        key = self._groq_key.text().strip()
        self._save_settings()
        self._groq_test_btn.setEnabled(False)
        self._groq_status.setText("Connecting to Groq & fetching available chat models...")

        def _worker() -> None:
            try:
                models = fetch_groq_models(key)
                self._sig_groq_models.emit(True, models, f"Connected ✓  Found {len(models)} chat models (STT: whisper-large-v3).")
            except AIEngineError as exc:
                self._sig_groq_models.emit(False, [], str(exc))
            except Exception as exc:
                self._sig_groq_models.emit(False, [], f"Error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(bool, object, str)
    def _on_groq_models_fetched(self, ok: bool, models: list[str], message: str) -> None:
        self._groq_test_btn.setEnabled(True)
        self._groq_status.setText(message)
        if not ok or not models:
            return

        self._loading_ui = True
        self._groq_model.clear()
        self._groq_model.addItems(models)
        self._groq_model.setCurrentText(models[0])
        self._loading_ui = False

        cfg = self.controller.config
        cfg.groq_available_models = models
        cfg.groq_chat_model = models[0]
        self.controller.apply_config(cfg)
