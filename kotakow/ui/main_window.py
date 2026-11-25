"""Main application window for Kota Kow: sidebar navigation, theme switcher, onboarding, tray minimize."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kotakow import APP_DISPLAY_NAME, APP_VERSION
from kotakow.assets import make_qicon
from kotakow.config import ACCENT_PRESETS, AppConfig
from kotakow.controller import AppController
from kotakow.ui.tabs.dashboard_tab import DashboardTab
from kotakow.ui.tabs.dictionary_tab import DictionaryTab
from kotakow.ui.tabs.history_tab import HistoryTab
from kotakow.ui.tabs.settings_tab import SettingsTab
from kotakow.ui.theme import ThemePalette, get_palette


class MainWindow(QMainWindow):
    """Modern 4-tab sidebar window for Kota Kow."""

    def __init__(self, controller: AppController, on_theme_updated) -> None:
        super().__init__()
        self.controller = controller
        self._on_theme_updated = on_theme_updated
        self._force_quit = False

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(1040, 700)
        self.setMinimumSize(860, 580)

        root = QWidget()
        root.setObjectName("RootContainer")
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ------------------------------------------------------------------
        # Left Sidebar
        # ------------------------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(16, 20, 16, 16)
        side_layout.setSpacing(6)

        # Brand Header
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self._brand_icon_lbl = QLabel()
        self._brand_icon_lbl.setFixedSize(32, 32)
        brand_text_col = QVBoxLayout()
        brand_text_col.setSpacing(0)
        brand_title = QLabel(APP_DISPLAY_NAME)
        brand_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        brand_sub = QLabel(f"v{APP_VERSION} · BYOK")
        brand_sub.setObjectName("MutedLabel")
        brand_sub.setStyleSheet("font-size: 11px;")
        brand_text_col.addWidget(brand_title)
        brand_text_col.addWidget(brand_sub)
        brand_row.addWidget(self._brand_icon_lbl)
        brand_row.addLayout(brand_text_col)
        brand_row.addStretch()
        side_layout.addLayout(brand_row)
        side_layout.addSpacing(18)

        # Navigation Buttons (4 tabs)
        self._nav_buttons: list[QPushButton] = []
        nav_items = [
            ("Dashboard", "📊  Dashboard"),
            ("History", "🕒  History"),
            ("Dictionary", "📖  Dictionary"),
            ("Settings", "⚙  Settings"),
        ]
        for idx, (_key, label) in enumerate(nav_items):
            btn = QPushButton(label)
            btn.setProperty("nav", True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=idx: self.switch_tab(i))
            side_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        side_layout.addStretch()

        # Hotkey Status Card at Bottom of Sidebar
        status_card = QFrame()
        status_card.setObjectName("Card")
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setContentsMargins(12, 10, 12, 10)
        sc_layout.setSpacing(4)

        self._status_dot_lbl = QLabel("●  Ready")
        self._status_dot_lbl.setStyleSheet("font-size: 12px; font-weight: 700;")
        self._hotkey_hint_lbl = QLabel()
        self._hotkey_hint_lbl.setObjectName("MutedLabel")
        self._hotkey_hint_lbl.setWordWrap(True)
        self._hotkey_hint_lbl.setStyleSheet("font-size: 11px;")

        sc_layout.addWidget(self._status_dot_lbl)
        sc_layout.addWidget(self._hotkey_hint_lbl)
        side_layout.addWidget(status_card)

        outer.addWidget(sidebar)

        # ------------------------------------------------------------------
        # Right Main Content Area (Top Bar + Onboarding Banner + Stacked Tabs)
        # ------------------------------------------------------------------
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(0)

        # Top Bar with Page Title + Top-Right Theme Switcher Dropdown
        topbar = QFrame()
        topbar.setObjectName("TopBar")
        topbar.setFixedHeight(60)
        tb_layout = QHBoxLayout(topbar)
        tb_layout.setContentsMargins(26, 0, 24, 0)

        self._page_title_lbl = QLabel("Dashboard")
        self._page_title_lbl.setObjectName("PageTitle")
        tb_layout.addWidget(self._page_title_lbl)
        tb_layout.addStretch()

        # Pause/Resume quick pill button
        self._pause_btn = QPushButton("Pause Hotkey")
        self._pause_btn.setObjectName("GhostButton")
        self._pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pause_btn.clicked.connect(self.controller.toggle_paused)
        tb_layout.addWidget(self._pause_btn)
        tb_layout.addSpacing(8)

        # Top-Right Theme Switcher Dropdown (Light / Dark / System)
        self._theme_btn = QToolButton()
        self._theme_btn.setObjectName("ThemeButton")
        self._theme_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._theme_menu = QMenu(self._theme_btn)
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for mode_key, mode_label in [
            ("light", "☀   Light"),
            ("dark", "🌙   Dark"),
            ("system", "💻   System"),
        ]:
            act = QAction(mode_label, self._theme_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, m=mode_key: self._select_theme_mode(m))
            self._theme_group.addAction(act)
            self._theme_menu.addAction(act)
            self._theme_actions[mode_key] = act

        self._theme_btn.setMenu(self._theme_menu)
        tb_layout.addWidget(self._theme_btn)
        right_col.addWidget(topbar)

        # First-Run Onboarding Banner (shown cleanly whenever no API key is configured)
        self._onboarding_wrap = QWidget()
        ob_wrap_layout = QVBoxLayout(self._onboarding_wrap)
        ob_wrap_layout.setContentsMargins(24, 14, 24, 0)
        ob_wrap_layout.setSpacing(0)

        banner = QFrame()
        banner.setObjectName("OnboardingBanner")
        b_layout = QHBoxLayout(banner)
        b_layout.setContentsMargins(16, 12, 16, 12)
        b_layout.setSpacing(12)

        b_text = QLabel(
            f"<b>Welcome to {APP_DISPLAY_NAME}!</b>  Add your own Google Gemini or Groq API key "
            "(BYOK) in Settings to start voice typing into any Windows app."
        )
        b_text.setWordWrap(True)
        b_btn = QPushButton("Set Up API Key →")
        b_btn.setObjectName("PrimaryButton")
        b_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        b_btn.clicked.connect(lambda: self.switch_tab(3))

        b_layout.addWidget(b_text, 1)
        b_layout.addWidget(b_btn)
        ob_wrap_layout.addWidget(banner)
        right_col.addWidget(self._onboarding_wrap)

        # Stacked Tab Pages
        self._stack = QStackedWidget()
        self.dashboard_tab = DashboardTab(self.controller)
        self.history_tab = HistoryTab(self.controller)
        self.dictionary_tab = DictionaryTab(self.controller)
        self.settings_tab = SettingsTab(self.controller)

        self._stack.addWidget(self.dashboard_tab)
        self._stack.addWidget(self.history_tab)
        self._stack.addWidget(self.dictionary_tab)
        self._stack.addWidget(self.settings_tab)

        right_col.addWidget(self._stack, 1)
        outer.addLayout(right_col, 1)

        # Signals
        self.controller.config_changed.connect(self._on_config_changed)
        self.controller.paused_changed.connect(self._on_paused_changed)
        self.controller.state_changed.connect(self._on_state_changed)

        self._sync_from_config(self.controller.config)
        self.switch_tab(0)

    def prepare_for_quit(self) -> None:
        self._force_quit = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_quit:
            event.accept()
            return
        # Minimize silently to System Tray instead of quitting
        event.ignore()
        self.hide()
        cfg = self.controller.config
        if not cfg.tray_notice_shown:
            cfg.tray_notice_shown = True
            self.controller.config_manager.save(cfg)
            self.controller.toast_message.emit(
                f"{APP_DISPLAY_NAME} is running in the tray",
                f"Press {cfg.hotkey_label} anytime to dictate. Right-click the tray icon to quit.",
            )

    @Slot()
    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def switch_tab(self, index: int) -> None:
        titles = ["Dashboard", "History", "Dictionary", "Settings"]
        self._stack.setCurrentIndex(index)
        self._page_title_lbl.setText(titles[index])
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if index == 0:
            self.dashboard_tab.refresh()
        elif index == 1:
            self.history_tab.refresh()
        elif index == 2:
            self.dictionary_tab.refresh()

    def _select_theme_mode(self, mode: str) -> None:
        cfg = self.controller.config
        if cfg.theme_mode != mode:
            cfg.theme_mode = mode
            self.controller.apply_config(cfg)

    def apply_palette(self, palette: ThemePalette) -> None:
        accent_hex = palette.accent
        icon = make_qicon(accent_hex=accent_hex)
        self.setWindowIcon(icon)
        self._brand_icon_lbl.setPixmap(icon.pixmap(32, 32))
        self.dashboard_tab.apply_palette(palette)

    @Slot(object)
    def _on_config_changed(self, cfg: AppConfig) -> None:
        self._sync_from_config(cfg)
        self._on_theme_updated(cfg)

    def _sync_from_config(self, cfg: AppConfig) -> None:
        mode_labels = {"light": "☀ Light ▾", "dark": "🌙 Dark ▾", "system": "💻 System ▾"}
        self._theme_btn.setText(mode_labels.get(cfg.theme_mode, "💻 System ▾"))
        if cfg.theme_mode in self._theme_actions:
            self._theme_actions[cfg.theme_mode].setChecked(True)

        self._hotkey_hint_lbl.setText(
            f"Hold: {cfg.hotkey_label}\nDouble-tap: Hands-Free"
        )
        self._onboarding_wrap.setVisible(not cfg.has_any_api_key())
        palette = get_palette(cfg.theme_mode, cfg.accent_color)
        self.apply_palette(palette)

    @Slot(bool)
    def _on_paused_changed(self, paused: bool) -> None:
        self._pause_btn.setText("Resume Hotkey" if paused else "Pause Hotkey")
        if paused:
            self._status_dot_lbl.setText("●  Paused")
            self._status_dot_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #94A3B8;")
        else:
            self._status_dot_lbl.setText("●  Ready")
            accent = ACCENT_PRESETS.get(self.controller.config.accent_color, ACCENT_PRESETS["teal"])["primary"]
            self._status_dot_lbl.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {accent};")

    @Slot(str)
    def _on_state_changed(self, state: str) -> None:
        if self.controller.is_paused:
            return
        if state in ("recording_ptt", "recording_hands_free"):
            label = "●  Hands-Free" if state == "recording_hands_free" else "●  Listening..."
            self._status_dot_lbl.setText(label)
            self._status_dot_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #EF4444;")
        elif state == "processing":
            self._status_dot_lbl.setText("●  Processing...")
            self._status_dot_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #F59E0B;")
        else:
            self._on_paused_changed(False)
