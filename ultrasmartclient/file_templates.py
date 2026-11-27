"""Datei aus Vorlage: choose a Vorlagenkategorie and browse its Vorlagen (VORLAGEN service)."""
import os
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QStyle, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from .user_selection import TreeRequest

# Template name and extension of a list row (UserRole + 1 on column 0).
TEMPLATE_ROLE = Qt.ItemDataRole.UserRole + 1


def template_of(row, columns):
    """(name without extension, extension) of a Vorlagen row; the column identifiers are guessed."""
    identifiers = [identifier for identifier, _ in columns]
    name_id = next((i for i in identifiers if 'name' in i.lower()), identifiers[0] if identifiers else None)
    ext_id = next((i for i in identifiers if 'ext' in i.lower()), None)
    name = (row.get(name_id) or '').strip() if name_id else ''
    extension = (row.get(ext_id) or '').strip() if ext_id else os.path.splitext(name)[1]
    if extension and not extension.startswith('.'):
        extension = '.' + extension
    if extension and name.lower().endswith(extension.lower()):
        name = name[:-len(extension)]
    return name, extension


class FileTemplateDialog(QDialog):
    def __init__(self, api, object_id, object_kind, parent=None):
        super().__init__(parent)
        self.api = api
        self.created_file = None
        self.busy = False
        self.editor = None
        self.closed = False
        self.workers = set()
        self.list_request = 0
        self.setWindowTitle('Vorlagenauswahl')
        self.resize(560, 440)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.category = QComboBox()
        self.category.setEnabled(False)
        self.category.currentIndexChanged.connect(self.category_changed)
        form.addRow(self.category)
        layout.addLayout(form)
        self.templates = QTreeWidget()
        self.templates.setRootIsDecorated(False)
        self.templates.setUniformRowHeights(True)
        self.templates.setAlternatingRowColors(True)
        self.templates.setHeaderHidden(True)
        self.templates.currentItemChanged.connect(self.template_selected)
        layout.addWidget(self.templates, 1)
        file_form = QFormLayout()
        self.filename = QLineEdit()
        self.filename.textChanged.connect(self.update_buttons)
        self.filename.returnPressed.connect(self.add_file)
        file_form.addRow('Dateiname', self.filename)
        layout.addLayout(file_form)
        self.status = QLabel('Vorlagenkategorien werden geladen …')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Schließen')
        self.add_button = buttons.addButton('Hinzufügen', QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton))
        self.add_button.setEnabled(False)
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.add_file)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.finished.connect(self.dialog_closed)
        self.request(self.api.open_file_templates, (object_id, object_kind), self.opened, self.failed)

    def request(self, callback, args, completed, failed):
        worker = TreeRequest()
        self.workers.add(worker)

        def finish(result, error):
            self.workers.discard(worker)
            if self.closed:
                # The dialog is gone; a session opened meanwhile must still be closed.
                if not error and callback == self.api.open_file_templates:
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
        self.category.blockSignals(True)
        for text, category_id in editor['categories']:
            self.category.addItem(text, category_id)
        current = self.category.findData(editor.get('category_id'))
        self.category.setCurrentIndex(max(current, 0))
        self.category.blockSignals(False)
        self.category.setEnabled(True)
        self.category_changed()
        self.update_buttons()

    def failed(self, error):
        self.status.setText(error)

    def category_changed(self, *_args):
        category_id = self.category.currentData()
        if self.editor is None or category_id is None:
            return
        self.list_request += 1
        request = self.list_request
        self.templates.clear()
        self.update_buttons()
        self.status.setText('Vorlagen werden geladen …')

        def loaded(result):
            if request == self.list_request:
                self.show_templates(result)

        def failed(error):
            if request == self.list_request:
                self.status.setText('Vorlagen konnten nicht geladen werden: ' + error)
        self.request(self.api.fetch_file_templates, (self.editor, category_id), loaded, failed)

    def show_templates(self, result):
        columns = result['columns'] or [('', 'Vorlage')]
        self.templates.clear()
        self.templates.setColumnCount(len(columns))
        for row in result['rows']:
            item = QTreeWidgetItem([row.get(identifier, '') for identifier, _ in columns])
            item.setData(0, Qt.ItemDataRole.UserRole, row['_session_index'])
            item.setData(0, TEMPLATE_ROLE, template_of(row, result['columns']))
            self.templates.addTopLevelItem(item)
        for column in range(len(columns)):
            self.templates.resizeColumnToContents(column)
        self.status.setText('' if result['rows'] else 'Keine Vorlagen in dieser Kategorie.')

    def selected_template(self):
        item = self.templates.currentItem()
        return item.data(0, TEMPLATE_ROLE) if item is not None else None

    def template_selected(self, item, _previous=None):
        if item is not None and not self.busy:
            self.filename.setText(item.data(0, TEMPLATE_ROLE)[0])
        self.update_buttons()

    def update_buttons(self, *_args):
        self.add_button.setEnabled(not self.busy and self.editor is not None and bool(self.editor.get('session_id'))
                                   and self.selected_template() is not None and bool(self.filename.text().strip()))

    def add_file(self):
        if not self.add_button.isEnabled():
            return
        template_name, extension = self.selected_template()
        filename = self.filename.text().strip()
        if filename.lower().endswith(extension.lower()):
            filename = filename[:-len(extension)]
        self.busy = True
        for widget in (self.category, self.templates, self.filename):
            widget.setEnabled(False)
        self.update_buttons()
        self.status.setText('Datei wird angelegt …')

        def created(name):
            self.created_file = name
            self.editor = None  # all sessions are closed by the server call
            self.accept()

        def failed(error):
            self.busy = False
            # After 1001 the VORLAGEN session is gone; the dialog can only be closed then.
            if self.editor and self.editor.get('session_id'):
                for widget in (self.category, self.templates, self.filename):
                    widget.setEnabled(True)
            self.update_buttons()
            self.status.setText('Datei konnte nicht angelegt werden: ' + error)
        self.request(self.api.create_file_from_template,
                     (self.editor, self.category.currentData(), template_name, extension, filename,
                      self.templates.currentItem().data(0, Qt.ItemDataRole.UserRole),
                      [self.templates.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole)
                       for row in range(self.templates.topLevelItemCount())]), created, failed)

    def close_editor(self, editor):
        if editor is not None:
            threading.Thread(target=self.api.close_file_templates, args=(editor,), daemon=True).start()

    def dialog_closed(self, *_args):
        self.closed = True
        self.close_editor(self.editor)
        self.editor = None
