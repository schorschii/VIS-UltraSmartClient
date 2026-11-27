"""Workflow template (Geschäftsgangmuster) administration: overview and editor for new templates."""
import threading

from PyQt6.QtCore import QCollator, QDate, QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QPlainTextEdit,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QStyle, QTableWidget, QTableWidgetItem, QToolButton,
    QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from . import gui
from .user_selection import TreeRequest, UserSelectionDialog

# ID of the selected Kategorie on the task table's Kategorie cells.
CATEGORY_ID_ROLE = Qt.ItemDataRole.UserRole + 1

# Visible columns of the template's task table (ggvermerke).
TASK_COLUMNS = [
    ('Stufe', 'stufe'), ('Kategorie', 'kategorie'), ('Erlassen für', 'erlassen_fuer_id'),
    ('Fällig am', 'termin'), ('Aufgabe', 'aufgabe'), ('Freigabe', 'freigabe'),
]


def template_kind(row):
    try:
        return int(row.get('objektart_id') or 0)
    except ValueError:
        return 0


def run_request(parent, callback, args, finished):
    """Run an API call in a thread; finished(result, error) runs in the GUI thread."""
    worker = TreeRequest(parent)
    def done(result, error):
        worker.deleteLater()
        finished(result, error)
    worker.finished.connect(done)
    threading.Thread(target=worker.run, args=(callback, args), daemon=True).start()


class WorkflowTemplateManagementDialog(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.state = None
        self.closed = False
        self.busy = False
        self.add_buttons = []
        self.last_kind = None
        self.setWindowTitle('Geschäftsgangmuster-Verwaltung')
        self.resize(560, 720)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Suchworte eingeben')
        self.search.setClearButtonEnabled(True)
        self.search.setEnabled(False)
        self.search.textChanged.connect(self.filter_templates)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setObjectName('workflowTemplateTree')
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 36)
        self.tree.setStyleSheet('QTreeWidget { border: 1px solid palette(midlight); background: palette(base); }')
        self.tree.itemDoubleClicked.connect(self.edit_template)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.template_context_menu)
        layout.addWidget(self.tree, 1)
        self.status = QLabel('Geschäftsgangmuster werden geladen …')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Schließen')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.finished.connect(self.dialog_closed)
        run_request(self, self.api.open_workflow_template_management, (), self.loaded)

    def dialog_closed(self, *_args):
        self.closed = True
        if self.state is not None:
            state, self.state = self.state, None
            threading.Thread(target=self._close_session, args=(state,), daemon=True).start()

    def _close_session(self, state):
        try:
            self.api.close_workflow_template_management(state)
        except Exception:
            pass

    def loaded(self, state, error):
        if self.closed:
            if state is not None:
                threading.Thread(target=self._close_session, args=(state,), daemon=True).start()
            return
        if error:
            self.status.setText('Geschäftsgangmuster konnten nicht geladen werden: ' + error)
            return
        self.state = state
        self.show_templates(state['rows'])
        self.search.setEnabled(True)
        self.search.setFocus()

    def show_templates(self, rows):
        expanded = {self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                    for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).isExpanded()}
        first_load = not self.tree.topLevelItemCount()
        self.tree.clear()
        self.add_buttons = []
        collator = QCollator()
        collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        collator.setNumericMode(True)
        by_kind = {}
        for row in rows:
            by_kind.setdefault(template_kind(row), []).append(row)
        # Object kinds come from the server, ordered by ID like the VIS client;
        # templates of a kind missing there still get their own category.
        known = dict(self.state['kinds']) if self.state else {}
        known.update({kind: f'Objektart {kind}' for kind in by_kind if kind not in known})
        categories = sorted(known.items())
        template_icon = QIcon(str(gui.ICON_DIR / 'ribbon-workflow-template.svg'))
        for kind, title in categories:
            category = QTreeWidgetItem(self.tree, [title])
            category.setIcon(0, gui.object_icon(kind))
            category.setData(0, Qt.ItemDataRole.UserRole, kind)
            category.setFlags(Qt.ItemFlag.ItemIsEnabled)
            add = QToolButton()
            add.setText('+')
            add.setAutoRaise(True)
            add.setAccessibleName(f'Neues Geschäftsgangmuster für {title}')
            add.setToolTip(f'Neues Geschäftsgangmuster für {title}')
            add.setStyleSheet('QToolButton { font-size: 18px; padding: 0 6px; } QToolButton:!hover { background: transparent; }')
            add.setEnabled(not self.busy)
            add.clicked.connect(lambda _checked=False, kind=kind: self.new_template(kind))
            self.tree.setItemWidget(category, 1, add)
            self.add_buttons.append(add)
            templates = sorted(by_kind.get(kind, []), key=lambda row: collator.sortKey(row.get('Name', '')))
            for row in templates:
                item = QTreeWidgetItem(category, [row.get('Name') or row.get('Description') or ''])
                item.setIcon(0, template_icon)
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                tooltip = [line for line in (row.get('Description', ''),
                                             'Eigentümer: ' + row['Owner'] if row.get('Owner') else '',
                                             'Muster-ID: ' + row['MusterId'] if row.get('MusterId') else '') if line]
                item.setToolTip(0, '\n'.join(tooltip))
            # Keep the user's expanded categories on reload; open the one a template was just added to.
            category.setExpanded(bool(templates) and (first_load or kind in expanded or kind == self.last_kind))
        count = len(rows)
        self.status.setText('1 Geschäftsgangmuster' if count == 1 else f'{count} Geschäftsgangmuster')
        self.filter_templates(self.search.text())

    def filter_templates(self, text):
        words = text.casefold().split()
        for index in range(self.tree.topLevelItemCount()):
            category = self.tree.topLevelItem(index)
            matches = 0
            for child_index in range(category.childCount()):
                item = category.child(child_index)
                row = item.data(0, Qt.ItemDataRole.UserRole) or {}
                haystack = ' '.join((item.text(0), row.get('Description', ''))).casefold()
                hidden = not all(word in haystack for word in words)
                item.setHidden(hidden)
                matches += not hidden
            # While searching, show only categories with hits and open them.
            category.setHidden(bool(words) and not matches)
            if words and matches:
                category.setExpanded(True)

    def set_busy(self, busy, message=''):
        self.busy = busy
        for button in self.add_buttons:
            button.setEnabled(not busy)
        if message:
            self.status.setText(message)

    def new_template(self, kind):
        if self.state is None or self.busy:
            return
        self.last_kind = kind
        self.set_busy(True, 'Geschäftsgangmuster-Editor wird geöffnet …')
        run_request(self, self.api.new_workflow_template, (self.state, kind), self.editor_opened)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and self.tree.hasFocus() and self.tree.currentItem() is not None:
            self.delete_template(self.tree.currentItem())
            return
        super().keyPressEvent(event)

    def template_context_menu(self, position):
        item = self.tree.itemAt(position)
        template = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(template, dict):
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        edit = menu.addAction('Bearbeiten')
        delete = menu.addAction('Löschen')
        for action in (edit, delete):
            action.setEnabled(self.state is not None and not self.busy)
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen == edit:
            self.edit_template(item)
        elif chosen == delete:
            self.delete_template(item)

    def delete_template(self, item):
        template = item.data(0, Qt.ItemDataRole.UserRole)
        if self.state is None or self.busy or not isinstance(template, dict):
            return
        name = template.get('Name') or template.get('Description') or ''
        answer = QMessageBox.question(
            self, 'Geschäftsgangmuster löschen',
            f'Soll das Geschäftsgangmuster „{name}“ wirklich gelöscht werden?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.last_kind = template_kind(template)
        self.set_busy(True, 'Geschäftsgangmuster wird gelöscht …')
        def deleted(rows, error):
            if self.closed:
                return
            self.set_busy(False)
            if error:
                self.status.setText('Geschäftsgangmuster konnte nicht gelöscht werden: ' + error)
                return
            self.state['rows'] = rows
            self.show_templates(rows)
            self.status.setText(f'Geschäftsgangmuster „{name}“ gelöscht.')
        run_request(self, self.api.delete_workflow_template, (self.state, template['_session_index']), deleted)

    def edit_template(self, item, _column=0):
        template = item.data(0, Qt.ItemDataRole.UserRole)
        if self.state is None or self.busy or not isinstance(template, dict) or not template.get('MusterId'):
            return  # category rows carry their object kind, not a template
        self.last_kind = template_kind(template)
        self.set_busy(True, 'Geschäftsgangmuster wird geöffnet …')
        run_request(self, self.api.open_workflow_template, (self.state, template), self.editor_opened)

    def editor_opened(self, editor, error):
        if self.closed:
            if editor is not None:
                threading.Thread(target=self.api.cancel_workflow_template_editor, args=(editor,), daemon=True).start()
            return
        self.set_busy(False)
        if error:
            self.status.setText('Geschäftsgangmuster-Editor konnte nicht geöffnet werden: ' + error)
            return
        dialog = WorkflowTemplateEditorDialog(self.api, editor, self)
        dialog.exec()
        if self.state is None:
            return
        if dialog.list_state is not None:
            # Creating a template continues the list in a new, unfiltered session.
            self.state.update(dialog.list_state)
            self.show_templates(self.state['rows'])
            if dialog.saved:
                self.status.setText('Geschäftsgangmuster gespeichert.')
        elif editor.get('list_command', True):
            # The editor could not hand back a list; reload it so it is not left filtered.
            self.reload_all()
        else:
            count = len(self.state['rows'])
            self.status.setText('1 Geschäftsgangmuster' if count == 1 else f'{count} Geschäftsgangmuster')

    def reload_all(self):
        old_state, self.state = self.state, None
        self.set_busy(True, 'Geschäftsgangmuster werden geladen …')
        threading.Thread(target=self._close_session, args=(old_state,), daemon=True).start()
        def reloaded(state, error):
            self.set_busy(False)
            self.loaded(state, error)
        run_request(self, self.api.open_workflow_template_management, (), reloaded)


class WorkflowTemplateEditorDialog(QDialog):
    """Edit a template in its GGVMUSTERVERWALTUNG_DETAILS session; changes are sent with each command."""

    def __init__(self, api, editor, parent=None):
        super().__init__(parent)
        self.api = api
        self.editor = editor
        self.busy = False
        self.saved = False
        self.list_state = None  # list session and rows to show after closing
        self.setWindowTitle('Geschäftsgangmuster')
        self.resize(740, 600)
        attributes = {attribute['identifier']: attribute for attribute in editor['attributes']}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(60)
        objektart = attributes.get('objektartId', {})
        self.kind = QComboBox()
        self.kind.addItem(objektart.get('value', ''))
        self.kind.setEnabled(False)
        form.addRow('Objektart', self.kind)
        owner = attributes.get('Owner', {})
        self.owner_ids = owner.get('choice_ids', {})
        self.owner = QComboBox()
        self.owner.addItems(list(dict.fromkeys(owner.get('choices') or [owner.get('value', '')])))
        self.owner.setCurrentText(owner.get('value', ''))
        form.addRow('Eigentümer', self.owner)
        self.name = QLineEdit(attributes.get('Name', {}).get('value', ''))
        self.name.setMaxLength(50)
        self.name.textChanged.connect(self.update_buttons)
        form.addRow('Mustername *', self.name)
        self.description = QLineEdit(attributes.get('Description', {}).get('value', ''))
        self.description.setMaxLength(500)
        form.addRow('Beschreibung', self.description)
        layout.addLayout(form)
        self.tasks = QTableWidget(0, len(TASK_COLUMNS))
        self.tasks.setHorizontalHeaderLabels([label for label, _ in TASK_COLUMNS])
        self.tasks.verticalHeader().hide()
        self.tasks.setShowGrid(False)
        self.tasks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Rows are edited in a dialog (double-click); changes are sent in bulk when saving.
        self.tasks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tasks.itemDoubleClicked.connect(lambda item: self.edit_task(item.row()))
        header = self.tasks.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column, width in enumerate((50, 135, 135, 135, 135, 80)):
            self.tasks.setColumnWidth(column, width)
        header.setStretchLastSection(True)
        self.tasks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tasks.customContextMenuRequested.connect(self.task_context_menu)
        layout.addWidget(self.tasks, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.add_task = QPushButton('Neue Geschäftsgangverfügung')
        self.add_task.clicked.connect(self.new_task)
        buttons.addWidget(self.add_task)
        buttons.addStretch()
        # A button box orders Speichern/Abbrechen like every other dialog on this desktop.
        dialog_buttons = QDialogButtonBox()
        self.save_button = dialog_buttons.addButton('Speichern', QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setDefault(True)
        self.cancel_button = dialog_buttons.addButton('Abbrechen', QDialogButtonBox.ButtonRole.RejectRole)
        dialog_buttons.accepted.connect(self.save)
        dialog_buttons.rejected.connect(self.reject)
        buttons.addWidget(dialog_buttons)
        app = QApplication.instance()
        icons = gui.ICON_DIR / 'dark' if getattr(getattr(app, 'theme_manager', None), 'dark', False) else gui.ICON_DIR
        self.add_task.setIcon(QIcon(str(icons / 'ribbon-new-task.svg')))
        # Same standard icons as the OK/Cancel buttons of the user selection dialog.
        self.save_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton))
        self.cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        for button in (self.save_button, self.add_task, self.cancel_button):
            button.setIconSize(QSize(16, 16))
            button.setStyleSheet('text-align: center; padding: 5px 10px;')
        layout.addLayout(buttons)
        self.mark_sent()
        self.show_tasks(editor['tasks'])
        self.update_buttons()
        self.name.setFocus()
        self.name.selectAll()

    def field_values(self):
        return {'Owner': self.owner.currentText(), 'Name': self.name.text(), 'Description': self.description.text()}

    def mark_sent(self):
        """Remember the field values the server session already has."""
        self.sent = self.field_values()

    def changes(self):
        changes = {}
        for identifier, value in self.field_values().items():
            if value == self.sent.get(identifier):
                continue
            if identifier == 'Owner':
                if self.owner_ids.get(value) is not None:
                    changes[identifier] = (value, self.owner_ids[value])
            else:
                changes[identifier] = (value, None)
        return changes

    def show_tasks(self, tasks):
        self.task_rows = {task.get('_session_index'): task for task in tasks}
        self.tasks.setRowCount(len(tasks))
        self.task_baseline = {}
        for row, task in enumerate(tasks):
            index = task.get('_session_index')
            for column, (_label, key) in enumerate(TASK_COLUMNS):
                value = task.get(key, '')
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, index)
                if key == 'kategorie':
                    item.setData(CATEGORY_ID_ROLE, (task.get('_category_ids') or {}).get('kategorie'))
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                if key == 'freigabe':
                    item.setText('')
                    item.setCheckState(Qt.CheckState.Checked if value.lower() in ('1', 'true') else Qt.CheckState.Unchecked)
                    flags |= Qt.ItemFlag.ItemIsUserCheckable
                item.setFlags(flags)
                item.setToolTip(value if key != 'freigabe' else '')
                self.tasks.setItem(row, column, item)
            self.task_baseline[index] = self.task_values(row)

    def task_cell(self, row, key):
        return self.tasks.item(row, [column for _, column in TASK_COLUMNS].index(key))

    def task_values(self, row):
        """Editable values of a task row, as sent to the server (dates as dd.MM.yyyy)."""
        return {'kategorie': self.task_cell(row, 'kategorie').data(CATEGORY_ID_ROLE),
                'aufgabe': self.task_cell(row, 'aufgabe').text(),
                'termin': self.task_cell(row, 'termin').text(),
                'freigabe': '1' if self.task_cell(row, 'freigabe').checkState() == Qt.CheckState.Checked else '0'}

    def edit_task(self, row):
        if self.busy or row < 0:
            return
        values = {key: self.task_cell(row, key).text() for _, key in TASK_COLUMNS}
        values.update(self.task_values(row))
        values['category_id'] = values.pop('kategorie')
        values['kategorie'] = self.task_cell(row, 'kategorie').text()
        index = self.tasks.item(row, 0).data(Qt.ItemDataRole.UserRole)
        dialog = TemplateTaskDialog(values, self.category_choices(index), self)
        dialog.recipient.clicked.connect(lambda: self.choose_recipient(index, dialog))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        row = self.row_of(index)
        if row is None:
            return
        for key, value in dialog.values().items():
            cell = self.task_cell(row, key)
            if key == 'kategorie':
                text, category_id = value
                cell.setText(text)
                cell.setToolTip(text)
                cell.setData(CATEGORY_ID_ROLE, category_id)
            elif key == 'freigabe':
                cell.setCheckState(Qt.CheckState.Checked if value == '1' else Qt.CheckState.Unchecked)
            else:
                cell.setText(value)
                cell.setToolTip(value)

    def row_changes(self):
        changes = {}
        for row in range(self.tasks.rowCount()):
            index = self.tasks.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if index is None:
                continue
            baseline = self.task_baseline.get(index, {})
            changed = {key: value for key, value in self.task_values(row).items() if value != baseline.get(key)}
            if 'kategorie' in changed:
                changed['kategorie'] = (self.task_cell(row, 'kategorie').text(), changed['kategorie'])
            if changed:
                changes[index] = changed
        return changes

    def update_buttons(self):
        idle = not self.busy
        self.add_task.setEnabled(idle)
        self.save_button.setEnabled(idle and bool(self.name.text().strip()))
        self.cancel_button.setEnabled(idle)
        for widget in (self.owner, self.name, self.description, self.tasks):
            widget.setEnabled(idle)

    def run(self, message, callback, args, finished, always=False):
        self.tasks.setCurrentItem(None)  # commit an open cell editor
        self.busy = True
        self.error.setText(message)
        self.update_buttons()
        def done(result, error):
            self.busy = False
            self.update_buttons()
            self.error.setText(error or '')
            if always or not error:
                finished(result)
        run_request(self, callback, args, done)

    def task_context_menu(self, position):
        item = self.tasks.itemAt(position)
        if item is None or self.busy:
            return
        row = item.row()
        self.tasks.selectRow(row)
        index = self.tasks.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        first, last = row == 0, row == self.tasks.rowCount() - 1
        menu = QMenu(self)
        actions = {}
        for label, action, enabled in (
                ('Bearbeiten …', 'edit', True),
                (None, None, None),
                ('Löschen', 'delete', True),
                (None, None, None),
                ('Nach oben schieben', 'up', not first),
                ('Nach unten schieben', 'down', not last),
                (None, None, None),
                ('Wie vorherige Stufe', 'previous_stage', not first),
                ('Wie nachfolgende Stufe', 'next_stage', not last),
                ('Als eigene Stufe', 'own_stage', True)):
            if label is None:
                menu.addSeparator()
                continue
            entry = menu.addAction(label)
            entry.setEnabled(enabled)
            actions[entry] = action
        chosen = menu.exec(self.tasks.viewport().mapToGlobal(position))
        if actions.get(chosen) == 'edit':
            self.edit_task(row)
        elif chosen in actions:
            self.task_command(actions[chosen], index, row)

    def row_of(self, index):
        for row in range(self.tasks.rowCount()):
            if self.tasks.item(row, 0).data(Qt.ItemDataRole.UserRole) == index:
                return row
        return None

    def category_choices(self, index):
        """Kategorien ({text: id}) of the session, or those the task row itself offers."""
        choices = dict(self.editor.get('categories') or {})
        if not choices:
            task = self.task_rows.get(index) or {}
            choices = {text or '': category_id for text, category_id in task.get('_category_choices') or ()
                       if category_id is not None}
        return choices

    def choose_recipient(self, index, task_dialog=None):
        """Select "Erlassen für" of a task row in the server's user selection (command 200607).

        Edits made so far are sent along; the task list is then reloaded from the server."""
        if self.busy or self.editor is None:
            return
        picker = UserSelectionDialog(self.api, parent=task_dialog or self,
            root_callback=self.api.open_template_user_selection,
            root_args=(self.editor, index, self.changes(), self.row_changes()),
            confirm_callback=self.api.confirm_template_user_selection,
            cleanup_callback=self.api.cancel_template_user_selection)
        if picker.exec() != QDialog.DialogCode.Accepted or not picker.confirm_result:
            return
        self.editor = picker.confirm_result
        self.mark_sent()
        self.show_tasks(self.editor['tasks'])
        row = self.row_of(index)
        if row is not None:
            self.tasks.selectRow(row)
            if task_dialog is not None:
                task_dialog.set_recipient(self.task_cell(row, 'erlassen_fuer_id').text())

    def task_command(self, action, index, row):
        changes, row_changes = self.changes(), self.row_changes()
        target = {'up': row - 1, 'down': row + 1, 'delete': None}.get(action, row)
        def done(editor):
            self.editor = editor
            self.mark_sent()
            self.show_tasks(editor['tasks'])
            if target is not None and 0 <= target < self.tasks.rowCount():
                self.tasks.selectRow(target)
        self.run('Geschäftsgangverfügungen werden aktualisiert …', self.api.workflow_template_task_command,
                 (self.editor, action, index, changes, row_changes), done)

    def new_task(self):
        if self.busy:
            return
        changes, row_changes = self.changes(), self.row_changes()
        def added(editor):
            self.editor = editor
            self.mark_sent()
            self.show_tasks(editor['tasks'])
        self.run('Geschäftsgangverfügung wird hinzugefügt …', self.api.add_workflow_template_task,
                 (self.editor, changes, row_changes), added)

    def save(self):
        if self.busy or not self.name.text().strip():
            return
        def saved(list_state):
            self.saved = True
            self.list_state = list_state
            self.editor = None
            super(WorkflowTemplateEditorDialog, self).accept()
        self.run('Geschäftsgangmuster wird gespeichert …', self.api.save_workflow_template,
                 (self.editor, self.changes(), self.row_changes()), saved)

    def reject(self):
        if self.busy:
            return
        if self.editor is None:
            super().reject()
            return
        def cancelled(list_state):
            self.list_state = list_state
            self.editor = None
            super(WorkflowTemplateEditorDialog, self).reject()
        # Close even if the server rejects the cancel; the session then expires on its own.
        self.run('Wird abgebrochen …', self.api.cancel_workflow_template_editor, (self.editor,), cancelled, always=True)


class TemplateTaskDialog(QDialog):
    """Edit one task row of a template, laid out like the main window's Geschäftsgangbearbeitung.

    Changes only update the row; the template's Speichern sends them to the server in bulk.
    """

    def __init__(self, values, categories=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Geschäftsgangbearbeitung')
        self.resize(590, 330)
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        def read_only(value):
            field = QLineEdit(value)
            field.setEnabled(False)
            return field
        self.aufgabe = QPlainTextEdit(values.get('aufgabe', ''))
        self.aufgabe.setMinimumHeight(80)
        self.termin = gui.OptionalDateEdit()
        self.termin.setObjectName('workflowDue')
        self.termin.setDisplayFormat('dd.MM.yyyy')
        self.termin.setCalendarPopup(True)
        self.termin.setSpecialValueText(' ')
        due = QDate.fromString(values.get('termin', ''), 'dd.MM.yyyy')
        self.termin.setDate(due if due.isValid() else self.termin.minimumDate())
        if not due.isValid():
            today = QDate.currentDate()
            self.termin.calendarWidget().setCurrentPage(today.year(), today.month())
        self.freigabe = QCheckBox()
        self.freigabe.setChecked(values.get('freigabe', '') in ('1', 'true'))
        # Kategorien as in the main window's task editor; the current one stays selectable.
        self.category = QComboBox()
        current_text, current_id = values.get('kategorie', ''), values.get('category_id')
        choices = dict(categories or {})
        if current_text and current_text not in choices:
            choices = {current_text: current_id, **choices}
        for text, category_id in choices.items():
            self.category.addItem(text, category_id)
        self.category.setCurrentText(current_text)
        self.category.setEnabled(self.category.count() > 0)
        # The selection runs on the server (200607) and updates the row there right away.
        self.recipient = QPushButton()
        self.recipient.setObjectName('workflowRecipient')
        self.set_recipient(values.get('erlassen_fuer_id', ''))
        for row, (label, field, label2, field2) in enumerate((
                ('Stufe', read_only(values.get('stufe', '')), 'Kategorie', self.category),
                ('Erlassen für', self.recipient, None, None),
                ('Aufgabe', self.aufgabe, None, None),
                ('Fällig am', self.termin, 'Freigabe', self.freigabe))):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(field, row, 1, 1, 1 if label2 else 3)
            if label2:
                grid.addWidget(QLabel(label2), row, 2)
                grid.addWidget(field2, row, 3)
        layout.addLayout(grid)
        layout.addStretch()
        buttons = QDialogButtonBox()
        apply_button = buttons.addButton('Übernehmen', QDialogButtonBox.ButtonRole.AcceptRole)
        apply_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton))
        cancel_button = buttons.addButton('Abbrechen', QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.aufgabe.setFocus()

    def set_recipient(self, name):
        self.recipient.setText(name or 'Empfänger auswählen …')

    def values(self):
        due = self.termin.date()
        return {'kategorie': (self.category.currentText(), self.category.currentData()),
                'aufgabe': self.aufgabe.toPlainText(),
                'termin': '' if due == self.termin.minimumDate() else due.toString('dd.MM.yyyy'),
                'freigabe': '1' if self.freigabe.isChecked() else '0'}
