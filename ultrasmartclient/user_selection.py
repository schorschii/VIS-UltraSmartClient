"""Hierarchical recipient picker backed by VIS tree sessions."""
import threading
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QStyle, QPushButton,
)


class TreeRequest(QObject):
    finished = pyqtSignal(object, str)

    def run(self, callback, args):
        try:
            result = callback(*args)
        except Exception as error:
            self.finished.emit(None, str(error))
        else:
            self.finished.emit(result, '')


class UserSelectionDialog(QDialog):
    def __init__(self, api, parent=None, root_callback=None, root_args=(), confirm_callback=None,
                 cleanup_callback=None):
        super().__init__(parent)
        self.api = api
        self.selection = None
        self.selection_path = None
        self.selection_root = None
        self.confirm_callback = confirm_callback
        # Called with the root instead of closing the selection session when the dialog is cancelled.
        self.cleanup_callback = cleanup_callback
        self.confirm_result = None
        self.tree_session = None
        self.selection_session = None
        self.closed = False
        self.nodes = {}
        self.loaded = set()
        self.pending = {}
        # Items expanded by the search filter, collapsed again when they no longer match.
        self.search_expanded = set()
        self.setWindowTitle('Nutzerauswahl')
        self.resize(430, 610)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Nutzer suchen …')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_tree)
        header.addWidget(self.search)
        layout.addLayout(header)
        self.tree = QTreeWidget()
        self.tree.setObjectName('userSelectionTree')
        self.tree.setProperty('framedList', True)
        self.tree.setStyleSheet('QTreeWidget::item { min-height: 24px; }')
        self.tree.setHeaderHidden(True)
        self.tree.itemExpanded.connect(self.load_children)
        self.tree.itemClicked.connect(self.select_user)
        self.tree.itemDoubleClicked.connect(self.accept_user)
        layout.addWidget(self.tree, 3)
        layout.addWidget(QLabel('Ausgewählte'))
        self.selected = QListWidget()
        self.selected.setProperty('framedList', True)
        layout.addWidget(self.selected, 1)
        self.error = QLabel()
        self.search.setEnabled(False)
        self.retry = QPushButton('Erneut laden')
        self.retry.hide()
        self.retry.clicked.connect(self.retry_load)
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        layout.addWidget(self.retry)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Übernehmen')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.finished.connect(self.close_session)
        self.root_callback = root_callback or api.open_user_selection
        self.root_args = root_args
        self.retry_load()

    def retry_load(self):
        self.retry.hide()
        self.error.setText('Nutzer werden geladen …')
        self.request('root', self.root_callback, self.root_args, self.root_loaded)

    def close_session(self, *_args):
        self.closed = True
        if self.selection_session is not None:
            session, self.selection_session = self.selection_session, None
            if self.cleanup_callback is not None:
                self.request('cleanup', self.cleanup_callback, (self.selection_root,), lambda result: None)
            else:
                self.request('cleanup', self.api.close_user_selection, (session,), lambda result: None)

    def request(self, key, callback, args, completed):
        if key in self.pending:
            return
        worker = TreeRequest(self)
        self.pending[key] = worker
        def finish(result, error):
            self.pending.pop(key, None)
            self.error.setText(error)
            if key == 'confirm':
                self.buttons.setEnabled(True)
                self.tree.setEnabled(True)
            if key == 'root':
                self.retry.setVisible(bool(error) and not self.closed)
            if not error:
                completed(result)
            worker.deleteLater()
        worker.finished.connect(finish)
        threading.Thread(target=worker.run, args=(callback, args), daemon=True).start()

    def root_loaded(self, root):
        self.selection_root = root
        self.selection_session = root.get('selection_session')
        if self.closed:
            self.close_session()
            return
        self.search.setEnabled(True)
        self.search.setFocus()
        self.tree_session = root['session_id']
        item = QTreeWidgetItem([root['name']])
        item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        item.setData(0, Qt.ItemDataRole.UserRole, root)
        self.nodes[root['id']] = item
        self.tree.addTopLevelItem(item)
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        item.setExpanded(True)

    def load_children(self, item):
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if not node or node['id'] in self.loaded:
            return
        self.request(node['id'], self.api.fetch_user_tree_children,
                     (self.tree_session, node['id']), lambda rows: self.children_loaded(item, rows))

    def children_loaded(self, parent, rows):
        parent_id = parent.data(0, Qt.ItemDataRole.UserRole)['id']
        for node in sorted(rows, key=lambda row: (row['id'] or '').count('/')):
            if not node['id'] or node['id'] in self.nodes:
                continue
            ancestor = self.nodes.get(node['id'].rsplit('/', 1)[0], parent)
            item = QTreeWidgetItem(ancestor, [node['name']])
            item.setData(0, Qt.ItemDataRole.UserRole, node)
            self.nodes[node['id']] = item
            item.setIcon(0, QIcon(str(Path(__file__).parent / 'assets/icons/user-placeholder.svg'))
                         if node['user_id'] else self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
            if node['has_children']:
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            if node['user_id']:
                item.setToolTip(0, f'Benutzer-ID: {node["user_id"]}')
        self.loaded.add(parent_id)
        self.filter_tree()

    def select_user(self, item, _column=0):
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if not node or not node.get('user_id'):
            return
        self.selection = (node['user_id'], node['name'])
        self.selection_path = node.get('selected_value') or node['id']
        self.selected.clear()
        self.selected.addItem(node['name'])
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def accept(self):
        if self.confirm_callback is None:
            super().accept()
            return
        if self.selection is None or self.selection_root is None or 'confirm' in self.pending:
            return
        self.buttons.setEnabled(False)
        self.tree.setEnabled(False)
        self.request('confirm', self.confirm_callback, (self.selection_root, self.selection_path), self.confirmed)

    def confirmed(self, result):
        self.confirm_result = result
        self.selection_session = None
        super().accept()

    def reject(self):
        if 'confirm' not in self.pending:
            super().reject()

    def accept_user(self, item, column=0):
        self.select_user(item, column)
        if (item.data(0, Qt.ItemDataRole.UserRole) or {}).get('user_id'):
            self.accept()

    def filter_tree(self, *_args):
        query = self.search.text().casefold().strip()
        def visit(item):
            children = [visit(item.child(i)) for i in range(item.childCount())]
            visible = not query or query in item.text(0).casefold() or any(children)
            item.setHidden(not visible)
            # Open branches containing a match so the result is visible.
            node_id = (item.data(0, Qt.ItemDataRole.UserRole) or {}).get('id')
            if query and any(children):
                if not item.isExpanded():
                    self.search_expanded.add(node_id)
                    item.setExpanded(True)
            elif node_id in self.search_expanded:
                self.search_expanded.discard(node_id)
                item.setExpanded(False)
            return visible
        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
