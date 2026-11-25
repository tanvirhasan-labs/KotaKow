"""Entry point for Kota Kow — Lightweight Windows 11 voice-typing desktop app."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from kotakow import APP_DISPLAY_NAME, APP_INTERNAL_NAME
from kotakow.assets import make_qicon
from kotakow.config import ACCENT_PRESETS, AppConfig, ConfigManager
from kotakow.controller import AppController
from kotakow.database import Database
from kotakow.ui.floating_pill import FloatingRecordingPill
from kotakow.ui.main_window import MainWindow
from kotakow.ui.theme import build_stylesheet, create_app_font, get_palette, resolve_is_dark
from kotakow.ui.tray import SystemTrayManager

_IPC_SERVER_NAME = f"{APP_INTERNAL_NAME}_SingleInstance_IPC_v1"


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"{APP_INTERNAL_NAME}.DesktopApp"
        )
    except Exception:
        pass


def _notify_existing_instance() -> bool:
    """If Kota Kow is already running, ask it to show its window and return True."""
    socket = QLocalSocket()
    socket.connectToServer(_IPC_SERVER_NAME)
    if socket.waitForConnected(250):
        socket.write(b"SHOW")
        socket.flush()
        socket.waitForBytesWritten(250)
        socket.disconnectFromServer()
        return True
    return False


def main() -> int:
    _set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(APP_INTERNAL_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(create_app_font(10))

    # Single-instance protection so duplicate keyboard hooks are never registered
    if _notify_existing_instance():
        return 0

    ipc_server = QLocalServer()
    QLocalServer.removeServer(_IPC_SERVER_NAME)
    ipc_server.listen(_IPC_SERVER_NAME)

    config_manager = ConfigManager()
    db = Database()
    controller = AppController(config_manager=config_manager, db=db)

    cfg = controller.config
    palette = get_palette(cfg.theme_mode, cfg.accent_color)
    app.setStyleSheet(build_stylesheet(palette))
    app.setWindowIcon(make_qicon(ACCENT_PRESETS.get(cfg.accent_color, ACCENT_PRESETS["teal"])["primary"]))

    pill = FloatingRecordingPill(palette=palette)
    tray = SystemTrayManager(accent_key=cfg.accent_color, parent=app)

    last_dark_state = {"is_dark": palette.is_dark}

    def apply_theme(current_cfg: AppConfig) -> None:
        pal = get_palette(current_cfg.theme_mode, current_cfg.accent_color)
        last_dark_state["is_dark"] = pal.is_dark
        app.setStyleSheet(build_stylesheet(pal))
        app.setWindowIcon(make_qicon(pal.accent))
        pill.apply_palette(pal)
        tray.set_accent(current_cfg.accent_color)
        window.apply_palette(pal)

    window = MainWindow(controller=controller, on_theme_updated=apply_theme)

    # Wire IPC second-launch wakeup -> bring existing window to front
    def _on_new_ipc_connection() -> None:
        conn = ipc_server.nextPendingConnection()
        if conn is not None:
            conn.readAll()
            conn.close()
            conn.deleteLater()
        window.bring_to_front()

    ipc_server.newConnection.connect(_on_new_ipc_connection)

    # Wire Controller <-> Floating Pill
    controller.pill_show_recording.connect(pill.show_recording)
    controller.pill_show_processing.connect(pill.show_processing)
    controller.pill_hide.connect(pill.hide_pill)
    controller.pill_audio_level.connect(pill.set_audio_level)
    pill.cancel_clicked.connect(controller.cancel_dictation)
    pill.confirm_clicked.connect(controller.confirm_and_stop)

    # Wire Controller <-> System Tray
    controller.paused_changed.connect(tray.set_paused)
    controller.state_changed.connect(tray.set_state)
    controller.toast_message.connect(tray.notify)
    tray.open_requested.connect(window.bring_to_front)
    tray.pause_toggled.connect(controller.toggle_paused)

    def _quit_app() -> None:
        window.prepare_for_quit()
        pill.hide_pill()
        tray.hide()
        ipc_server.close()
        controller.shutdown()
        app.quit()

    tray.quit_requested.connect(_quit_app)
    app.aboutToQuit.connect(controller.shutdown)

    # Watch Windows 11 system theme changes automatically when theme_mode == "system"
    theme_watcher = QTimer(app)
    theme_watcher.setInterval(3000)

    def _check_system_theme() -> None:
        c = controller.config
        if c.theme_mode == "system":
            now_dark = resolve_is_dark("system")
            if now_dark != last_dark_state["is_dark"]:
                apply_theme(c)

    theme_watcher.timeout.connect(_check_system_theme)
    theme_watcher.start()

    # Start Windows global low-level keyboard hook
    controller.start()

    start_minimized = "--minimized" in sys.argv
    if start_minimized and cfg.has_any_api_key():
        window.hide()
    else:
        window.show()
        if not cfg.has_any_api_key():
            # Clean first-run experience: land on Dashboard with prominent onboarding banner
            window.switch_tab(0)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
