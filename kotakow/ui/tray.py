"""System Tray integration for Kota Kow."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from kotakow import APP_DISPLAY_NAME
from kotakow.assets import make_qicon
from kotakow.config import ACCENT_PRESETS


class SystemTrayManager(QObject):
    """Manages the Windows System Tray icon, tooltip, notifications, and menu."""

    open_requested = Signal()
    pause_toggled = Signal()
    quit_requested = Signal()

    def __init__(self, accent_key: str = "teal", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._accent_hex = ACCENT_PRESETS.get(accent_key, ACCENT_PRESETS["teal"])["primary"]
        self._paused = False
        self._recording = False

        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip(f"{APP_DISPLAY_NAME} — Ready")

        self._menu = QMenu()
        self._open_action = QAction(f"Open {APP_DISPLAY_NAME}", self._menu)
        self._open_action.triggered.connect(self.open_requested.emit)

        self._pause_action = QAction("Pause Hotkey", self._menu)
        self._pause_action.triggered.connect(self.pause_toggled.emit)

        self._quit_action = QAction("Quit", self._menu)
        self._quit_action.triggered.connect(self.quit_requested.emit)

        self._menu.addAction(self._open_action)
        self._menu.addAction(self._pause_action)
        self._menu.addSeparator()
        self._menu.addAction(self._quit_action)

        self.tray.setContextMenu(self._menu)
        self.tray.activated.connect(self._on_activated)
        self._refresh_icon()
        self.tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    def set_accent(self, accent_key: str) -> None:
        self._accent_hex = ACCENT_PRESETS.get(accent_key, ACCENT_PRESETS["teal"])["primary"]
        self._refresh_icon()

    @Slot(bool)
    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self._pause_action.setText("Resume Hotkey" if self._paused else "Pause Hotkey")
        self._refresh_icon()

    @Slot(str)
    def set_state(self, state: str) -> None:
        self._recording = state in ("recording_ptt", "recording_hands_free", "processing")
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        self.tray.setIcon(
            make_qicon(
                accent_hex=self._accent_hex,
                paused=self._paused,
                recording=self._recording,
            )
        )
        if self._paused:
            self.tray.setToolTip(f"{APP_DISPLAY_NAME} — Hotkey Paused")
        elif self._recording:
            self.tray.setToolTip(f"{APP_DISPLAY_NAME} — Listening...")
        else:
            self.tray.setToolTip(f"{APP_DISPLAY_NAME} — Ready")

    def notify(self, title: str, message: str, duration_ms: int = 3200) -> None:
        if self.tray.isSystemTrayAvailable():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, duration_ms)

    def hide(self) -> None:
        self.tray.hide()
