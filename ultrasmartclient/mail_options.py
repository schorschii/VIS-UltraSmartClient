"""E-mail notification settings stored as VIS user properties."""
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget,
)

from .gui import Section
from .user_selection import TreeRequest

# (section title, [(checkbox label, user property name)])
MAIL_OPTION_SECTIONS = [
    ('E-Mail Benachrichtigungen', [
        ('Geschäftsgangverfügungen', 'MailSendOptionSendGGV'),
        ('Zeichnungen', 'MailSendOptionSendZEI'),
        ('Wiedervorlagen', 'MailSendOptionSendWV'),
    ]),
    ('E-Mail Benachrichtigungen in Stellvertretung', [
        ('Geschäftsgangverfügungen', 'MailSendOptionSendGGVStellv'),
        ('Zeichnungen', 'MailSendOptionSendZEIStellv'),
        ('Wiedervorlagen', 'MailSendOptionSendWVStellv'),
    ]),
]


def property_enabled(value):
    return str(value).strip().lower() in ('1', 'true')


class MailOptionsDialog(QDialog):
    """Checkboxes are saved on the server as soon as they are toggled."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.closed = False
        self.pending = {}
        self.checkboxes = {}
        self.setWindowTitle('E-Mail Optionen')
        self.resize(380, 330)
        layout = QVBoxLayout(self)
        for title, options in MAIL_OPTION_SECTIONS:
            content = QWidget()
            options_layout = QVBoxLayout(content)
            options_layout.setContentsMargins(8, 6, 8, 10)
            options_layout.setSpacing(8)
            for label, name in options:
                checkbox = QCheckBox(label)
                checkbox.setEnabled(False)
                checkbox.toggled.connect(lambda checked, name=name: self.option_toggled(name, checked))
                options_layout.addWidget(checkbox)
                self.checkboxes[name] = checkbox
            layout.addWidget(Section(title, content))
        layout.addStretch()
        self.status = QLabel('Einstellungen werden geladen …')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Schließen')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.finished.connect(self.dialog_closed)
        self.request('load', self.api.fetch_user_properties, (), self.loaded, self.load_failed)

    def dialog_closed(self, *_args):
        self.closed = True

    def request(self, key, callback, args, completed, failed):
        worker = TreeRequest(self)
        self.pending[key] = worker
        def finish(result, error):
            self.pending.pop(key, None)
            worker.deleteLater()
            if self.closed:
                return
            if error:
                failed(error)
            else:
                completed(result)
        worker.finished.connect(finish)
        threading.Thread(target=worker.run, args=(callback, args), daemon=True).start()

    def loaded(self, properties):
        for name, checkbox in self.checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(property_enabled(properties.get(name, '0')))
            checkbox.blockSignals(False)
            checkbox.setEnabled(True)
        self.status.setText('')

    def load_failed(self, error):
        self.status.setText('Einstellungen konnten nicht geladen werden: ' + error)

    def option_toggled(self, name, checked):
        checkbox = self.checkboxes[name]
        checkbox.setEnabled(False)
        self.status.setText('Einstellung wird gespeichert …')

        def saved(_result):
            checkbox.setEnabled(True)
            if not any(key != 'load' for key in self.pending):
                self.status.setText('')

        def failed(error):
            # Show the state that is actually stored on the server.
            checkbox.blockSignals(True)
            checkbox.setChecked(not checked)
            checkbox.blockSignals(False)
            checkbox.setEnabled(True)
            self.status.setText('Einstellung konnte nicht gespeichert werden: ' + error)

        self.request(name, self.api.set_user_property, (name, '1' if checked else '0'), saved, failed)
