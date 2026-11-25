"""History tab: SQLite + Lazy Loading + Collapsible Month/Date dropdowns + Manage History."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, Qt, QTimer, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kotakow.controller import AppController
from kotakow.database import DictationEntry


def _format_month_title(month_key: str) -> str:
    try:
        dt = datetime.strptime(month_key, "%Y-%m")
        return dt.strftime("%B %Y")
    except ValueError:
        return month_key


def _format_day_title(day_key: str) -> str:
    today = date.today()
    yesterday = today - timedelta(days=1)
    if day_key == today.strftime("%Y-%m-%d"):
        return f"Today · {today.strftime('%b %d, %Y')}"
    if day_key == yesterday.strftime("%Y-%m-%d"):
        return f"Yesterday · {yesterday.strftime('%b %d, %Y')}"
    try:
        dt = datetime.strptime(day_key, "%Y-%m-%d")
        return dt.strftime("%A, %b %d, %Y")
    except ValueError:
        return day_key


def _format_time(created_at: str) -> str:
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return created_at


class EntryCard(QFrame):
    """Single dictation item with timestamp, app name, Bengali-safe text, Copy & Delete."""

    def __init__(self, entry: DictationEntry, on_delete) -> None:
        super().__init__()
        self.entry = entry
        self.setObjectName("HistoryCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # Header meta row
        top = QHBoxLayout()
        top.setSpacing(8)

        time_lbl = QLabel(_format_time(entry.created_at))
        time_lbl.setObjectName("MutedLabel")
        time_lbl.setStyleSheet("font-size: 11px; font-weight: 600;")

        app_badge = QLabel(entry.app_name)
        app_badge.setObjectName("AccentBadge")

        eng_badge = QLabel("Gemini" if entry.engine == "gemini" else "Groq")
        eng_badge.setObjectName("Badge")

        words_lbl = QLabel(f"{entry.word_count}w")
        words_lbl.setObjectName("MutedLabel")
        words_lbl.setStyleSheet("font-size: 11px;")

        top.addWidget(time_lbl)
        top.addWidget(app_badge)
        top.addWidget(eng_badge)
        top.addWidget(words_lbl)
        top.addStretch()

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setObjectName("GhostButton")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet("font-size: 12px; padding: 3px 9px;")
        self._copy_btn.clicked.connect(self._copy_text)

        del_btn = QPushButton("✕")
        del_btn.setObjectName("GhostButton")
        del_btn.setToolTip("Delete this item")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFixedWidth(28)
        del_btn.clicked.connect(lambda: on_delete(entry.id))

        top.addWidget(self._copy_btn)
        top.addWidget(del_btn)
        layout.addLayout(top)

        # Text preview (Bengali Unicode friendly)
        text_lbl = QLabel(entry.text)
        text_lbl.setWordWrap(True)
        text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_lbl.setStyleSheet("font-size: 13px; line-height: 1.45;")
        layout.addWidget(text_lbl)

    @Slot()
    def _copy_text(self) -> None:
        QApplication.clipboard().setText(self.entry.text)
        self._copy_btn.setText("Copied ✓")
        QTimer.singleShot(1400, lambda: self._copy_btn.setText("Copy"))


class DayAccordion(QWidget):
    """Collapsible Date dropdown that lazily loads entries from SQLite on expand."""

    def __init__(
        self,
        controller: AppController,
        day_key: str,
        count: int,
        words: int,
        search_query: str,
        expanded: bool,
        on_changed,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.day_key = day_key
        self.search_query = search_query
        self.on_changed = on_changed
        self._loaded = False
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 2, 0, 4)
        layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(6)

        self._title_base = f"{_format_day_title(day_key)}   ({count} · {words:,} words)"
        self._toggle_btn = QPushButton()
        self._toggle_btn.setObjectName("DayAccordionHeader")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self.toggle)

        del_day_btn = QPushButton("Delete day")
        del_day_btn.setObjectName("GhostButton")
        del_day_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_day_btn.setStyleSheet("font-size: 11px; padding: 4px 8px;")
        del_day_btn.clicked.connect(self._delete_this_day)

        hdr_row.addWidget(self._toggle_btn, 1)
        hdr_row.addWidget(del_day_btn)
        layout.addLayout(hdr_row)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(6, 2, 0, 4)
        self._body_layout.setSpacing(8)
        self._body.setVisible(False)
        layout.addWidget(self._body)

        self._update_header_text()
        if expanded:
            self.set_expanded(True)

    def _update_header_text(self) -> None:
        arrow = "▾" if self._expanded else "▸"
        self._toggle_btn.setText(f"{arrow}   {self._title_base}")

    @Slot()
    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        if expanded and not self._loaded:
            self._load_entries()
        self._body.setVisible(expanded)
        self._update_header_text()

    def _load_entries(self) -> None:
        self._loaded = True
        entries = self.controller.db.get_entries_for_day(self.day_key, self.search_query)
        for entry in entries:
            self._body_layout.addWidget(EntryCard(entry, self._delete_single))

    def _delete_single(self, entry_id: int) -> None:
        self.controller.db.delete_entry(entry_id)
        self.controller.history_updated.emit()

    @Slot()
    def _delete_this_day(self) -> None:
        res = QMessageBox.question(
            self,
            "Delete Day",
            f"Delete all dictations from {_format_day_title(self.day_key)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            self.controller.db.delete_day(self.day_key)
            self.controller.history_updated.emit()


class MonthAccordion(QWidget):
    """Collapsible Month dropdown that lazily loads Date dropdowns on expand."""

    def __init__(
        self,
        controller: AppController,
        month_key: str,
        count: int,
        words: int,
        search_query: str,
        expanded: bool,
        on_changed,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.month_key = month_key
        self.search_query = search_query
        self.on_changed = on_changed
        self._loaded = False
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(6)

        self._title_base = f"{_format_month_title(month_key)}   ({count} · {words:,} words)"
        self._toggle_btn = QPushButton()
        self._toggle_btn.setObjectName("AccordionHeader")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self.toggle)

        del_month_btn = QPushButton("Delete month")
        del_month_btn.setObjectName("GhostButton")
        del_month_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_month_btn.setStyleSheet("font-size: 11px; padding: 5px 9px;")
        del_month_btn.clicked.connect(self._delete_this_month)

        hdr_row.addWidget(self._toggle_btn, 1)
        hdr_row.addWidget(del_month_btn)
        layout.addLayout(hdr_row)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 2, 0, 2)
        self._body_layout.setSpacing(4)
        self._body.setVisible(False)
        layout.addWidget(self._body)

        self._update_header_text()
        if expanded:
            self.set_expanded(True)

    def _update_header_text(self) -> None:
        arrow = "▾" if self._expanded else "▸"
        self._toggle_btn.setText(f"{arrow}   {self._title_base}")

    @Slot()
    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        if expanded and not self._loaded:
            self._load_days()
        self._body.setVisible(expanded)
        self._update_header_text()

    def _load_days(self) -> None:
        self._loaded = True
        today_key = date.today().strftime("%Y-%m-%d")
        days = self.controller.db.get_days_in_month(self.month_key, self.search_query)
        has_search = bool(self.search_query.strip())
        for d in days:
            # Today is expanded by default; older dates start collapsed (unless searching)
            expand_day = has_search or (d["day_key"] == today_key)
            self._body_layout.addWidget(
                DayAccordion(
                    controller=self.controller,
                    day_key=d["day_key"],
                    count=d["count"],
                    words=d["words"],
                    search_query=self.search_query,
                    expanded=expand_day,
                    on_changed=self.on_changed,
                )
            )

    @Slot()
    def _delete_this_month(self) -> None:
        res = QMessageBox.question(
            self,
            "Delete Month",
            f"Delete all dictations from {_format_month_title(self.month_key)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            self.controller.db.delete_month(self.month_key)
            self.controller.history_updated.emit()


class HistoryTab(QWidget):
    """Searchable, lazy-loaded History view with full Manage History controls."""

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 18, 26, 18)
        layout.setSpacing(12)

        # Search + Manage History toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search dictations or app names (বাংলা / English)...")
        self._search_input.setClearButtonEnabled(True)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self.refresh)
        self._search_input.textChanged.connect(lambda _text="": self._search_timer.start())

        self._manage_btn = QPushButton("Manage History ▾")
        self._manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manage_menu = self._build_manage_menu()
        self._manage_btn.setMenu(self._manage_menu)

        toolbar.addWidget(self._search_input, 1)
        toolbar.addWidget(self._manage_btn)
        layout.addLayout(toolbar)

        # Rolling 90-day info caption
        info_lbl = QLabel("Records older than 90 days are automatically purged on startup. Click any month or date to expand.")
        info_lbl.setObjectName("MutedLabel")
        info_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(info_lbl)

        # Lazy-loaded Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 4, 6, 12)
        self._list_layout.setSpacing(6)
        scroll.setWidget(self._list_host)

        self.controller.history_updated.connect(self.refresh)
        self.refresh()

    def _build_manage_menu(self) -> QMenu:
        menu = QMenu(self)

        actions = [
            ("Delete an Entire Day…", lambda _c=False: self._action_delete_day()),
            ("Delete an Entire Month…", lambda _c=False: self._action_delete_month()),
            None,
            ("Delete Last 24 Hours", lambda _c=False: self._confirm_delete_recent(hours=24, label="the last 24 hours")),
            ("Delete Last 7 Days", lambda _c=False: self._confirm_delete_recent(days=7, label="the last 7 days")),
            ("Delete Last 30 Days", lambda _c=False: self._confirm_delete_recent(days=30, label="the last 30 days")),
            None,
            ("Keep Last X Days & Delete Older…", lambda _c=False: self._action_keep_last_x_days()),
            ("Delete Custom Date Range…", lambda _c=False: self._action_delete_range()),
            None,
            ("Clear All History…", lambda _c=False: self._action_clear_all()),
        ]
        for item in actions:
            if item is None:
                menu.addSeparator()
            else:
                text, handler = item
                act = QAction(text, menu)
                act.triggered.connect(handler)
                menu.addAction(act)
        return menu

    @Slot()
    def refresh(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        query = self._search_input.text().strip()
        months = self.controller.db.get_months(query)

        if not months:
            empty = QLabel(
                "No matching dictations found." if query else "Your dictation history will appear here once you start speaking."
            )
            empty.setObjectName("MutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("padding: 48px 16px; font-size: 13px;")
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch()
            return

        current_month = date.today().strftime("%Y-%m")
        for idx, m in enumerate(months):
            # Expand current month (or first month when searching) so Today is ready immediately
            expand_month = bool(query) or (m["month_key"] == current_month) or (idx == 0)
            self._list_layout.addWidget(
                MonthAccordion(
                    controller=self.controller,
                    month_key=m["month_key"],
                    count=m["count"],
                    words=m["words"],
                    search_query=query,
                    expanded=expand_month,
                    on_changed=self.refresh,
                )
            )
        self._list_layout.addStretch()

    # ------------------------------------------------------------------
    # Manage History Dialogs & Handlers
    # ------------------------------------------------------------------

    def _confirm_delete_recent(self, label: str, hours: int | None = None, days: int | None = None) -> None:
        res = QMessageBox.question(
            self,
            "Delete Recent History",
            f"Permanently delete all dictations from {label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        if hours is not None:
            self.controller.db.delete_last_hours(hours)
        elif days is not None:
            self.controller.db.delete_last_days(days)
        self.controller.history_updated.emit()

    def _action_delete_day(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Delete an Entire Day")
        form = QFormLayout(dlg)
        picker = QDateEdit(QDate.currentDate())
        picker.setCalendarPopup(True)
        picker.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Select date:", picker)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            day_key = picker.date().toString("yyyy-MM-dd")
            res = QMessageBox.question(
                self,
                "Confirm Delete Day",
                f"Delete all dictations recorded on {day_key}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                self.controller.db.delete_day(day_key)
                self.controller.history_updated.emit()

    def _action_delete_month(self) -> None:
        months = self.controller.db.get_months()
        if not months:
            QMessageBox.information(self, "History Empty", "There are no months to delete.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Delete an Entire Month")
        form = QFormLayout(dlg)
        combo = QComboBox()
        for m in months:
            combo.addItem(f"{_format_month_title(m['month_key'])} ({m['count']} items)", m["month_key"])
        form.addRow("Select month:", combo)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            mkey = str(combo.currentData())
            res = QMessageBox.question(
                self,
                "Confirm Delete Month",
                f"Delete all dictations from {_format_month_title(mkey)}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                self.controller.db.delete_month(mkey)
                self.controller.history_updated.emit()

    def _action_keep_last_x_days(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Keep Last X Days & Delete Older")
        form = QFormLayout(dlg)
        spin = QSpinBox()
        spin.setRange(1, 90)
        spin.setValue(30)
        spin.setSuffix(" days")
        form.addRow("Keep history from the last:", spin)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            days = spin.value()
            res = QMessageBox.question(
                self,
                "Confirm Purge",
                f"Delete all dictation records older than the last {days} days?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                self.controller.db.purge_older_than_days(days)
                self.controller.history_updated.emit()

    def _action_delete_range(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Delete Custom Date Range")
        form = QFormLayout(dlg)
        start_edit = QDateEdit(QDate.currentDate().addDays(-7))
        start_edit.setCalendarPopup(True)
        start_edit.setDisplayFormat("yyyy-MM-dd")
        end_edit = QDateEdit(QDate.currentDate())
        end_edit.setCalendarPopup(True)
        end_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow("From date:", start_edit)
        form.addRow("To date:", end_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            s = start_edit.date().toString("yyyy-MM-dd")
            e = end_edit.date().toString("yyyy-MM-dd")
            res = QMessageBox.question(
                self,
                "Confirm Delete Range",
                f"Delete all dictations between {s} and {e} (inclusive)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                self.controller.db.delete_date_range(s, e)
                self.controller.history_updated.emit()

    def _action_clear_all(self) -> None:
        res = QMessageBox.warning(
            self,
            "Clear All History",
            "Are you sure you want to permanently delete ALL dictation history?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if res == QMessageBox.StandardButton.Yes:
            self.controller.db.clear_all_history()
            self.controller.history_updated.emit()
