"""Watch opened downloads, including editors that save by replacing the file."""
import hashlib
from pathlib import Path
import shutil
import tempfile

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.digest()


def signature(path):
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class OpenFileMonitor(QObject):
    changed = pyqtSignal(object, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files = {}
        self.busy = False
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)

    def watch(self, file, path, object_name=''):
        path = Path(path)
        self.files[path] = {'file': file, 'object_name': object_name, 'digest': digest(path),
                            'signature': signature(path), 'pending': None}
        self.timer.start()

    def retry(self, path):
        if path in self.files:
            self.files[path]['signature'] = None
            self.files[path]['digest'] = None

    def poll(self):
        if self.busy:
            return
        for path, state in list(self.files.items()):
            temporary = None
            try:
                current = signature(path)
                if current == state['signature']:
                    state['pending'] = None
                    continue
                # Wait for two matching observations so multi-write saves settle.
                if current != state['pending']:
                    state['pending'] = current
                    continue
                temporary = tempfile.TemporaryDirectory(prefix='ultrasmartclient-upload-')
                snapshot = Path(temporary.name) / path.name
                shutil.copyfile(path, snapshot)
                if signature(path) != current:
                    temporary.cleanup()
                    continue
                checksum = digest(snapshot)
                state['signature'] = current
                state['pending'] = None
                if checksum == state['digest']:
                    temporary.cleanup()
                    continue
                state['digest'] = checksum
            except OSError:
                if temporary is not None:
                    temporary.cleanup()
                # Editors can briefly remove or lock the path during an atomic save.
                continue
            self.busy = True
            self.changed.emit(state['file'], path, snapshot, temporary)
            break
