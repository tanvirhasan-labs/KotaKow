"""Theme system (Light / Dark / System) + 5 Accent Presets + Bengali-safe typography.

Ensures crisp Bengali Unicode rendering across all widgets and dictation history
by prioritizing ``Nirmala UI`` with clean ``Segoe UI`` fallback on Windows 11.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtGui import QFont

from kotakow.config import ACCENT_PRESETS

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ThemePalette:
    is_dark: bool
    bg: str
    sidebar_bg: str
    card_bg: str
    card_alt_bg: str
    input_bg: str
    border: str
    border_subtle: str
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    danger: str
    danger_soft: str
    success: str
    pill_bg: str
    pill_border: str
    pill_cancel_bg: str
    pill_cancel_hover: str
    pill_cancel_fg: str
    pill_wave: str


def is_windows_dark_mode() -> bool:
    """Detect whether Windows 11 apps are currently set to Dark theme."""
    if sys.platform != "win32" or winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(val) == 0
    except OSError:
        return False


def resolve_is_dark(theme_mode: str) -> bool:
    if theme_mode == "dark":
        return True
    if theme_mode == "light":
        return False
    return is_windows_dark_mode()


def get_palette(theme_mode: str = "system", accent_key: str = "teal") -> ThemePalette:
    is_dark = resolve_is_dark(theme_mode)
    accent = ACCENT_PRESETS.get(accent_key, ACCENT_PRESETS["teal"])

    if is_dark:
        return ThemePalette(
            is_dark=True,
            bg="#0F1117",
            sidebar_bg="#141720",
            card_bg="#181C26",
            card_alt_bg="#1E2330",
            input_bg="#12151E",
            border="#282E3E",
            border_subtle="#202534",
            text="#F1F5F9",
            text_secondary="#CBD5E1",
            text_muted="#8A94A8",
            accent=accent["primary"],
            accent_hover=accent["hover"],
            accent_soft=accent["dark_bg"],
            danger="#EF4444",
            danger_soft="#3F1D24",
            success="#10B981",
            pill_bg="#141821",
            pill_border="#2B3242",
            pill_cancel_bg="#232938",
            pill_cancel_hover="#31394D",
            pill_cancel_fg="#CBD5E1",
            pill_wave="#F8FAFC",
        )

    return ThemePalette(
        is_dark=False,
        bg="#F6F7FA",
        sidebar_bg="#FFFFFF",
        card_bg="#FFFFFF",
        card_alt_bg="#F1F4F9",
        input_bg="#FFFFFF",
        border="#E2E8F0",
        border_subtle="#EEF2F6",
        text="#0F172A",
        text_secondary="#334155",
        text_muted="#64748B",
        accent=accent["primary"],
        accent_hover=accent["hover"],
        accent_soft=accent["light"],
        danger="#DC2626",
        danger_soft="#FEE2E2",
        success="#059669",
        pill_bg="#FFFFFF",
        pill_border="#DCE3EE",
        pill_cancel_bg="#F1F5F9",
        pill_cancel_hover="#E2E8F0",
        pill_cancel_fg="#475569",
        pill_wave="#0F172A",
    )


def create_app_font(point_size: int = 10) -> QFont:
    """Return a clean Windows 11 font configured with Bengali Unicode fallback."""
    font = QFont("Nirmala UI", point_size)
    font.setFamilies(["Nirmala UI", "Segoe UI", "Segoe UI Variable", "sans-serif"])
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def build_stylesheet(p: ThemePalette) -> str:
    """Generate the complete PySide6 QSS stylesheet for the active palette."""
    return f"""
    * {{
        font-family: "Nirmala UI", "Segoe UI", sans-serif;
    }}

    QMainWindow, QDialog {{
        background-color: {p.bg};
        color: {p.text};
    }}

    QWidget#RootContainer {{
        background-color: {p.bg};
        color: {p.text};
    }}

    QFrame#Sidebar {{
        background-color: {p.sidebar_bg};
        border-right: 1px solid {p.border};
    }}

    QFrame#TopBar {{
        background-color: {p.bg};
        border-bottom: 1px solid {p.border_subtle};
    }}

    QFrame#Card {{
        background-color: {p.card_bg};
        border: 1px solid {p.border};
        border-radius: 14px;
    }}

    QFrame#OnboardingBanner {{
        background-color: {p.accent_soft};
        border: 1px solid {p.accent};
        border-radius: 12px;
    }}

    QFrame#HistoryCard {{
        background-color: {p.card_bg};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}

    QFrame#HistoryCard:hover {{
        border: 1px solid {p.accent};
    }}

    QLabel {{
        color: {p.text};
        background: transparent;
    }}

    QLabel#MutedLabel {{
        color: {p.text_muted};
    }}

    QLabel#SecondaryLabel {{
        color: {p.text_secondary};
    }}

    QLabel#PageTitle {{
        font-size: 20px;
        font-weight: 700;
        color: {p.text};
    }}

    QLabel#SectionTitle {{
        font-size: 14px;
        font-weight: 700;
        color: {p.text};
    }}

    QLabel#BigMetric {{
        font-size: 30px;
        font-weight: 700;
        color: {p.text};
    }}

    QLabel#Badge {{
        background-color: {p.card_alt_bg};
        color: {p.text_secondary};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 600;
    }}

    QLabel#AccentBadge {{
        background-color: {p.accent_soft};
        color: {p.accent};
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 600;
    }}

    /* Sidebar Navigation Buttons */
    QPushButton[nav="true"] {{
        text-align: left;
        padding: 10px 14px;
        border: none;
        border-radius: 10px;
        font-size: 13px;
        font-weight: 600;
        color: {p.text_secondary};
        background-color: transparent;
    }}

    QPushButton[nav="true"]:hover {{
        background-color: {p.card_alt_bg};
        color: {p.text};
    }}

    QPushButton[nav="true"][active="true"] {{
        background-color: {p.accent_soft};
        color: {p.accent};
    }}

    /* Standard Buttons */
    QPushButton {{
        background-color: {p.card_alt_bg};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 7px 14px;
        font-size: 13px;
        font-weight: 600;
    }}

    QPushButton:hover {{
        border-color: {p.accent};
        background-color: {p.card_bg};
    }}

    QPushButton:disabled {{
        opacity: 0.5;
        color: {p.text_muted};
    }}

    QPushButton#PrimaryButton {{
        background-color: {p.accent};
        color: #FFFFFF;
        border: 1px solid {p.accent};
    }}

    QPushButton#PrimaryButton:hover {{
        background-color: {p.accent_hover};
        border-color: {p.accent_hover};
    }}

    QPushButton#DangerButton {{
        background-color: {p.danger_soft};
        color: {p.danger};
        border: 1px solid transparent;
    }}

    QPushButton#DangerButton:hover {{
        background-color: {p.danger};
        color: #FFFFFF;
    }}

    QPushButton#GhostButton {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {p.text_secondary};
        padding: 5px 10px;
    }}

    QPushButton#GhostButton:hover {{
        background-color: {p.card_alt_bg};
        color: {p.text};
    }}

    QPushButton#AccordionHeader {{
        text-align: left;
        background-color: {p.card_alt_bg};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 9px 14px;
        font-size: 13px;
        font-weight: 700;
        color: {p.text};
    }}

    QPushButton#AccordionHeader:hover {{
        border-color: {p.accent};
    }}

    QPushButton#DayAccordionHeader {{
        text-align: left;
        background-color: transparent;
        border: 1px solid {p.border_subtle};
        border-radius: 8px;
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 600;
        color: {p.text_secondary};
    }}

    QPushButton#DayAccordionHeader:hover {{
        background-color: {p.card_alt_bg};
        color: {p.text};
    }}

    QToolButton#ThemeButton {{
        background-color: {p.card_bg};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 9px;
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 600;
    }}

    QToolButton#ThemeButton:hover {{
        border-color: {p.accent};
    }}

    QToolButton#ThemeButton::menu-indicator {{
        image: none;
    }}

    /* Inputs */
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateEdit {{
        background-color: {p.input_bg};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 7px 10px;
        font-size: 13px;
        selection-background-color: {p.accent};
        selection-color: #FFFFFF;
    }}

    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{
        border: 1px solid {p.accent};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {p.card_bg};
        color: {p.text};
        border: 1px solid {p.border};
        selection-background-color: {p.accent_soft};
        selection-color: {p.accent};
        outline: none;
    }}

    /* Checkboxes */
    QCheckBox {{
        spacing: 8px;
        color: {p.text};
        font-size: 13px;
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid {p.border};
        background-color: {p.input_bg};
    }}

    QCheckBox::indicator:checked {{
        background-color: {p.accent};
        border-color: {p.accent};
    }}

    /* Sliders */
    QSlider::groove:horizontal {{
        height: 6px;
        background: {p.border};
        border-radius: 3px;
    }}

    QSlider::sub-page:horizontal {{
        background: {p.accent};
        border-radius: 3px;
    }}

    QSlider::handle:horizontal {{
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
        background: {p.accent};
        border: 2px solid {p.card_bg};
    }}

    /* Menus */
    QMenu {{
        background-color: {p.card_bg};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 5px;
    }}

    QMenu::item {{
        padding: 7px 18px;
        border-radius: 6px;
        font-size: 13px;
    }}

    QMenu::item:selected {{
        background-color: {p.accent_soft};
        color: {p.accent};
    }}

    QMenu::separator {{
        height: 1px;
        background: {p.border_subtle};
        margin: 4px 8px;
    }}

    /* Scroll Areas & Bars */
    QScrollArea {{
        border: none;
        background: transparent;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px 0;
    }}

    QScrollBar::handle:vertical {{
        background: {p.border};
        border-radius: 4px;
        min-height: 28px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {p.text_muted};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        height: 0px;
    }}

    QToolTip {{
        background-color: {p.card_bg};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    """
