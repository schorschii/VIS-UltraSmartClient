"""Offline sample content for the interactive demo window."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidgetItem, QPlainTextEdit, QLineEdit, QListWidgetItem

from .gui import Client


def create_demo_window():
    window = Client(display_name='Alex Beispiel', tenant_name='Demo', load_repositories_on_start=False)
    window.setWindowTitle('UltraSmartClient – Demo')
    window.tabs.setCurrentIndex(0)
    repository = window.add_node(window.tree, 'Demo-Ablage', 'ablage.svg')
    documents = [
        ('Modernisierung des Bürgerportals', '2026 / IT / 042', 'Projektauftrag und Abstimmung der nächsten Schritte.'),
        ('Besprechung zur Haushaltsplanung', '2026 / FIN / 018', 'Protokoll der Besprechung und offene Entscheidungen.'),
        ('Antrag auf Fortbildung', '2026 / PERS / 007', 'Teilnahme an der Fortbildung zur digitalen Verwaltung.'),
    ]
    documents.extend([
        ('Digitalisierung der Verwaltung', '2026 / IT', 'Akte mit Projekten zur digitalen Verwaltung.'),
        ('Einführung des Bürgerportals', '2026 / IT / 042 / 01', 'Vorgang zur Planung und Einführung des Bürgerportals.'),
    ])
    akte = window.add_node(repository, documents[3][0], 'akte.svg')
    akte.setData(0, Qt.ItemDataRole.UserRole, 3)
    vorgang = window.add_node(akte, documents[4][0], 'vorgang.svg')
    vorgang.setData(0, Qt.ItemDataRole.UserRole, 4)
    nodes = {3: akte, 4: vorgang}
    for index, document in enumerate(documents[:3]):
        item = window.add_node(vorgang, document[0])
        item.setData(0, Qt.ItemDataRole.UserRole, index)
        nodes[index] = item
    akte.setToolTip(0, 'Typ: Akte')
    vorgang.setToolTip(0, 'Typ: Vorgang')

    def record_history(index):
        for row in range(window.history_list.count()):
            if window.history_list.item(row).data(Qt.ItemDataRole.UserRole) == index:
                window.history_list.takeItem(row)
                break
        entry = QListWidgetItem(documents[index][0])
        entry.setIcon(nodes[index].icon(0))
        entry.setData(Qt.ItemDataRole.UserRole, index)
        window.history_list.insertItem(0, entry)

    for index in (3, 4, 1):
        record_history(index)

    def show_document(item, _previous=None):
        if item is None:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(index, int):
            return
        title, reference, subject = documents[index]
        record_history(index)
        window.center_tabs.setTabIcon(0, item.icon(0))
        window.center_view.setCurrentIndex(1)
        window.properties_view.setCurrentIndex(1)
        window.center_tabs.setTabText(0, title)
        values = {'Name': title, 'Geschäftszeichen': reference, 'Betreff': subject,
                  'Kurzbezeichnung': title, 'Bemerkung': 'Fiktive Beispieldaten für die Offline-Demo.',
                  'Ablage': 'Demo-Ablage', 'Anlagen': '2', 'Dok.Datum': '24.11.2026'}
        for key, value in values.items():
            field = window.fields[key]
            if isinstance(field, QPlainTextEdit):
                field.setPlainText(value)
            elif isinstance(field, QLineEdit):
                field.setText(value)
        files = [('PDF', '—', '—', 'Projektunterlagen.pdf', '248.0 KiB',
                  '24.11.2026', 'Alex Beispiel', '20.11.2026'),
                 ('TXT', '—', '—', 'Besprechungsnotizen.txt', '3.2 KiB',
                  '23.11.2026', 'Kim Muster', '21.11.2026')]
        window.content.setRowCount(len(files))
        for row, values in enumerate(files):
            for column, value in enumerate(values):
                window.content.setItem(row, column, QTableWidgetItem(value))
        window.empty.hide()
        window.show_tasks([
            {'aufgabe': 'Bitte prüfen und Stellung nehmen', 'erlassen_fuer_id': 'Kim Muster',
             'kategorie': 'Stellungnahme', 'erlassen_von_id': 'Alex Beispiel',
             'termin': '30.11.2026', 'freigabe': '1', 'state': '0'},
            {'aufgabe': 'Zur Kenntnis', 'erlassen_fuer_id': 'Alex Beispiel',
             'kategorie': 'Kenntnisnahme', 'erlassen_von_id': 'Kim Muster',
             'erledigt_am': '23.11.2026', 'freigabe': '1', 'state': '1'},
        ])
        window.show_reminders([{'aufgabe': 'Rückmeldung nachhalten', 'termin': '01.12.2026', 'state': '0',
                                'kategorie': 'Wiedervorlage', 'vorlage_durch_id': 'Alex Beispiel',
                                'vorlage_fuer_id': 'Kim Muster', 'erlassen_von_id': 'Alex Beispiel'}])
        window.show_links([('Projektinformationen', 'https://example.org/projekt')])
        window.statusBar().showMessage('Demo-Modus – fiktive Daten, keine Serververbindung.')

    window.search.textChanged.connect(window.tree_filter.setText)
    window.tree.currentItemChanged.connect(show_document)
    window.tree.expandAll()
    window.history_list.itemClicked.connect(
        lambda item: window.tree.setCurrentItem(nodes[item.data(Qt.ItemDataRole.UserRole)]))
    window.tree.setCurrentItem(nodes[0])
    return window
