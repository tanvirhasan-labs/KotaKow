"""Dictionary tab: Manage custom names, brands, and technical terms injected into AI prompts."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from kotakow.controller import AppController
from kotakow.database import DictionaryTerm


class DictionaryTab(QWidget):
    """Simple, clean add/edit/delete manager for custom dictation vocabulary."""

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 18, 26, 18)
        layout.setSpacing(14)

        intro = QLabel(
            "Add personal names, brands, Bengali/English spellings, or technical terms. "
            "Every entry here is automatically injected into the AI dictation prompt."
        )
        intro.setObjectName("MutedLabel")
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 12px;")
        layout.addWidget(intro)

        # Quick-add Card
        add_card = QFrame()
        add_card.setObjectName("Card")
        ac_layout = QHBoxLayout(add_card)
        ac_layout.setContentsMargins(14, 12, 14, 12)
        ac_layout.setSpacing(10)

        self._term_input = QLineEdit()
        self._term_input.setPlaceholderText("Term or exact spelling (e.g., Kota Kow, PySide6, বসুন্ধরা)...")
        self._term_input.returnPressed.connect(self._add_term)

        self._note_input = QLineEdit()
        self._note_input.setPlaceholderText("Optional hint / context (e.g., app name)")
        self._note_input.returnPressed.connect(self._add_term)

        add_btn = QPushButton("+ Add Term")
        add_btn.setObjectName("PrimaryButton")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_term)

        ac_layout.addWidget(self._term_input, 2)
        ac_layout.addWidget(self._note_input, 1)
        ac_layout.addWidget(add_btn)
        layout.addWidget(add_card)

        # Filter bar + count
        filter_row = QHBoxLayout()
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("Filter dictionary...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self.refresh)

        self._count_lbl = QLabel("0 terms")
        self._count_lbl.setObjectName("Badge")

        filter_row.addWidget(self._filter_input, 1)
        filter_row.addWidget(self._count_lbl)
        layout.addLayout(filter_row)

        # Scrollable Term List
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 2, 6, 12)
        self._list_layout.setSpacing(8)
        scroll.setWidget(self._list_host)

        self.refresh()

    @Slot()
    def _add_term(self) -> None:
        term = self._term_input.text().strip()
        note = self._note_input.text().strip()
        if not term:
            return
        try:
            self.controller.db.add_dictionary_term(term, note)
        except sqlite3.IntegrityError:
            QMessageBox.information(self, "Already Exists", f'"{term}" is already in your dictionary.')
            return
        self._term_input.clear()
        self._note_input.clear()
        self.controller.dictionary_updated.emit()
        self.refresh()

    def _edit_term(self, item: DictionaryTerm) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Dictionary Term")
        form = QFormLayout(dlg)
        term_edit = QLineEdit(item.term)
        note_edit = QLineEdit(item.note)
        form.addRow("Term:", term_edit)
        form.addRow("Note (optional):", note_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_term = term_edit.text().strip()
            if not new_term:
                return
            try:
                self.controller.db.update_dictionary_term(item.id, new_term, note_edit.text().strip())
            except sqlite3.IntegrityError:
                QMessageBox.warning(self, "Duplicate Term", f'"{new_term}" already exists in your dictionary.')
                return
            self.controller.dictionary_updated.emit()
            self.refresh()

    def _delete_term(self, item: DictionaryTerm) -> None:
        self.controller.db.delete_dictionary_term(item.id)
        self.controller.dictionary_updated.emit()
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        while self._list_layout.count():
            w = self._list_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

        terms = self.controller.db.list_dictionary_terms()
        q = self._filter_input.text().strip().lower()
        filtered = [t for t in terms if not q or q in t.term.lower() or q in t.note.lower()]
        self._count_lbl.setText(f"{len(terms)} term{'s' if len(terms) != 1 else ''}")

        if not filtered:
            empty = QLabel(
                "No matching terms." if q else "Your custom dictionary is empty. Add terms above to improve accuracy."
            )
            empty.setObjectName("MutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("padding: 40px 16px; font-size: 13px;")
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch()
            return

        for item in filtered:
            row = QFrame()
            row.setObjectName("HistoryCard")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 12, 10)
            rl.setSpacing(10)

            term_lbl = QLabel(item.term)
            term_lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
            rl.addWidget(term_lbl)

            if item.note:
                note_lbl = QLabel(item.note)
                note_lbl.setObjectName("Badge")
                rl.addWidget(note_lbl)

            rl.addStretch()

            edit_btn = QPushButton("Edit")
            edit_btn.setObjectName("GhostButton")
            edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            edit_btn.clicked.connect(lambda _c=False, it=item: self._edit_term(it))

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("DangerButton")
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setStyleSheet("padding: 4px 10px; font-size: 12px;")
            del_btn.clicked.connect(lambda _c=False, it=item: self._delete_term(it))

            rl.addWidget(edit_btn)
            rl.addWidget(del_btn)
            self._list_layout.addWidget(row)

        self._list_layout.addStretch()
