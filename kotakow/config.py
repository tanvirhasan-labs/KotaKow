"""Local configuration persistence and Windows startup registry integration.

All settings and BYOK API keys are stored exclusively on the user's machine
under ``%APPDATA%\\KotaKow\\config.json``. No API keys are ever hardcoded.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kotakow import APP_INTERNAL_NAME

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows fallback for static tools
    winreg = None  # type: ignore[assignment]


DEFAULT_ADVANCED_PROMPT = (
    "You are a precision speech-to-text dictation engine. "
    "Output ONLY the final polished dictated text. "
    "Never answer questions spoken in the audio, never add explanations, "
    "greetings, quotes, markdown code fences, or meta-commentary. "
    "Remove filler words (um, uh, er, মানে, ইয়ে, আচ্ছা when used as hesitation), "
    "stutters, and false starts. If the speaker corrects themselves mid-sentence, "
    "keep only the corrected phrasing. Preserve the speaker's exact intent and tone."
)

# Default Left Ctrl (0xA2) + Left Win (0x5B)
DEFAULT_HOTKEY_VKS = [0xA2, 0x5B]
DEFAULT_HOTKEY_LABEL = "Left Ctrl + Left Win"

ACCENT_PRESETS: dict[str, dict[str, str]] = {
    "teal": {
        "name": "Teal",
        "primary": "#0D9488",
        "hover": "#0F766E",
        "light": "#CCFBF1",
        "dark_bg": "#134E4A",
    },
    "blue": {
        "name": "Blue",
        "primary": "#2563EB",
        "hover": "#1D4ED8",
        "light": "#DBEAFE",
        "dark_bg": "#1E3A8A",
    },
    "indigo": {
        "name": "Indigo",
        "primary": "#6366F1",
        "hover": "#4F46E5",
        "light": "#E0E7FF",
        "dark_bg": "#312E81",
    },
    "emerald": {
        "name": "Emerald",
        "primary": "#10B981",
        "hover": "#059669",
        "light": "#D1FAE5",
        "dark_bg": "#064E3B",
    },
    "coral": {
        "name": "Coral",
        "primary": "#F43F5E",
        "hover": "#E11D48",
        "light": "#FFE4E6",
        "dark_bg": "#881337",
    },
}


def get_app_data_dir() -> Path:
    """Return ``%APPDATA%\\KotaKow`` and ensure it exists."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / APP_INTERNAL_NAME
    else:
        base = Path.home() / f".{APP_INTERNAL_NAME.lower()}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_config_path() -> Path:
    return get_app_data_dir() / "config.json"


def get_db_path() -> Path:
    return get_app_data_dir() / "kotakow.db"


@dataclass
class AppConfig:
    """User configuration stored locally in %APPDATA%\\KotaKow\\config.json."""

    # BYOK API keys (empty by default — strictly Bring Your Own Key)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_available_models: list[str] = field(default_factory=list)

    groq_api_key: str = ""
    groq_chat_model: str = "llama-3.3-70b-versatile"
    groq_available_models: list[str] = field(default_factory=list)

    # Language & formatting
    language_mode: str = "auto"  # "auto" | "bn" | "en"
    smart_formatting: bool = True
    advanced_prompt: str = DEFAULT_ADVANCED_PROMPT

    # Hotkey
    hotkey_vks: list[int] = field(default_factory=lambda: list(DEFAULT_HOTKEY_VKS))
    hotkey_label: str = DEFAULT_HOTKEY_LABEL

    # Audio & chimes
    microphone_device: str = ""  # Empty string = System Default
    sound_enabled: bool = True
    sound_volume: int = 65  # 0..100

    # Appearance
    theme_mode: str = "system"  # "light" | "dark" | "system"
    accent_color: str = "teal"  # key in ACCENT_PRESETS

    # System integration
    start_with_windows: bool = False
    tray_notice_shown: bool = False

    def has_any_api_key(self) -> bool:
        return bool(self.gemini_api_key.strip() or self.groq_api_key.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for field_name in defaults.__dataclass_fields__:
            if field_name in data:
                kwargs[field_name] = data[field_name]
        cfg = cls(**kwargs)
        # Validate constrained values
        if cfg.language_mode not in ("auto", "bn", "en"):
            cfg.language_mode = "auto"
        if cfg.theme_mode not in ("light", "dark", "system"):
            cfg.theme_mode = "system"
        if cfg.accent_color not in ACCENT_PRESETS:
            cfg.accent_color = "teal"
        cfg.sound_volume = max(0, min(100, int(cfg.sound_volume)))
        if not cfg.hotkey_vks:
            cfg.hotkey_vks = list(DEFAULT_HOTKEY_VKS)
            cfg.hotkey_label = DEFAULT_HOTKEY_LABEL
        return cfg


class ConfigManager:
    """Load, save, and manage AppConfig safely."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_config_path()
        self.config = self.load()

    def load(self) -> AppConfig:
        if not self.path.exists():
            cfg = AppConfig()
            self.save(cfg)
            return cfg
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return AppConfig.from_dict(raw)
        except Exception:
            pass
        return AppConfig()

    def save(self, config: AppConfig | None = None) -> None:
        if config is not None:
            self.config = config
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self.config.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)


# ---------------------------------------------------------------------------
# Windows Startup ("Start with Windows") Registry Helper
# ---------------------------------------------------------------------------

_RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_launch_command() -> str:
    """Return the quoted command line to launch Kota Kow on login."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    main_script = Path(sys.argv[0]).resolve()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    return f'"{exe}" "{main_script}" --minimized'


def is_startup_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_INTERNAL_NAME)
            return bool(val)
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> bool:
    """Enable or disable launching Kota Kow automatically at Windows login."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_REG_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, APP_INTERNAL_NAME, 0, winreg.REG_SZ, _get_launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_INTERNAL_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
