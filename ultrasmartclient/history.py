"""Persistent most-recently-used objects, isolated by tenant base URL."""
import json
import os
from pathlib import Path
import tempfile

from PyQt6.QtCore import QObject, pyqtSignal


class HistoryStore(QObject):
    changed = pyqtSignal(str)
    limit = 20
    file_label = 'Verlaufsdatei'
    entry_label = 'Verlaufseintrag'

    def __init__(self, path=None, parent=None):
        super().__init__(parent)
        self.path = Path(path) if path is not None else Path.home() / '.config' / 'ultrasmartclient' / 'history.json'

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError('Ungültige ' + self.file_label + ': ' + str(self.path))
        for server, entries in data.items():
            if not isinstance(server, str) or not isinstance(entries, list):
                raise ValueError('Ungültige ' + self.file_label + ': ' + str(self.path))
            for entry in entries:
                if (not isinstance(entry, dict) or type(entry.get('id')) is not int
                        or not isinstance(entry.get('name'), str)
                        or type(entry.get('typ')) is not int
                        or type(entry.get('repository')) is not bool):
                    raise ValueError('Ungültiger ' + self.entry_label + ': ' + str(self.path))
        return data

    def entries(self, server_url):
        if not server_url:
            return []
        return self._load().get(server_url.rstrip('/'), [])[:self.limit]

    def record(self, server_url, entry):
        server_url = server_url.rstrip('/')
        data = self._load()
        entries = data.get(server_url, [])
        data[server_url] = [dict(entry)] + [old for old in entries
                                         if (old['id'], old['repository']) != (entry['id'], entry['repository'])]
        data[server_url] = data[server_url][:self.limit]
        self._save(data)
        self.changed.emit(server_url)

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
