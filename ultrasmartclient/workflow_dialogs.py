"""Dialogs for editing a Geschäftsgangverfügung (task) and choosing a Geschäftsgangmuster."""
import threading

from PyQt6.QtCore import QCollator, QDate, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QStyle, QVBoxLayout, QWidget,
)

from . import gui
from .user_selection import UserSelectionDialog


class WorkflowDialog(QDialog):
    def __init__(self, api, editor, parent=None):
        super().__init__(parent)
        self.api, self.editor = api, editor
        self.worker = None
        self.changes = {}
        self.setWindowTitle('Geschäftsgangbearbeitung')
        self.setWindowIcon(parent.windowIcon() if parent else QIcon())
        self.resize(590, 490)
        layout = QVBoxLayout(self)
        self.form = QWidget()
        grid = QGridLayout(self.form)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.inputs = {}
        self.attributes = {a['identifier']: a for a in editor['attributes']}
        created_at = 'angelegt_am' if 'angelegt_am' in self.attributes else 'erzeugt_am'
        created_by = 'angelegt_von_id' if 'angelegt_von_id' in self.attributes else 'erzeugt_von'
        rows = [('stufe', 'Stufe', 'kategorie', 'Kategorie'),
                ('erlassen_von_id', 'Erlassen von', 'erlassen_fuer_id', 'Erlassen für'),
                ('aufgabe', 'Aufgabe', None, None), ('erledigung', 'Vermerk', None, None),
                ('termin', 'Fällig am', 'freigabe', 'Freigabe'),
                ('erledigt_am', 'Erledigt am', None, None),
                (created_at, 'Angelegt am', 'geaendert_am', 'Geändert am'),
                (created_by, 'Angelegt durch', 'geaendert_von', 'Geändert durch')]
        for row, pair in enumerate(rows):
            for column, key, label in ((0, pair[0], pair[1]), (2, pair[2], pair[3])):
                if key is None:
                    continue
                attribute = self.attributes.get(key)
                if attribute is None:
                    continue
                value = attribute['value']
                if key == 'erlassen_fuer_id':
                    field = QPushButton(value or 'Empfänger auswählen …')
                    field.setObjectName('workflowRecipient')
                    field.clicked.connect(self.choose_recipient)
                elif key == 'termin':
                    field = gui.OptionalDateEdit()
                    field.setObjectName('workflowDue')
                    field.setDisplayFormat('dd.MM.yyyy')
                    field.setCalendarPopup(True)
                    field.setSpecialValueText(' ')
                    due = QDate.fromString(value, 'dd.MM.yyyy')
                    field.setDate(due if due.isValid() else field.minimumDate())
                    if not due.isValid():
                        today = QDate.currentDate()
                        field.calendarWidget().setCurrentPage(today.year(), today.month())
                elif key in ('aufgabe', 'erledigung'):
                    field = QPlainTextEdit(value)
                    field.setMinimumHeight(80)
                elif key == 'freigabe':
                    field = QCheckBox()
                    field.setChecked(value.lower() in ('1', 'true'))
                elif attribute['choices']:
                    field = QComboBox()
                    field.addItems(list(dict.fromkeys([value] + attribute['choices'])))
                else:
                    field = QLineEdit(value)
                field.setEnabled(attribute['behavior'] == '1')
                grid.addWidget(QLabel(label), row, column)
                grid.addWidget(field, row, column + 1, 1, 3 if key in ('aufgabe', 'erledigung') else 1)
                self.inputs[key] = field
                if key == 'erledigung' and attribute['choices']:
                    presets = QComboBox()
                    presets.addItem('Vermerk auswählen …')
                    presets.addItems(attribute['choices'])
                    presets.setEnabled(attribute['behavior'] == '1')
                    presets.textActivated.connect(field.setPlainText)
                    wrapper = QWidget()
                    controls = QVBoxLayout(wrapper)
                    controls.setContentsMargins(0, 0, 0, 0)
                    grid.removeWidget(field)
                    controls.addWidget(field)
                    controls.addWidget(presets)
                    grid.addWidget(wrapper, row, column + 1, 1, 3)
        layout.addWidget(self.form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox()
        self.apply_button = self.buttons.addButton('Übernehmen', QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton))
        cancel_button = self.buttons.addButton('Abbrechen', QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self.buttons.accepted.connect(self.apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        if 'aufgabe' in self.inputs:
            self.inputs['aufgabe'].setFocus()

    def choose_recipient(self):
        dialog = UserSelectionDialog(self.api, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selection:
            identifier, name = dialog.selection
            field = self.inputs['erlassen_fuer_id']
            field.setText(name)
            field.setProperty('recipient_id', identifier)

    def apply(self):
        changes = {}
        for key, field in self.inputs.items():
            attr = self.attributes[key]
            if attr['behavior'] != '1':
                continue
            value = ('1' if field.isChecked() else '0') if isinstance(field, QCheckBox) else (
                field.toPlainText() if isinstance(field, QPlainTextEdit) else
                ('' if field.date() == field.minimumDate() else field.date().toString('dd.MM.yyyy')) if isinstance(field, QDateEdit) else
                field.currentText() if isinstance(field, QComboBox) else field.text())
            original = ('1' if attr['value'].lower() in ('1', 'true') else '0') if isinstance(field, QCheckBox) else attr['value']
            if value == original and not field.property('recipient_id'):
                continue
            idvalue = attr.get('idvalue', '0')
            if field.property('recipient_id'):
                idvalue = str(field.property('recipient_id'))
                value = f'--;{idvalue};{value};'
            elif isinstance(field, QComboBox):
                idvalue = attr.get('choice_ids', {}).get(value) or idvalue
            changes[key] = (value, idvalue)
        self.changes = changes
        self.run_operation('apply_workflow_task', (self.editor, changes), True)

    def run_operation(self, operation, args, accept):
        if self.worker is not None:
            return
        self.form.setEnabled(False)
        self.buttons.setEnabled(False)
        self.worker = gui.WorkflowWorker()
        self.worker.finished.connect(lambda result, error: self.finished_operation(accept, error))
        threading.Thread(target=self.worker.run, args=(self.api, operation, args), daemon=True).start()

    def finished_operation(self, accept, error):
        self.worker = None
        self.form.setEnabled(True)
        self.buttons.setEnabled(True)
        if error:
            self.error.setText(error)
            return
        if accept:
            super().accept()
        else:
            super().reject()

    def reject(self):
        if self.worker is None:
            self.run_operation('cancel_workflow_editor', (self.editor,), False)


class WorkflowTemplateDialog(QDialog):
    def __init__(self, api, editor, parent=None):
        super().__init__(parent)
        self.api, self.editor = api, editor
        self.worker = None
        self.result_state = None
        self.setWindowTitle('Geschäftsgangmusterauswahl')
        self.resize(460, 580)
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Suchworte eingeben')
        self.search.setClearButtonEnabled(True)
        heading.addWidget(self.search)
        layout.addLayout(heading)
        self.templates = QListWidget()
        self.templates.setProperty('framedList', True)
        collator = QCollator()
        collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        collator.setNumericMode(True)
        names = [(row.get('Name') or row.get('Description') or '', row) for row in editor['rows']]
        for name, row in sorted(names, key=lambda entry: collator.sortKey(entry[0])):
            item = QListWidgetItem(QIcon(str(gui.ICON_DIR / 'ribbon-workflow-template.svg')), name)
            item.setData(Qt.ItemDataRole.UserRole, row['_session_index'])
            item.setToolTip(row.get('Description', ''))
            self.templates.addItem(item)
        layout.addWidget(self.templates)
        self.error = QLabel('' if editor['rows'] else 'Keine Geschäftsgangmuster verfügbar.')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Auswählen')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.apply)
        self.buttons.rejected.connect(self.reject)
        self.templates.itemDoubleClicked.connect(lambda _item: self.apply())
        self.templates.currentItemChanged.connect(self.update_selection)
        self.search.textChanged.connect(self.filter_templates)
        if self.templates.count():
            self.templates.setCurrentRow(0)
        self.update_selection()

    def update_selection(self):
        item = self.templates.currentItem()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.worker is None and item is not None and not item.isHidden())

    def filter_templates(self, text):
        words = text.casefold().split()
        for index in range(self.templates.count()):
            item = self.templates.item(index)
            item.setHidden(not all(word in item.text().casefold() for word in words))
        self.update_selection()

    def apply(self):
        item = self.templates.currentItem()
        if item is not None and not item.isHidden():
            self.run_operation('apply_workflow_template', (self.editor, item.data(Qt.ItemDataRole.UserRole)), True)

    def run_operation(self, operation, args, accept):
        if self.worker is not None:
            return
        self.buttons.setEnabled(False)
        self.templates.setEnabled(False)
        self.search.setEnabled(False)
        self.worker = gui.WorkflowWorker()
        self.worker.finished.connect(lambda result, error: self.finished_operation(result, error, accept))
        threading.Thread(target=self.worker.run, args=(self.api, operation, args), daemon=True).start()

    def finished_operation(self, result, error, accept):
        self.worker = None
        self.buttons.setEnabled(True)
        self.templates.setEnabled(True)
        self.search.setEnabled(True)
        self.update_selection()
        if error:
            self.error.setText(error)
        elif accept:
            self.result_state = result
            super().accept()
        else:
            super().reject()

    def reject(self):
        self.run_operation('cancel_workflow_template', (self.editor,), False)

    def closeEvent(self, event):
        event.ignore()
        self.reject()
