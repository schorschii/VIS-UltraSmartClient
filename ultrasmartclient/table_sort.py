"""Click-to-sort support for QTableWidget tables."""
import re
from contextlib import contextmanager

from PyQt6.QtCore import QCollator, QLocale, Qt
from PyQt6.QtWidgets import QTableWidgetItem

# Explicit sort value for cells whose text does not sort meaningfully
# (icon-only or checkbox cells, formatted sizes).
SORT_ROLE = Qt.ItemDataRole.UserRole + 50

_GERMAN_DATE = re.compile(r'^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(.*)$', re.DOTALL)
_collator = None


def _text_collator():
    global _collator
    if _collator is None:
        _collator = QCollator(QLocale.system())
        _collator.setNumericMode(True)
        _collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return _collator


def _normalized(text):
    """Rewrite German dates (dd.mm.yyyy [time]) so they sort chronologically."""
    match = _GERMAN_DATE.match(text)
    if match:
        day, month, year, rest = match.groups()
        return f'{year}-{int(month):02}-{int(day):02}{rest}'
    return text.strip()


class SortableItem(QTableWidgetItem):
    """Table item sorting numbers numerically, dates chronologically and text naturally."""

    def sort_value(self):
        value = self.data(SORT_ROLE)
        return self.text() if value is None else value

    def __lt__(self, other):
        mine = self.sort_value()
        theirs = other.sort_value() if isinstance(other, SortableItem) else other.text()
        numeric = (int, float)
        if isinstance(mine, numeric) and isinstance(theirs, numeric):
            return mine < theirs
        if isinstance(mine, numeric) != isinstance(theirs, numeric):
            return isinstance(mine, numeric)
        return _text_collator().compare(_normalized(str(mine)), _normalized(str(theirs))) < 0


def enable_sorting(table):
    """Sort by clicking a column header; keep the loaded order until the user does."""
    table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    table.setSortingEnabled(True)


@contextmanager
def sorting_suspended(table):
    """Fill a table without rows moving between setItem calls, then re-apply the sort."""
    enabled = table.isSortingEnabled()
    table.setSortingEnabled(False)
    try:
        yield
    finally:
        table.setSortingEnabled(enabled)
