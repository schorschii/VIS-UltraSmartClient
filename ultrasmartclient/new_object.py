"""Objekt anlegen: wizard for creating a new object below the selected location."""
import threading

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from . import gui
from .richclient_config import custom_wizard_fields


class NewObjectDialog(QDialog):
    def __init__(self, api, parent_entry, parent=None):
        super().__init__(parent)
        self.api, self.parent_entry = api, dict(parent_entry)
        self.worker = None
        self.editor = None
        self.pool_id = None
        self.created_entry = None
        self.selected_type = None
        self.setWindowTitle('Objekt anlegen')
        self.resize(700, 600)
        layout = QHBoxLayout(self)
        # Wizard steps: a bold heading label and a plain label per step.
        sidebar = QFrame()
        sidebar.setObjectName('newObjectSidebar')
        sidebar.setFixedWidth(170)
        sidebar.setStyleSheet('#newObjectSidebar { background: #243e60; } QLabel { color: white; }')
        steps = QVBoxLayout(sidebar)
        steps.setContentsMargins(14, 14, 14, 14)
        steps.setSpacing(2)

        def step_label(bold=False):
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            if bold:
                font = label.font()
                font.setBold(True)
                label.setFont(font)
            steps.addWidget(label)
            return label
        self.location_title = step_label(True)
        self.location_text = step_label()
        steps.addSpacing(14)
        self.kind_title = step_label(True)
        self.kind_text = step_label()
        steps.addSpacing(14)
        self.capture_title = step_label(True)
        self.capture_title.setText('Erfassen')
        steps.addStretch()
        self.sidebar = sidebar
        self.show_sidebar_steps()
        layout.addWidget(sidebar)
        content = QVBoxLayout()
        layout.addLayout(content, 1)
        title = QLabel('Objektart und Typ')
        self.page_title = title
        font = title.font()
        font.setPointSize(18)
        title.setFont(font)
        content.addWidget(title)
        self.kinds_widget = QWidget()
        self.kinds_layout = QHBoxLayout(self.kinds_widget)
        self.kinds_layout.setContentsMargins(0, 0, 0, 0)
        content.addWidget(self.kinds_widget)
        self.types = QListWidget()
        self.types.itemClicked.connect(self.select_type)
        content.addWidget(self.types, 1)
        self.custom_fields = custom_wizard_fields()
        self.field_widgets = {}
        self.metadata_page = gui.vertical_scroll_only(QScrollArea())
        self.metadata_page.setFrameShape(QFrame.Shape.NoFrame)
        metadata = QWidget()
        self.metadata_layout = QFormLayout(metadata)
        self.metadata_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.subject = QLineEdit()
        self.metadata_layout.addRow('Betreff *', self.subject)
        self.metadata_page.setWidget(metadata)
        self.metadata_page.hide()
        content.addWidget(self.metadata_page, 1)
        self.status = QLabel('Objektarten werden geladen …')
        self.status.setWordWrap(True)
        content.addWidget(self.status)
        self.buttons = QWidget()
        button_layout = QHBoxLayout(self.buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.cancel_button = QPushButton('Abbrechen')
        self.cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        self.back_button = QPushButton('Zurück')
        self.back_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.back_button.clicked.connect(self.back)
        self.back_button.hide()
        button_layout.addWidget(self.back_button)
        button_layout.addStretch()
        self.create_button = QPushButton('Anlegen')
        self.create_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.create_button.clicked.connect(self.create)
        self.create_button.hide()
        button_layout.addWidget(self.create_button)
        content.addWidget(self.buttons)
        self.run('fetch_new_object_kinds', (self.parent_entry,), 'kinds')

    def run(self, operation, args, phase):
        if self.worker is not None:
            return
        self.kinds_widget.setEnabled(False)
        self.types.setEnabled(False)
        self.metadata_page.setEnabled(False)
        self.buttons.setEnabled(False)
        self.worker = gui.WorkflowWorker()
        self.worker.finished.connect(lambda result, error: self.finished_operation(phase, result, error))
        threading.Thread(target=self.worker.run, args=(self.api, operation, args), daemon=True).start()

    def select_kind(self, kind, button):
        if self.worker is not None:
            return
        for other in self.kinds_widget.findChildren(QToolButton):
            other.setChecked(other is button)
        self.types.clear()
        self.status.setText('Objekttypen werden geladen …')
        self.run('load_new_object_types', (kind, self.parent_entry['id'], self.pool_id, self.editor), 'types')

    def finished_operation(self, phase, result, error):
        self.worker = None
        self.kinds_widget.setEnabled(True)
        self.types.setEnabled(True)
        self.metadata_page.setEnabled(True)
        self.buttons.setEnabled(True)
        if error:
            self.status.setText(error)
            return
        if phase == 'created':
            self.created_entry = result
            self.editor = None
            super().accept()
        elif phase == 'close':
            self.editor = None
            super().reject()
        elif phase == 'fields':
            self.show_metadata(result)
        elif phase == 'kinds':
            self.pool_id = result['pool_id']
            for name, kind in result['kinds']:
                button = QToolButton()
                button.setText(name)
                button.setIcon(gui.object_icon(kind))
                button.setIconSize(QSize(32, 32))
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                button.setCheckable(True)
                button.setStyleSheet('QToolButton:checked { background: palette(highlight); color: palette(highlighted-text); border: 1px solid palette(link); }')
                button.clicked.connect(lambda checked, kind=kind, button=button: self.select_kind(kind, button))
                self.kinds_layout.addWidget(button)
            self.kinds_layout.addStretch()
            self.status.setText('Bitte eine Objektart auswählen.' if result['kinds'] else 'Keine Objektarten verfügbar.')
        else:
            self.editor = result
            for name, identifier in result['types']:
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, identifier)
                self.types.addItem(item)
            self.status.setText('Bitte einen Objekttyp auswählen.' if result['types'] else 'Keine Objekttypen verfügbar.')

    def select_type(self, item):
        if self.worker is not None or self.editor is None:
            return
        self.selected_type = item.data(Qt.ItemDataRole.UserRole)
        self.selected_type_name = item.text()
        if self.custom_fields:
            self.status.setText('Felder werden geladen …')
            self.run('select_new_object_type', (self.editor, self.selected_type), 'fields')
        else:
            self.show_metadata([])

    def wizard_attributes(self, attributes):
        """Attributes listed in CustomWizardFields, matched by identifier or label, in configured order."""
        skip = {'betreff', self.editor.get('type_key')}
        result = []
        for entry in self.custom_fields:
            key = entry.casefold()
            for attribute in attributes:
                if (attribute['identifier'] not in skip and attribute['behavior'] != '4' and attribute not in result
                        and key in (attribute['identifier'].casefold(), attribute['name'].casefold())):
                    result.append(attribute)
        return result

    def show_metadata(self, attributes):
        while self.metadata_layout.rowCount() > 1:
            self.metadata_layout.removeRow(1)
        self.field_widgets = {}
        for attribute in self.wizard_attributes(attributes):
            field = gui.property_field(attribute)
            if attribute['behavior'] != '1':
                field.setEnabled(False)
            label = QLabel(attribute['name'])
            label.setWordWrap(True)
            self.metadata_layout.addRow(label, field)
            self.field_widgets[attribute['identifier']] = (field, attribute)
        self.subject.setText(self.editor.get('subject', ''))
        self.page_title.setText('Metadaten und Inhalt')
        self.kinds_widget.hide()
        self.types.hide()
        self.metadata_page.show()
        self.create_button.show()
        self.back_button.show()
        kind = next((b.text() for b in self.kinds_widget.findChildren(QToolButton) if b.isChecked()), '')
        self.show_sidebar_steps(kind)
        self.status.clear()
        self.subject.setFocus()

    def show_sidebar_steps(self, kind=None):
        """Update the wizard steps; kind is set once Objektart and Typ are chosen."""
        self.location_title.setText('Speicherort ✓')
        self.location_text.setText(self.parent_entry.get('name', ''))
        chosen = kind is not None
        self.kind_title.setText('Objektart ✓' if chosen else 'Objektart')
        self.kind_text.setText(kind + '\n' + self.selected_type_name if chosen else 'Wählen Sie Objektart\nund Typ aus')
        self.capture_title.setVisible(chosen)

    def back(self):
        self.show_sidebar_steps()
        self.metadata_page.hide()
        self.kinds_widget.show()
        self.types.show()
        self.create_button.hide()
        self.back_button.hide()
        self.page_title.setText('Objektart und Typ')

    def create(self):
        if self.worker is not None or self.editor is None:
            return
        if not self.subject.text().strip():
            self.status.setText('Bitte einen Betreff eingeben.')
            return
        self.status.setText('Objekt wird angelegt …')
        fields = {}
        for identifier, (field, attribute) in self.field_widgets.items():
            value = gui.property_field_change(field, attribute) if attribute['behavior'] == '1' else None
            if value is not None:
                fields[identifier] = value
        self.run('create_object', (self.editor, self.selected_type, self.subject.text(), fields), 'created')

    def reject(self):
        if self.worker is not None:
            return
        if self.editor:
            self.run('cancel_workflow_editor', (self.editor,), 'close')
        else:
            super().reject()

    def closeEvent(self, event):
        event.ignore()
        self.reject()
