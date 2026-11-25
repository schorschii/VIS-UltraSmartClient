"""Server-backed Stellvertreter administration."""
import threading
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QMenu
from .user_selection import TreeRequest, UserSelectionDialog


class StellvertreterManagementDialog(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.state = None
        self.worker = None
        self.setWindowTitle('Stellvertreterverwaltung')
        self.resize(680, 500)
        layout = QVBoxLayout(self)
        self.entries = QTableWidget(0, 5)
        self.entries.setHorizontalHeaderLabels(['Name', 'Vorname', 'Aktiv', 'Stelle', 'E-Mail'])
        self.entries.verticalHeader().hide()
        self.entries.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.entries.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.entries.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.entries.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.entries.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.entries.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.entries.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.entries)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        self.add_button = QPushButton('Hinzufügen')
        self.add_button.clicked.connect(self.add)
        layout.addWidget(self.add_button)
        self.reload()

    def request(self, callback, args, completed):
        if self.worker is not None:
            return
        self.entries.setEnabled(False)
        self.add_button.setEnabled(False)
        self.error.setText('Bitte warten …')
        self.worker = TreeRequest(self)
        def finish(result, error):
            worker, self.worker = self.worker, None
            self.error.setText(error)
            self.entries.setEnabled(True)
            self.add_button.setEnabled(self.state is not None)
            if not error:
                completed(result)
            worker.deleteLater()
        self.worker.finished.connect(finish)
        threading.Thread(target=self.worker.run, args=(callback, args), daemon=True).start()

    def reload(self):
        self.request(self.api.reload_stellvertreter_management if self.state else self.api.open_stellvertreter_management,
                     (self.state,) if self.state else (), self.loaded)

    def loaded(self, state):
        self.state = state
        self.entries.setRowCount(len(state['rows']))
        for row_index, row in enumerate(state['rows']):
            values = (row.get('stellvertreterName', ''), row.get('stellvertreterVorname', ''),
                      'Ja' if str(row.get('aktiv', '')).lower() in ('1', 'true') else 'Nein',
                      row.get('stellvertreterStelle', ''),
                      'Ja' if str(row.get('mail', '')).lower() in ('1', 'true') else 'Nein')
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row['_session_index'])
                self.entries.setItem(row_index, column, item)
        self.add_button.setEnabled(True)
        if not state['rows']:
            self.error.setText('Keine Stellvertreter vorhanden.')

    def add(self):
        if self.state is None or self.worker is not None:
            return
        picker = UserSelectionDialog(self.api, parent=self,
            root_callback=self.api.open_stellvertreter_selection,
            root_args=(self.state['session_id'],),
            confirm_callback=self.api.confirm_stellvertreter_selection)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def context_menu(self, position):
        item = self.entries.itemAt(position)
        if item is None or self.state is None or self.worker is not None:
            return
        self.entries.selectRow(item.row())
        menu = QMenu(self)
        delete = menu.addAction('Entfernen')
        delete.setEnabled(item.data(Qt.ItemDataRole.UserRole) is not None)
        if menu.exec(self.entries.viewport().mapToGlobal(position)) == delete and delete.isEnabled():
            self.request(self.api.delete_stellvertreter,
                         (self.state, item.data(Qt.ItemDataRole.UserRole)), self.loaded)

    def reject(self):
        if self.worker is not None:
            return
        if self.state is None:
            super().reject()
        else:
            self.request(self.api.close_user_selection, (self.state['session_id'],), self.closed)

    def closed(self, _result):
        self.state = None
        super().reject()
