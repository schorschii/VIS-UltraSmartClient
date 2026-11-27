"""Neue Verknüpfung: name and URL of a new link."""
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QStyle, QVBoxLayout, QWidget

from . import gui


class LinkDialog(QDialog):
    """Name and URL of a new Verknüpfung, entered in the server's LINKS session."""

    def __init__(self, api, editor, parent=None):
        super().__init__(parent)
        self.api, self.editor = api, editor
        self.worker = None
        self.result_state = None
        self.setWindowTitle('Neue Verknüpfung')
        self.resize(460, 150)
        layout = QVBoxLayout(self)
        self.form = QWidget()
        form = QFormLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText('https://')
        form.addRow('Name', self.name)
        form.addRow('URL', self.url)
        layout.addWidget(self.form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        layout.addStretch()
        self.buttons = QDialogButtonBox()
        self.apply_button = self.buttons.addButton('Übernehmen', QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton))
        cancel_button = self.buttons.addButton('Abbrechen', QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self.buttons.accepted.connect(self.apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name.textChanged.connect(self.update_buttons)
        self.url.textChanged.connect(self.update_buttons)
        self.update_buttons()
        self.name.setFocus()

    def update_buttons(self):
        self.apply_button.setEnabled(self.worker is None and bool(self.url.text().strip()))

    def apply(self):
        if self.apply_button.isEnabled():
            self.run_operation('save_link', (self.editor, self.name.text().strip(), self.url.text().strip()), True)

    def reject(self):
        if self.worker is None:
            self.run_operation('cancel_link_editor', (self.editor,), False)

    def closeEvent(self, event):
        event.ignore()
        self.reject()

    def run_operation(self, operation, args, accept):
        self.form.setEnabled(False)
        self.buttons.setEnabled(False)
        self.error.setText('Verknüpfung wird gespeichert …' if accept else '')
        self.worker = gui.WorkflowWorker()
        self.worker.finished.connect(lambda result, error: self.finished_operation(result, error, accept))
        threading.Thread(target=self.worker.run, args=(self.api, operation, args), daemon=True).start()

    def finished_operation(self, result, error, accept):
        self.worker = None
        self.form.setEnabled(True)
        self.buttons.setEnabled(True)
        self.update_buttons()
        self.result_state = result
        if accept and error:
            self.error.setText(error)  # the LINKS session stays open for a correction
        elif accept:
            super().accept()
        else:
            # Close even if the server rejects the cancel.
            super().reject()
