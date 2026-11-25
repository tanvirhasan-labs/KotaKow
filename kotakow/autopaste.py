"""Reliable UTF-16 Unicode clipboard auto-paste & foreground app detection (Windows).

Flow:
1. Detect active foreground window / executable name (e.g., Chrome, WhatsApp,
   VS Code, Notepad) for Desktop App Usage analytics.
2. Back up current clipboard Unicode text (CF_UNICODETEXT).
3. Write finalized UTF-16LE text cleanly to the Windows clipboard (lossless
   Bengali Unicode + punctuation + emojis).
4. Wait ~60ms, then send ``Ctrl + V`` via 64-bit safe Win32 ``SendInput``.
5. Restore the user's previous clipboard contents ~250ms later.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Friendly executable -> Display Name mappings for Desktop App Usage stats
_FRIENDLY_APP_NAMES: dict[str, str] = {
    "chrome": "Chrome",
    "msedge": "Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "whatsapp": "WhatsApp",
    "whatsapp.root": "WhatsApp",
    "telegram": "Telegram",
    "discord": "Discord",
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "ms-teams": "Microsoft Teams",
    "code": "VS Code",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "notepad": "Notepad",
    "notepad++": "Notepad++",
    "winword": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpnt": "PowerPoint",
    "outlook": "Outlook",
    "olk": "Outlook",
    "notion": "Notion",
    "obsidian": "Obsidian",
    "windowsterminal": "Terminal",
    "powershell": "PowerShell",
    "pwsh": "PowerShell",
    "cmd": "Command Prompt",
    "messenger": "Messenger",
    "signal": "Signal",
    "explorer": "File Explorer",
    "kotakow": "Kota Kow",
}


if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    ULONG_PTR = ctypes.c_size_t

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", _INPUT_UNION),
        ]

    # Explicit 64-bit safe signatures
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND

    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int

    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL

    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL

    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL

    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL

    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE

    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL

    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p

    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT


def get_active_app_name() -> str:
    """Detect the friendly name of the currently focused Windows desktop app."""
    if not IS_WINDOWS:
        return "Unknown"

    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "Desktop"

        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return "Unknown"

        exe_stem = ""
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if hproc:
            try:
                buf_size = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(1024)
                if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(buf_size)):
                    exe_stem = Path(buf.value).stem
            finally:
                kernel32.CloseHandle(hproc)

        # UWP apps host under ApplicationFrameHost.exe -> inspect window title
        if exe_stem.lower() == "applicationframehost":
            title_len = user32.GetWindowTextLengthW(hwnd)
            if title_len > 0:
                tbuf = ctypes.create_unicode_buffer(title_len + 1)
                user32.GetWindowTextW(hwnd, tbuf, title_len + 1)
                title = tbuf.value.strip()
                if title:
                    for key, friendly in _FRIENDLY_APP_NAMES.items():
                        if key in title.lower():
                            return friendly
                    return title[:32]

        if not exe_stem:
            return "Unknown"

        friendly = _FRIENDLY_APP_NAMES.get(exe_stem.lower())
        if friendly:
            return friendly

        # Clean up raw process stem (e.g. "sublime_text" -> "Sublime Text")
        return exe_stem.replace("_", " ").replace("-", " ").title()
    except Exception:
        return "Unknown"


def _open_clipboard_with_retry(attempts: int = 12, delay_s: float = 0.012) -> bool:
    for _ in range(attempts):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay_s)
    return False


def get_clipboard_text() -> str | None:
    """Read current Unicode text from the Windows clipboard, or None if unavailable."""
    if not IS_WINDOWS:
        return None
    if not _open_clipboard_with_retry():
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    """Write UTF-16LE Unicode text cleanly to the Windows clipboard."""
    if not IS_WINDOWS:
        return False
    encoded = text.encode("utf-16-le") + b"\x00\x00"
    if not _open_clipboard_with_retry():
        return False
    try:
        user32.EmptyClipboard()
        hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not hmem:
            return False
        ptr = kernel32.GlobalLock(hmem)
        if not ptr:
            kernel32.GlobalFree(hmem)
            return False
        try:
            ctypes.memmove(ptr, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(hmem)

        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            kernel32.GlobalFree(hmem)
            return False
        return True
    finally:
        user32.CloseClipboard()


def _send_ctrl_v() -> None:
    """Send Ctrl + V keystrokes via Win32 SendInput."""
    if not IS_WINDOWS:
        return
    inputs = (INPUT * 4)()
    # Ctrl down
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].union.ki = KEYBDINPUT(wVk=VK_CONTROL, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
    # V down
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].union.ki = KEYBDINPUT(wVk=VK_V, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
    # V up
    inputs[2].type = INPUT_KEYBOARD
    inputs[2].union.ki = KEYBDINPUT(wVk=VK_V, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
    # Ctrl up
    inputs[3].type = INPUT_KEYBOARD
    inputs[3].union.ki = KEYBDINPUT(wVk=VK_CONTROL, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
    user32.SendInput(4, inputs, ctypes.sizeof(INPUT))


def paste_unicode_text(text: str) -> bool:
    """Back up clipboard -> copy UTF-16 text -> wait 60ms -> Ctrl+V -> restore after 250ms."""
    if not text or not IS_WINDOWS:
        return False

    previous_text = get_clipboard_text()
    if not set_clipboard_text(text):
        return False

    time.sleep(0.060)
    _send_ctrl_v()

    if previous_text is not None:
        def _restore() -> None:
            try:
                current = get_clipboard_text()
                # Only restore if the user hasn't copied something else in the meantime
                if current == text:
                    set_clipboard_text(previous_text)
            except Exception:
                pass

        timer = threading.Timer(0.250, _restore)
        timer.daemon = True
        timer.start()

    return True
