"""Dashboard tab: 4 crisp metric cards backed by real local SQLite data.

Cards:
1. Total Words & Average WPM
2. Daily Streak & 90-Day GitHub/Wispr-style Activity Heatmap
3. Desktop App Usage (percentage bars per app)
4. Today's API Usage (live daily request counter for Gemini & Groq)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import QRectF, Qt, Slot
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from kotakow.controller import AppController
from kotakow.ui.theme import ThemePalette, get_palette


class ActivityHeatmapWidget(QWidget):
    """GitHub/Wispr-style 13-week (91-day) calendar activity grid."""

    WEEKS = 13
    DAYS = 7
    CELL = 14
    GAP = 4
    LEFT_LABEL_W = 28
    TOP_LABEL_H = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: dict[str, dict[str, int]] = {}
        self._palette = get_palette("system", "teal")
        self._cells: list[tuple[QRectF, date, int, int]] = []
        self.setMouseTracking(True)
        w = self.LEFT_LABEL_W + self.WEEKS * (self.CELL + self.GAP) + 4
        h = self.TOP_LABEL_H + self.DAYS * (self.CELL + self.GAP) + 4
        self.setMinimumSize(w, h)
        self.setFixedHeight(h)

    def set_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def set_data(self, heatmap: dict[str, dict[str, int]]) -> None:
        self._data = heatmap or {}
        self.update()

    def _level_color(self, words: int) -> QColor:
        p = self._palette
        if words <= 0:
            return QColor("#222836" if p.is_dark else "#E8EEF5")
        accent = QColor(p.accent)
        if words < 40:
            alpha = 85
        elif words < 150:
            alpha = 145
        elif words < 400:
            alpha = 205
        else:
            alpha = 255
        c = QColor(accent)
        c.setAlpha(alpha)
        return c

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._palette

        today = date.today()
        # Align the grid so column 0 starts on a Sunday ~12-13 weeks ago
        days_since_sunday = (today.weekday() + 1) % 7
        end_sunday = today - timedelta(days=days_since_sunday)
        start_date = end_sunday - timedelta(weeks=self.WEEKS - 1)

        # Day-of-week labels (Mon, Wed, Fri)
        label_font = QFont("Nirmala UI", 8)
        painter.setFont(label_font)
        painter.setPen(QColor(p.text_muted))
        for row_idx, lbl in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
            y = self.TOP_LABEL_H + row_idx * (self.CELL + self.GAP) + self.CELL - 2
            painter.drawText(0, int(y), lbl)

        # Month headers at first week of each new month
        seen_months: set[tuple[int, int]] = set()
        self._cells.clear()

        for col in range(self.WEEKS):
            col_date = start_date + timedelta(weeks=col)
            ym = (col_date.year, col_date.month)
            x = self.LEFT_LABEL_W + col * (self.CELL + self.GAP)
            if ym not in seen_months:
                seen_months.add(ym)
                painter.setPen(QColor(p.text_muted))
                painter.drawText(int(x), 12, col_date.strftime("%b"))

            for row in range(self.DAYS):
                d = col_date + timedelta(days=row)
                if d > today:
                    continue
                y = self.TOP_LABEL_H + row * (self.CELL + self.GAP)
                rect = QRectF(x, y, self.CELL, self.CELL)
                info = self._data.get(d.strftime("%Y-%m-%d"), {})
                words = int(info.get("words", 0))
                sessions = int(info.get("sessions", 0))

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._level_color(words))
                painter.drawRoundedRect(rect, 3.2, 3.2)
                self._cells.append((rect, d, words, sessions))

        painter.end()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        for rect, d, words, sessions in self._cells:
            if rect.contains(pos):
                if words > 0:
                    tip = f"{d.strftime('%b %d, %Y')}: {words:,} words ({sessions} dictations)"
                else:
                    tip = f"{d.strftime('%b %d, %Y')}: No dictations"
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class DashboardTab(QWidget):
    """4-card analytics dashboard backed by local SQLite."""

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self._palette = get_palette(controller.config.theme_mode, controller.config.accent_color)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(26, 20, 26, 26)
        body_layout.setSpacing(16)
        scroll.setWidget(body)

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        body_layout.addLayout(grid)

        # ------------------------------------------------------------------
        # Card 1: Total Words & Average WPM
        # ------------------------------------------------------------------
        c1 = self._make_card()
        c1_l = QVBoxLayout(c1)
        c1_l.setContentsMargins(20, 18, 20, 18)
        c1_l.setSpacing(8)

        c1_hdr = QLabel("Total Words & Speaking Speed")
        c1_hdr.setObjectName("SectionTitle")
        self._words_metric = QLabel("0")
        self._words_metric.setObjectName("BigMetric")

        c1_sub_row = QHBoxLayout()
        c1_sub_row.setSpacing(8)
        self._wpm_badge = QLabel("0.0 WPM avg")
        self._wpm_badge.setObjectName("AccentBadge")
        self._sessions_badge = QLabel("0 dictations")
        self._sessions_badge.setObjectName("Badge")
        c1_sub_row.addWidget(self._wpm_badge)
        c1_sub_row.addWidget(self._sessions_badge)
        c1_sub_row.addStretch()

        c1_note = QLabel("Tracked locally over your rolling 90-day dictation history.")
        c1_note.setObjectName("MutedLabel")
        c1_note.setWordWrap(True)
        c1_note.setStyleSheet("font-size: 12px;")

        c1_l.addWidget(c1_hdr)
        c1_l.addWidget(self._words_metric)
        c1_l.addLayout(c1_sub_row)
        c1_l.addStretch()
        c1_l.addWidget(c1_note)
        grid.addWidget(c1, 0, 0)

        # ------------------------------------------------------------------
        # Card 2: Today's API Usage (Gemini & Groq)
        # ------------------------------------------------------------------
        c4 = self._make_card()
        c4_l = QVBoxLayout(c4)
        c4_l.setContentsMargins(20, 18, 20, 18)
        c4_l.setSpacing(10)

        c4_hdr = QLabel("Today's API Usage")
        c4_hdr.setObjectName("SectionTitle")
        c4_l.addWidget(c4_hdr)

        api_row = QHBoxLayout()
        api_row.setSpacing(14)

        # Gemini counter box
        gem_box = QFrame()
        gem_box.setObjectName("HistoryCard")
        gem_l = QVBoxLayout(gem_box)
        gem_l.setContentsMargins(14, 10, 14, 10)
        gem_l.setSpacing(2)
        gem_title = QLabel("Google Gemini")
        gem_title.setObjectName("MutedLabel")
        gem_title.setStyleSheet("font-size: 11px; font-weight: 600;")
        self._gemini_count_lbl = QLabel("0")
        self._gemini_count_lbl.setStyleSheet("font-size: 24px; font-weight: 700;")
        self._gemini_status_lbl = QLabel("requests today")
        self._gemini_status_lbl.setObjectName("MutedLabel")
        self._gemini_status_lbl.setStyleSheet("font-size: 11px;")
        gem_l.addWidget(gem_title)
        gem_l.addWidget(self._gemini_count_lbl)
        gem_l.addWidget(self._gemini_status_lbl)

        # Groq counter box
        groq_box = QFrame()
        groq_box.setObjectName("HistoryCard")
        groq_l = QVBoxLayout(groq_box)
        groq_l.setContentsMargins(14, 10, 14, 10)
        groq_l.setSpacing(2)
        groq_title = QLabel("Groq Backup")
        groq_title.setObjectName("MutedLabel")
        groq_title.setStyleSheet("font-size: 11px; font-weight: 600;")
        self._groq_count_lbl = QLabel("0")
        self._groq_count_lbl.setStyleSheet("font-size: 24px; font-weight: 700;")
        self._groq_status_lbl = QLabel("requests today")
        self._groq_status_lbl.setObjectName("MutedLabel")
        self._groq_status_lbl.setStyleSheet("font-size: 11px;")
        groq_l.addWidget(groq_title)
        groq_l.addWidget(self._groq_count_lbl)
        groq_l.addWidget(self._groq_status_lbl)

        api_row.addWidget(gem_box, 1)
        api_row.addWidget(groq_box, 1)
        c4_l.addLayout(api_row)

        self._routing_note = QLabel()
        self._routing_note.setObjectName("MutedLabel")
        self._routing_note.setStyleSheet("font-size: 11px;")
        self._routing_note.setWordWrap(True)
        c4_l.addWidget(self._routing_note)
        grid.addWidget(c4, 0, 1)

        # ------------------------------------------------------------------
        # Card 3: Daily Streak & Activity Heatmap
        # ------------------------------------------------------------------
        c2 = self._make_card()
        c2_l = QVBoxLayout(c2)
        c2_l.setContentsMargins(20, 18, 20, 18)
        c2_l.setSpacing(10)

        c2_top = QHBoxLayout()
        c2_hdr = QLabel("Daily Streak & Activity Heatmap")
        c2_hdr.setObjectName("SectionTitle")
        self._streak_badge = QLabel("🔥 0 day streak")
        self._streak_badge.setObjectName("AccentBadge")
        c2_top.addWidget(c2_hdr)
        c2_top.addStretch()
        c2_top.addWidget(self._streak_badge)
        c2_l.addLayout(c2_top)

        self._heatmap = ActivityHeatmapWidget()
        c2_l.addWidget(self._heatmap)

        self._active_days_lbl = QLabel("0 active days in the last 90 days")
        self._active_days_lbl.setObjectName("MutedLabel")
        self._active_days_lbl.setStyleSheet("font-size: 11px;")
        c2_l.addWidget(self._active_days_lbl)
        grid.addWidget(c2, 1, 0)

        # ------------------------------------------------------------------
        # Card 4: Desktop App Usage
        # ------------------------------------------------------------------
        c3 = self._make_card()
        c3_l = QVBoxLayout(c3)
        c3_l.setContentsMargins(20, 18, 20, 18)
        c3_l.setSpacing(10)

        c3_hdr = QLabel("Desktop App Usage")
        c3_hdr.setObjectName("SectionTitle")
        c3_l.addWidget(c3_hdr)

        self._apps_container = QVBoxLayout()
        self._apps_container.setSpacing(8)
        c3_l.addLayout(self._apps_container)
        c3_l.addStretch()
        grid.addWidget(c3, 1, 1)

        body_layout.addStretch()

        self.controller.history_updated.connect(self.refresh)
        self.controller.config_changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _make_card() -> QFrame:
        f = QFrame()
        f.setObjectName("Card")
        return f

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self._heatmap.set_palette(palette)
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        stats: dict[str, Any] = self.controller.db.get_dashboard_stats()
        cfg = self.controller.config

        self._words_metric.setText(f"{stats['total_words']:,}")
        self._wpm_badge.setText(f"{stats['avg_wpm']:.1f} WPM avg")
        sess = stats["total_sessions"]
        self._sessions_badge.setText(f"{sess:,} dictation{'s' if sess != 1 else ''}")

        streak = stats["streak_days"]
        self._streak_badge.setText(f"🔥 {streak} day{'s' if streak != 1 else ''} streak")
        self._heatmap.set_data(stats["heatmap"])
        active_d = stats["active_days_90d"]
        self._active_days_lbl.setText(f"{active_d} active day{'s' if active_d != 1 else ''} in the last 90 days")

        api_today = stats["api_usage_today"]
        self._gemini_count_lbl.setText(str(api_today.get("gemini", 0)))
        self._groq_count_lbl.setText(str(api_today.get("groq", 0)))

        has_g = bool(cfg.gemini_api_key.strip())
        has_q = bool(cfg.groq_api_key.strip())
        self._gemini_status_lbl.setText("Active · Primary" if has_g else "Not configured")
        self._groq_status_lbl.setText(
            "Active · Auto-Fallback" if (has_g and has_q) else ("Active · Primary" if has_q else "Optional backup")
        )
        if has_g and has_q:
            self._routing_note.setText("Smart Routing: Gemini runs first; auto-falls back to Groq on 429/quota.")
        elif has_g:
            self._routing_note.setText("Using Google Gemini direct audio-to-text. Add a Groq key for auto-fallback.")
        elif has_q:
            self._routing_note.setText("Using Groq Whisper Large v3 + Chat cleanup.")
        else:
            self._routing_note.setText("Add your Gemini or Groq API key in Settings to begin dictating.")

        # Rebuild Desktop App Usage bars
        while self._apps_container.count():
            item = self._apps_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        app_usage = stats["app_usage"]
        if not app_usage:
            empty = QLabel("Start dictating in Chrome, WhatsApp, VS Code, or Notepad to see app breakdown.")
            empty.setObjectName("MutedLabel")
            empty.setWordWrap(True)
            empty.setStyleSheet("font-size: 12px;")
            self._apps_container.addWidget(empty)
            return

        p = self._palette
        bar_css = (
            f"QProgressBar {{ border: none; border-radius: 4px; background: {p.card_alt_bg}; height: 7px; }}"
            f"QProgressBar::chunk {{ border-radius: 4px; background: {p.accent}; }}"
        )
        for entry in app_usage:
            row_w = QWidget()
            rl = QVBoxLayout(row_w)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(4)

            top = QHBoxLayout()
            name_lbl = QLabel(entry["app_name"])
            name_lbl.setStyleSheet("font-size: 12px; font-weight: 600;")
            pct_lbl = QLabel(f"{entry['percent']:.0f}%  ({entry['count']})")
            pct_lbl.setObjectName("MutedLabel")
            pct_lbl.setStyleSheet("font-size: 11px;")
            top.addWidget(name_lbl)
            top.addStretch()
            top.addWidget(pct_lbl)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(max(2, int(round(entry["percent"]))))
            bar.setTextVisible(False)
            bar.setFixedHeight(7)
            bar.setStyleSheet(bar_css)

            rl.addLayout(top)
            rl.addWidget(bar)
            self._apps_container.addWidget(row_w)
