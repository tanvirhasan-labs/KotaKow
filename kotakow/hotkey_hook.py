"""Windows 11-safe global low-level keyboard hook (WH_KEYBOARD_LL via ctypes).

Guarantees:
1. Pressing/releasing ``Left Ctrl + Left Win`` (in either order) NEVER opens
   the Windows Start Menu, while normal single ``Win`` key usage stays 100%
   unaffected.
2. Fully customizable hotkey combinations (any 1–3 keys) plus built-in
   interactive Hotkey Recorder mode for the Settings screen.
3. Intercepts and swallows ``Esc`` ONLY while dictation is active (recording
   or processing), leaving ``Esc`` completely normal everywhere else.
4. Runs in its own dedicated Win32 message-pump thread so keyboard hooks
   never lag or time out when Qt UI work occurs.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

# Virtual-key constants
VK_ESCAPE = 0x1B
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4  # Left Alt
VK_RMENU = 0xA5  # Right Alt
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_DUMMY_MASK = 0xE8  # Unassigned VK used to mask LWin/RWin Start-Menu activation

MODIFIER_VKS = {
    VK_LCONTROL,
    VK_RCONTROL,
    VK_LWIN,
    VK_RWIN,
    VK_LSHIFT,
    VK_RSHIFT,
    VK_LMENU,
    VK_RMENU,
    VK_CONTROL,
    VK_SHIFT,
    VK_MENU,
}

WIN_VKS = {VK_LWIN, VK_RWIN}

# Human-readable virtual key names for Settings display & recorder
VK_NAMES: dict[int, str] = {
    0xA2: "Left Ctrl",
    0xA3: "Right Ctrl",
    0x5B: "Left Win",
    0x5C: "Right Win",
    0xA0: "Left Shift",
    0xA1: "Right Shift",
    0xA4: "Left Alt",
    0xA5: "Right Alt",
    0x20: "Space",
    0x09: "Tab",
    0x0D: "Enter",
    0x08: "Backspace",
    0x14: "Caps Lock",
    0x1B: "Esc",
    0x2D: "Insert",
    0x2E: "Delete",
    0x24: "Home",
    0x23: "End",
    0x21: "Page Up",
    0x22: "Page Down",
    0xC0: "`",
    0xBD: "-",
    0xBB: "=",
    0xDB: "[",
    0xDD: "]",
    0xDC: "\\",
    0xBA: ";",
    0xDE: "'",
    0xBC: ",",
    0xBE: ".",
    0xBF: "/",
    0x90: "Num Lock",
    0x91: "Scroll Lock",
    0x13: "Pause",
}
for _i in range(1, 25):
    VK_NAMES[0x6F + _i] = f"F{_i}"
for _c in range(ord("A"), ord("Z") + 1):
    VK_NAMES[_c] = chr(_c)
for _d in range(ord("0"), ord("9") + 1):
    VK_NAMES[_d] = chr(_d)


def vk_to_name(vk: int) -> str:
    return VK_NAMES.get(vk, f"Key(0x{vk:02X})")


def format_hotkey_label(vks: list[int]) -> str:
    """Sort modifiers first and format a clean human-readable hotkey string."""
    priority = {
        VK_LCONTROL: 1,
        VK_RCONTROL: 2,
        VK_LWIN: 3,
        VK_RWIN: 4,
        VK_LMENU: 5,
        VK_RMENU: 6,
        VK_LSHIFT: 7,
        VK_RSHIFT: 8,
    }
    ordered = sorted(dict.fromkeys(vks), key=lambda k: (priority.get(k, 50), k))
    return " + ".join(vk_to_name(k) for k in ordered)


if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    ULONG_PTR = ctypes.c_size_t
    LRESULT = ctypes.c_ssize_t

    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012
    LLKHF_INJECTED = 0x00000010

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

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

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK

    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = LRESULT

    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL

    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL

    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL

    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT

    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def _send_win_mask_key() -> None:
    """Inject a harmless unassigned key (0xE8) so Windows suppresses Start Menu on Win release."""
    if not IS_WINDOWS:
        return
    inputs = (INPUT * 2)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].union.ki = KEYBDINPUT(wVk=VK_DUMMY_MASK, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].union.ki = KEYBDINPUT(wVk=VK_DUMMY_MASK, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
    user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


class GlobalHotkeyHook:
    """Windows low-level keyboard hook for Kota Kow."""

    def __init__(
        self,
        hotkey_vks: list[int],
        on_combo_down: Callable[[], None],
        on_combo_up: Callable[[], None],
        on_escape: Callable[[], None],
        is_escape_active: Callable[[], bool],
    ) -> None:
        self._lock = threading.Lock()
        self._hotkey_vks: set[int] = set(hotkey_vks)
        self._on_combo_down = on_combo_down
        self._on_combo_up = on_combo_up
        self._on_escape = on_escape
        self._is_escape_active = is_escape_active

        self._paused = False
        self._pressed_vks: set[int] = set()
        self._swallowed_vks: set[int] = set()
        self._combo_active = False

        # Interactive Hotkey Recorder state (used by Settings tab)
        self._capture_mode = False
        self._capture_keys: list[int] = []
        self._capture_callback: Callable[[list[int] | None, str], None] | None = None

        self._hook_handle = None
        self._hook_proc = None
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._ready = threading.Event()

    def set_hotkey(self, vks: list[int]) -> None:
        with self._lock:
            self._hotkey_vks = set(vks)
            self._combo_active = False
            self._pressed_vks.clear()
            self._swallowed_vks.clear()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
            if self._paused:
                self._combo_active = False
                self._pressed_vks.clear()
                self._swallowed_vks.clear()

    def start_capture(self, callback: Callable[[list[int] | None, str], None]) -> None:
        """Enter hotkey-recording mode for the Settings UI."""
        with self._lock:
            self._capture_mode = True
            self._capture_keys = []
            self._capture_callback = callback
            self._combo_active = False

    def cancel_capture(self) -> None:
        with self._lock:
            self._capture_mode = False
            self._capture_keys = []
            self._capture_callback = None

    def start(self) -> None:
        if not IS_WINDOWS or self._thread is not None:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="KotaKow-HotkeyHook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def stop(self) -> None:
        if not IS_WINDOWS:
            return
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run_loop(self) -> None:
        self._thread_id = int(kernel32.GetCurrentThreadId())
        # Keep strong reference on self to prevent GC of ctypes callback
        self._hook_proc = HOOKPROC(self._low_level_proc)
        self._hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, None, 0)
        self._ready.set()

        if not self._hook_handle:
            return

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook_handle:
                user32.UnhookWindowsHookEx(self._hook_handle)
                self._hook_handle = None
            self._thread_id = 0

    def _dispatch_async(self, fn: Callable[[], None]) -> None:
        """Run callbacks off the Win32 hook thread so the hook returns in <1ms."""
        threading.Thread(target=fn, daemon=True).start()

    def _low_level_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code < 0:
            return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        # Ignore synthetic keys injected by ourselves or auto-paste
        if info.flags & LLKHF_INJECTED:
            return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        vk = int(info.vkCode)
        is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = w_param in (WM_KEYUP, WM_SYSKEYUP)
        if not (is_down or is_up):
            return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        # ------------------------------------------------------------------
        # 1. Interactive Custom Hotkey Recorder Mode (Settings)
        # ------------------------------------------------------------------
        if self._capture_mode:
            return self._handle_capture(vk, is_down, is_up, n_code, w_param, l_param)

        # ------------------------------------------------------------------
        # 2. Active Esc Cancel Interception (only while recording/processing)
        # ------------------------------------------------------------------
        if vk == VK_ESCAPE and not self._paused:
            if is_down and self._is_escape_active():
                self._swallowed_vks.add(VK_ESCAPE)
                self._dispatch_async(self._on_escape)
                return 1
            if is_up and VK_ESCAPE in self._swallowed_vks:
                self._swallowed_vks.discard(VK_ESCAPE)
                return 1

        # ------------------------------------------------------------------
        # 3. Global Dictation Hotkey Tracking + Windows Start-Menu Safety
        # ------------------------------------------------------------------
        if self._paused:
            return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        swallow = False
        fire_down = False
        fire_up = False
        need_win_mask = False

        with self._lock:
            target = self._hotkey_vks
            if not target:
                return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

            if is_down:
                already_down = vk in self._pressed_vks
                self._pressed_vks.add(vk)

                if already_down:
                    # Keep swallowing key-repeat events for swallowed keys
                    if vk in self._swallowed_vks:
                        swallow = True
                else:
                    # Did this key complete the target hotkey combination?
                    if target.issubset(self._pressed_vks) and not self._combo_active:
                        self._combo_active = True
                        fire_down = True

                        if vk in WIN_VKS:
                            # Case A: Ctrl (or other modifier) was pressed first, then Win.
                            # Swallow Win DOWN and matching Win UP -> Start Menu NEVER triggers!
                            self._swallowed_vks.add(vk)
                            swallow = True
                        elif target.intersection(WIN_VKS):
                            # Case B: Win was pressed first (Windows already saw Win DOWN),
                            # and now the second key completed the combo.
                            # Inject unassigned mask key 0xE8 so releasing Win later does NOT
                            # open the Start Menu, without leaving Win stuck down!
                            need_win_mask = True
                            if vk not in MODIFIER_VKS:
                                self._swallowed_vks.add(vk)
                                swallow = True
                        elif vk not in MODIFIER_VKS:
                            # Non-modifier trigger key (e.g. Ctrl+Alt+Space or F9) -> swallow it
                            self._swallowed_vks.add(vk)
                            swallow = True

            elif is_up:
                self._pressed_vks.discard(vk)
                if vk in self._swallowed_vks:
                    self._swallowed_vks.discard(vk)
                    swallow = True

                if self._combo_active and not target.issubset(self._pressed_vks):
                    self._combo_active = False
                    fire_up = True

        if need_win_mask:
            _send_win_mask_key()

        if fire_down:
            self._dispatch_async(self._on_combo_down)
        elif fire_up:
            self._dispatch_async(self._on_combo_up)

        if swallow:
            return 1
        return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

    def _handle_capture(
        self,
        vk: int,
        is_down: bool,
        is_up: bool,
        n_code: int,
        w_param: int,
        l_param: int,
    ) -> int:
        cb = None
        captured: list[int] | None = None
        cancelled = False
        need_mask = False

        with self._lock:
            if is_down:
                if vk == VK_ESCAPE:
                    cancelled = True
                    self._capture_mode = False
                    self._capture_keys = []
                    cb = self._capture_callback
                    self._capture_callback = None
                else:
                    if vk not in self._capture_keys and len(self._capture_keys) < 3:
                        self._capture_keys.append(vk)
                    if vk in WIN_VKS:
                        need_mask = True
            elif is_up:
                if self._capture_keys:
                    captured = list(self._capture_keys)
                    self._capture_mode = False
                    self._capture_keys = []
                    cb = self._capture_callback
                    self._capture_callback = None

        if need_mask:
            _send_win_mask_key()

        if cancelled and cb is not None:
            self._dispatch_async(lambda: cb(None, ""))
            return 1

        if captured is not None and cb is not None:
            label = format_hotkey_label(captured)
            self._dispatch_async(lambda: cb(captured, label))
            return 1

        # Swallow Win / non-modifier keys while recording so Start Menu / buttons don't fire
        if vk in WIN_VKS or vk not in MODIFIER_VKS:
            return 1
        return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)
