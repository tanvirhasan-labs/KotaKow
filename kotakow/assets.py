"""Procedural icon generator for Kota Kow (PySide6 QIcon + standalone Windows .ico).

Works both at runtime (rendering crisp high-DPI vector icons for the window
and System Tray without relying on external image files) and headless in CI
(generating a valid multi-resolution PNG-encoded Windows ``.ico`` file using
only Python's standard library).
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


def _encode_png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """Encode raw RGBA bytes into a valid PNG image using only stdlib."""
    stride = width * 4
    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)  # Filter type 0 (None)
        start = y * stride
        raw_rows.extend(rgba[start : start + stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    compressed = zlib.compress(bytes(raw_rows), level=9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


def _render_icon_rgba(size: int, accent_rgb: tuple[int, int, int] = (13, 148, 136)) -> bytes:
    """Render an anti-aliased rounded-square microphone/waveform badge in RGBA."""
    buf = bytearray(size * size * 4)
    r_bg, g_bg, b_bg = accent_rgb
    # Slightly darker gradient bottom
    r_bot = max(0, int(r_bg * 0.72))
    g_bot = max(0, int(g_bg * 0.72))
    b_bot = max(0, int(b_bg * 0.78))

    cx = (size - 1) / 2.0
    cy = (size - 1) / 2.0
    half = size * 0.45
    corner = size * 0.24

    # 5 crisp vertical waveform bars (Wispr/voice-typing aesthetic)
    bar_specs = [
        (-0.28, 0.14),
        (-0.14, 0.26),
        (0.00, 0.34),
        (0.14, 0.23),
        (0.28, 0.13),
    ]
    bar_half_w = size * 0.042

    for y in range(size):
        t = y / max(1, size - 1)
        cr = int(r_bg + (r_bot - r_bg) * t)
        cg = int(g_bg + (g_bot - g_bg) * t)
        cb = int(b_bg + (b_bot - b_bg) * t)
        for x in range(size):
            # Signed distance to rounded rectangle
            dx = abs(x - cx) - (half - corner)
            dy = abs(y - cy) - (half - corner)
            dist = math.hypot(max(dx, 0.0), max(dy, 0.0)) + min(max(dx, dy), 0.0) - corner
            alpha = max(0.0, min(1.0, 0.5 - dist))
            if alpha <= 0.0:
                continue

            # Check waveform bars (capsule SDF)
            bar_alpha = 0.0
            for bx_norm, bh_norm in bar_specs:
                bx = cx + bx_norm * size
                bh = bh_norm * size
                bdx = abs(x - bx)
                bdy = max(0.0, abs(y - cy) - max(0.0, bh - bar_half_w))
                bdist = math.hypot(bdx, bdy) - bar_half_w
                ba = max(0.0, min(1.0, 0.5 - bdist))
                if ba > bar_alpha:
                    bar_alpha = ba

            pr = int(cr * (1.0 - bar_alpha) + 255 * bar_alpha)
            pg = int(cg * (1.0 - bar_alpha) + 255 * bar_alpha)
            pb = int(cb * (1.0 - bar_alpha) + 255 * bar_alpha)
            pa = int(alpha * 255)

            idx = (y * size + x) * 4
            buf[idx] = pr
            buf[idx + 1] = pg
            buf[idx + 2] = pb
            buf[idx + 3] = pa
    return bytes(buf)


def generate_ico_file(output_path: Path, accent_rgb: tuple[int, int, int] = (13, 148, 136)) -> Path:
    """Write a multi-resolution Windows .ico file (16, 32, 48, 64, 128, 256 px)."""
    sizes = [16, 32, 48, 64, 128, 256]
    pngs = [_encode_png_rgba(s, s, _render_icon_rgba(s, accent_rgb)) for s in sizes]

    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = bytearray()
    for s, png in zip(sizes, pngs):
        dim = 0 if s >= 256 else s
        entries.extend(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset))
        offset += len(png)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(header + bytes(entries) + b"".join(pngs))
    return output_path


def make_qicon(
    accent_hex: str = "#0D9488",
    paused: bool = False,
    recording: bool = False,
):
    """Build a crisp high-DPI PySide6 QIcon dynamically."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap

    icon = QIcon()
    base = QColor("#64748B" if paused else ("#EF4444" if recording else accent_hex))
    darker = base.darker(125)

    for size in (16, 24, 32, 48, 64, 128):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        margin = size * 0.06
        rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
        radius = size * 0.24

        grad = QLinearGradient(0, 0, 0, size)
        grad.setColorAt(0.0, base)
        grad.setColorAt(1.0, darker)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(rect, radius, radius)

        painter.setBrush(QColor("#FFFFFF"))
        if paused:
            # Pause bars
            bar_w = size * 0.13
            bar_h = size * 0.44
            top = (size - bar_h) / 2.0
            gap = size * 0.12
            painter.drawRoundedRect(QRectF(size / 2 - gap / 2 - bar_w, top, bar_w, bar_h), bar_w / 2, bar_w / 2)
            painter.drawRoundedRect(QRectF(size / 2 + gap / 2, top, bar_w, bar_h), bar_w / 2, bar_w / 2)
        else:
            # 5 minimalist waveform bars
            bars = [(-0.28, 0.24), (-0.14, 0.44), (0.0, 0.60), (0.14, 0.40), (0.28, 0.22)]
            bar_w = max(1.5, size * 0.085)
            for bx_norm, bh_norm in bars:
                bh = size * bh_norm
                bx = size / 2.0 + bx_norm * size - bar_w / 2.0
                by = (size - bh) / 2.0
                painter.drawRoundedRect(QRectF(bx, by, bar_w, bh), bar_w / 2, bar_w / 2)

        painter.end()
        icon.addPixmap(pm)

    return icon
