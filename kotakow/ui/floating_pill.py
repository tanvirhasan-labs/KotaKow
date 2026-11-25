"""Minimal floating recording capsule positioned bottom-center above Windows taskbar.

Strict minimal layout (NO language buttons on the pill):
- Left: circular subtle cancel button (✕)
- Center: smooth responsive live audio waveform bars (transitions to clean
  minimal loading animation while processing)
- Right: solid high-contrast circular confirm/stop button (✓)

Non-focus-stealing guarantees (CRITICAL):
- ``Qt.WindowType.WindowDoesNotAcceptFocus``
- ``Qt.WidgetAttribute.WA_ShowWithoutActivating``
- Win32 ``WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW``
- Native ``WM_MOUSEACTIVATE`` -> ``MA_NOACTIVATE`` so clicking ✓ or ✕ never
  steals the active text cursor from Chrome, WhatsApp, VS Code, or any app.
"""

from __future__ import annotations

import ctypes
import math
import sys
from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from kotakow.ui.theme import ThemePalette, get_palette

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    WM_MOUSEACTIVATE = 0x0021
    MA_NOACTIVATE = 3

    _is_64bit = sys.maxsize > 2**32
    if _is_64bit:
        _GetWindowLongPtr = user32.GetWindowLongPtrW
        _SetWindowLongPtr = user32.SetWindowLongPtrW
        _LONG_PTR = ctypes.c_ssize_t
    else:
        _GetWindowLongPtr = user32.GetWindowLongW
        _SetWindowLongPtr = user32.SetWindowLongW
        _LONG_PTR = ctypes.c_long

    _GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    _GetWindowLongPtr.restype = _LONG_PTR
    _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
    _SetWindowLongPtr.restype = _LONG_PTR


class FloatingRecordingPill(QWidget):
    """Exact minimal non-focus-stealing capsule for recording & processing."""

    cancel_clicked = Signal()
    confirm_clicked = Signal()

    PILL_WIDTH = 216
    PILL_HEIGHT = 54
    SHADOW_PAD = 10
    BTN_DIAMETER = 34
    NUM_BARS = 15

    def __init__(self, palette: ThemePalette | None = None) -> None:
        super().__init__(None)
        self._palette = palette or get_palette("system", "teal")
        self._mode = "hidden"  # "hidden" | "recording" | "processing"
        self._target_level = 0.0
        self._bar_heights = [0.14] * self.NUM_BARS
        self._phase = 0.0
        self._hover_btn: str | None = None  # "cancel" | "confirm" | None
        self._exstyle_applied = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        total_w = self.PILL_WIDTH + self.SHADOW_PAD * 2
        total_h = self.PILL_HEIGHT + self.SHADOW_PAD * 2
        self.setFixedSize(total_w, total_h)

        # 60 FPS animation loop (only runs while visible)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_animation)

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def _apply_win32_no_activate(self) -> None:
        if not IS_WINDOWS:
            return
        try:
            hwnd = int(self.winId())
            ex_style = _GetWindowLongPtr(hwnd, GWL_EXSTYLE)
            new_style = ex_style | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
            if new_style != ex_style:
                _SetWindowLongPtr(hwnd, GWL_EXSTYLE, new_style)
            self._exstyle_applied = True
        except Exception:
            pass

    def _position_above_taskbar(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.x() + (avail.width() - self.width()) // 2
        y = avail.y() + avail.height() - self.height() - 14
        self.move(x, y)

    @Slot()
    def show_recording(self) -> None:
        self._mode = "recording"
        self._target_level = 0.08
        self._bar_heights = [0.16] * self.NUM_BARS
        self._hover_btn = None
        self._position_above_taskbar()
        self._apply_win32_no_activate()
        self.show()
        self._apply_win32_no_activate()
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        self.update()

    @Slot()
    def show_processing(self) -> None:
        self._mode = "processing"
        self._hover_btn = None
        if not self.isVisible():
            self._position_above_taskbar()
            self._apply_win32_no_activate()
            self.show()
            self._apply_win32_no_activate()
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        self.update()

    @Slot()
    def hide_pill(self) -> None:
        self._mode = "hidden"
        self._target_level = 0.0
        self._hover_btn = None
        self._anim_timer.stop()
        self.hide()

    @Slot(float)
    def set_audio_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, float(level)))

    # ------------------------------------------------------------------
    # Win32 WM_MOUSEACTIVATE Guard (Clicking buttons NEVER steals focus)
    # ------------------------------------------------------------------

    def nativeEvent(self, event_type, message):
        if IS_WINDOWS and event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_MOUSEACTIVATE:
                    return True, MA_NOACTIVATE
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    # ------------------------------------------------------------------
    # Geometry Helpers
    # ------------------------------------------------------------------

    def _capsule_rect(self) -> QRectF:
        return QRectF(
            self.SHADOW_PAD,
            self.SHADOW_PAD,
            self.PILL_WIDTH,
            self.PILL_HEIGHT,
        )

    def _cancel_rect(self) -> QRectF:
        cap = self._capsule_rect()
        d = self.BTN_DIAMETER
        x = cap.left() + 10
        y = cap.top() + (cap.height() - d) / 2.0
        return QRectF(x, y, d, d)

    def _confirm_rect(self) -> QRectF:
        cap = self._capsule_rect()
        d = self.BTN_DIAMETER
        x = cap.right() - 10 - d
        y = cap.top() + (cap.height() - d) / 2.0
        return QRectF(x, y, d, d)

    # ------------------------------------------------------------------
    # Mouse Interaction (Custom hit testing inside capsule)
    # ------------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        hover = None
        if self._cancel_rect().contains(pos):
            hover = "cancel"
        elif self._mode == "recording" and self._confirm_rect().contains(pos):
            hover = "confirm"
        if hover != self._hover_btn:
            self._hover_btn = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor)
            self.update()
        event.accept()

    def leaveEvent(self, event) -> None:
        if self._hover_btn is not None:
            self._hover_btn = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._cancel_rect().contains(pos):
                self.cancel_clicked.emit()
                event.accept()
                return
            if self._mode == "recording" and self._confirm_rect().contains(pos):
                self.confirm_clicked.emit()
                event.accept()
                return
        event.accept()

    # ------------------------------------------------------------------
    # Animation & Painting
    # ------------------------------------------------------------------

    def _tick_animation(self) -> None:
        self._phase += 0.16
        if self._mode == "recording":
            # Gentle decay toward baseline between audio callback frames
            self._target_level *= 0.90
            center = (self.NUM_BARS - 1) / 2.0
            for i in range(self.NUM_BARS):
                dist = abs(i - center) / max(1.0, center)
                envelope = math.cos(dist * math.pi * 0.46) ** 1.35
                ripple = 0.65 + 0.35 * math.sin(self._phase * 1.45 + i * 0.72)
                idle_wave = 0.12 + 0.04 * math.sin(self._phase * 0.8 + i * 0.55)
                target = idle_wave + self._target_level * 0.88 * envelope * ripple
                target = max(0.11, min(1.0, target))
                # Smooth spring-like interpolation
                self._bar_heights[i] += (target - self._bar_heights[i]) * 0.34
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        p = self._palette
        cap = self._capsule_rect()
        radius = cap.height() / 2.0

        # Soft layered drop shadow (lightweight & clean without QGraphicsDropShadowEffect bugs)
        shadow_alpha = 52 if p.is_dark else 26
        for step in (6, 4, 2):
            srect = cap.adjusted(-step * 0.45, step * 0.35, step * 0.45, step * 0.85)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, max(4, shadow_alpha // step)))
            painter.drawRoundedRect(srect, radius + step * 0.4, radius + step * 0.4)

        # Main capsule body
        painter.setBrush(QColor(p.pill_bg))
        painter.setPen(QPen(QColor(p.pill_border), 1.25))
        painter.drawRoundedRect(cap, radius, radius)

        # 1. Left: Circular subtle cancel button (✕)
        c_rect = self._cancel_rect()
        c_bg = QColor(p.pill_cancel_hover if self._hover_btn == "cancel" else p.pill_cancel_bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c_bg)
        painter.drawEllipse(c_rect)

        x_pen = QPen(QColor(p.pill_cancel_fg), 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(x_pen)
        cx, cy = c_rect.center().x(), c_rect.center().y()
        arm = 4.6
        painter.drawLine(QPointF(cx - arm, cy - arm), QPointF(cx + arm, cy + arm))
        painter.drawLine(QPointF(cx + arm, cy - arm), QPointF(cx - arm, cy + arm))

        # 2. Right: Solid high-contrast circular confirm/stop button (✓)
        ok_rect = self._confirm_rect()
        if self._mode == "processing":
            ok_bg = QColor(p.pill_cancel_bg)
            check_color = QColor(p.text_muted)
        else:
            ok_bg = QColor(p.accent_hover if self._hover_btn == "confirm" else p.accent)
            check_color = QColor("#FFFFFF")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ok_bg)
        painter.drawEllipse(ok_rect)

        chk_pen = QPen(check_color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(chk_pen)
        ox, oy = ok_rect.center().x(), ok_rect.center().y()
        chk = QPainterPath()
        chk.moveTo(ox - 5.2, oy + 0.4)
        chk.lineTo(ox - 1.4, oy + 4.2)
        chk.lineTo(ox + 5.6, oy - 3.8)
        painter.drawPath(chk)

        # 3. Center: Live audio waveform OR minimal processing animation
        wave_left = c_rect.right() + 14
        wave_right = ok_rect.left() - 14
        wave_w = max(20.0, wave_right - wave_left)
        mid_y = cap.center().y()

        painter.setPen(Qt.PenStyle.NoPen)
        if self._mode == "processing":
            # Clean minimal 5-dot pulsing loader
            dot_count = 5
            spacing = wave_w / (dot_count + 1)
            accent_q = QColor(p.accent)
            for i in range(dot_count):
                pulse = 0.5 + 0.5 * math.sin(self._phase * 1.15 - i * 0.75)
                r = 2.6 + pulse * 2.1
                color = QColor(accent_q)
                color.setAlpha(int(95 + pulse * 160))
                painter.setBrush(color)
                dx = wave_left + spacing * (i + 1)
                dy = mid_y - pulse * 3.0 + 1.5
                painter.drawEllipse(QPointF(dx, dy), r, r)
        else:
            # Smooth live audio waveform bars
            bar_w = 3.0
            step_x = (wave_w - bar_w) / max(1, self.NUM_BARS - 1)
            max_h = cap.height() * 0.56
            wave_color = QColor(p.pill_wave)
            accent_color = QColor(p.accent)

            for i, h_norm in enumerate(self._bar_heights):
                bh = max(4.0, h_norm * max_h)
                bx = wave_left + i * step_x
                by = mid_y - bh / 2.0
                # Subtle accent tint on louder peaks
                blend = max(0.0, min(1.0, (h_norm - 0.35) * 1.4))
                col = QColor(
                    int(wave_color.red() * (1 - blend) + accent_color.red() * blend),
                    int(wave_color.green() * (1 - blend) + accent_color.green() * blend),
                    int(wave_color.blue() * (1 - blend) + accent_color.blue() * blend),
                    int(165 + h_norm * 90),
                )
                painter.setBrush(col)
                painter.drawRoundedRect(QRectF(bx, by, bar_w, bh), bar_w / 2.0, bar_w / 2.0)

        painter.end()
