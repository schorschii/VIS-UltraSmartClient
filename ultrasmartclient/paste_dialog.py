"""Einfügen als …: add the copied object to the current object as a Bezug."""
import threading

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QRadioButton,
    QStyle, QToolButton, QVBoxLayout, QWidget,
)

from . import gui
from .user_selection import TreeRequest


def option(title, description, parent_layout):
    radio = QRadioButton(title)
    font = radio.font()
    font.setPointSizeF(font.pointSizeF() * 1.3)
    radio.setFont(font)
    parent_layout.addWidget(radio)
    text = QLabel(description)
    text.setWordWrap(True)
    text.setContentsMargins(24, 0, 0, 4)
    parent_layout.addWidget(text)
    return radio, text


def object_row(title, entry):
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.addWidget(QLabel(title))
    row = QHBoxLayout()
    row.setContentsMargins(8, 4, 0, 0)
    icon = QLabel()
    icon.setPixmap(gui.object_icon(entry.get('icon_id', entry.get('object_kind') or 0)).pixmap(QSize(32, 32)))
    row.addWidget(icon)
    name = QLabel(entry.get('name', ''))
    name.setTextFormat(Qt.TextFormat.PlainText)
    name.setWordWrap(True)
    font = name.font()
    font.setBold(True)
    name.setFont(font)
    row.addWidget(name, 1)
    layout.addLayout(row)
    return box


class PasteDialog(QDialog):
    """Asks how the copied object (source) is inserted into the current object (target)."""

    def __init__(self, api, source, target, parent=None):
        super().__init__(parent)
        self.api = api
        self.source, self.target = source, target
        self.editor = None
        self.busy = False
        self.closed = False
        self.workers = set()
        self.setWindowTitle('Einfügen')
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        heading = QLabel('Wie möchten Sie einfügen?')
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.7)
        heading.setFont(font)
        layout.addWidget(heading)

        self.reference, _ = option('Bezug', 'Legt einen Bezug zum kopierten Objekt an.', layout)
        self.reference.setChecked(True)
        form = QFormLayout()
        form.setContentsMargins(24, 2, 0, 8)
        self.reference_type = QComboBox()
        self.reference_type.setEnabled(False)
        self.remark = QLineEdit()
        self.remark.setClearButtonEnabled(True)
        form.addRow('Bezugstyp', self.reference_type)
        form.addRow('Bemerkung', self.remark)
        layout.addLayout(form)
        for title, description in (
                ('Davor einsortieren', 'Ändert die Heftung des Objektes, sodass es vor dem Zielobjekt einsortiert wird.'),
                ('Danach einsortieren', 'Ändert die Heftung des Objektes, sodass es nach dem Zielobjekt einsortiert wird.')):
            radio, text = option(title, description, layout)
            for widget in (radio, text):
                widget.setEnabled(False)
                widget.setToolTip('Im Prototyp nicht implementiert')

        footer = QHBoxLayout()
        self.details_button = QToolButton()
        self.details_button.setText('Details')
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.setAutoRaise(True)
        self.details_button.toggled.connect(self.toggle_details)
        footer.addWidget(self.details_button)
        footer.addStretch()
        buttons = QDialogButtonBox()
        self.paste_button = buttons.addButton('Einfügen', QDialogButtonBox.ButtonRole.AcceptRole)
        self.paste_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton))
        self.paste_button.setEnabled(False)
        self.paste_button.setDefault(True)
        self.paste_button.clicked.connect(self.paste)
        cancel = buttons.addButton('Abbrechen', QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

        self.details = QWidget()
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(object_row('Zwischenablage', source))
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        details_layout.addWidget(line)
        details_layout.addWidget(object_row('Zielobjekt', target))
        self.details.hide()
        layout.addWidget(self.details)

        self.status = QLabel('Bezugstypen werden geladen …')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        layout.addStretch()
        self.finished.connect(self.dialog_closed)
        self.request(self.api.open_paste, (source['id'], source['object_kind'], target['object_kind']),
                     self.opened, self.status.setText)

    def toggle_details(self, shown):
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)
        self.details.setVisible(shown)
        self.adjustSize()

    def request(self, callback, args, completed, failed):
        worker = TreeRequest()
        self.workers.add(worker)

        def finish(result, error):
            self.workers.discard(worker)
            if self.closed:
                # The dialog is gone; a session opened meanwhile must still be closed.
                if not error and callback == self.api.open_paste:
                    self.close_editor(result)
                return
            if error:
                failed(error)
            else:
                completed(result)
        worker.finished.connect(finish, Qt.ConnectionType.QueuedConnection)
        threading.Thread(target=worker.run, args=(callback, args), daemon=True).start()

    def opened(self, editor):
        self.editor = editor
        for text, type_id in editor['types']:
            self.reference_type.addItem(text, type_id)
        self.reference_type.setEnabled(True)
        self.paste_button.setEnabled(True)
        self.status.setText('')

    def paste(self):
        if self.busy or self.editor is None:
            return
        self.busy = True
        for widget in (self.reference_type, self.remark, self.paste_button):
            widget.setEnabled(False)
        self.status.setText('Bezug wird angelegt …')

        def done(_result):
            self.editor = None  # both sessions are closed by the server call
            self.accept()

        def failed(error):
            # The copied object's session is closed after any attempt; the dialog can only be closed then.
            self.busy = False
            self.editor = None
            self.status.setText('Bezug konnte nicht angelegt werden: ' + error)
        self.request(self.api.paste_reference,
                     (self.editor, self.source['id'], self.source['object_kind'], self.target['id'],
                      self.target['object_kind'], self.reference_type.currentData(), self.remark.text().strip()),
                     done, failed)

    def reject(self):
        if not self.busy:
            super().reject()

    def close_editor(self, editor):
        if editor is not None:
            threading.Thread(target=self.api.close_paste, args=(editor,), daemon=True).start()

    def dialog_closed(self, *_args):
        self.closed = True
        self.close_editor(self.editor)
        self.editor = None
