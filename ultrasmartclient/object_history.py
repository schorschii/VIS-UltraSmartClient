"""Historie: the change history of an object."""
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QVBoxLayout

from . import gui
from .table_sort import SortableItem, enable_sorting


class ObjectHistoryDialog(QDialog):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Historie')
        self.setWindowIcon(QIcon(str(gui.ICON_DIR / 'ribbon-history.svg')))
        self.resize(800, 540)
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel('Historie')
        font = title.font()
        font.setPointSize(18)
        title.setFont(font)
        heading.addWidget(title)
        heading.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Suchworte eingeben')
        self.search.setClearButtonEnabled(True)
        heading.addWidget(self.search)
        layout.addLayout(heading)
        columns = [('Datum', 'datum'), ('Feld', 'name'), ('Neuer Wert', 'neu'),
                   ('Alter Wert', 'alt'), ('Änderung durch', 'durch')]
        self.table = QTableWidget(len(rows), len(columns))
        self.table.setHorizontalHeaderLabels([label for label, key in columns])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((140, 160, 170, 170, 130)):
            self.table.setColumnWidth(column, width)
        for index, row in enumerate(rows):
            for column, (_label, key) in enumerate(columns):
                value = row.get(key, '')
                item = SortableItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
        enable_sorting(self.table)
        layout.addWidget(self.table)
        self.empty = QLabel('Keine Historieneinträge vorhanden.')
        self.empty.setVisible(not rows)
        layout.addWidget(self.empty)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Schließen')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter_rows)

    def filter_rows(self, text):
        words = text.casefold().split()
        for row in range(self.table.rowCount()):
            values = ' '.join(self.table.item(row, column).text()
                              for column in range(self.table.columnCount())).casefold()
            self.table.setRowHidden(row, not all(word in values for word in words))
