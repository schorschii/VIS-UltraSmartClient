"""Persistent tenant configuration and the pre-login selection dialog."""
import json
import os
import sys
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout,
)

from . import APP_NAME, VERSION, executable_dir


TENANT_PATH_USER = Path.home() / '.config' / 'ultrasmartclient' / 'tenants.json'
TENANT_PATH_SYSTEM = '/etc/ultrasmartclient/tenants.json'
TENANT_REGISTRY_KEY = r'Software\Compaq\VIS'

def validate_tenant(name, server_url):
    name, server_url = name.strip(), server_url.strip().rstrip('/')
    url = urlsplit(server_url)
    if not name:
        raise ValueError('Bitte einen Mandantennamen angeben.')
    if (url.scheme not in ('http', 'https') or not url.hostname
            or url.username is not None or url.password is not None
            or url.query or url.fragment):
        raise ValueError('Bitte eine HTTP(S)-Server-Basis-URL ohne Zugangsdaten, Query oder Fragment angeben.')
    # Accessing port also validates malformed port numbers.
    url.port
    return {'name': name, 'server_url': server_url}


def system_tenant_path():
    candidates = [
        Path(TENANT_PATH_SYSTEM),
        executable_dir() / 'tenants.json'
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def registry_tenants(winreg=None):
    """Read tenants from HKCU and HKLM (both registry views).

    Each tenant is a subkey named by its GUID with an ``AppServer`` base URL; the
    tenant URL is ``AppServer/GUID``. ``System\\DefaultMandant`` names the default.
    Unusable entries are skipped since the registry is maintained by another program.
    """
    if winreg is None:
        if sys.platform != 'win32':
            return [], None
        import winreg
    roots = [(winreg.HKEY_CURRENT_USER, 0), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
             (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)]
    tenants, urls, default_url = [], set(), None

    def value(key, name):
        try:
            data, kind = winreg.QueryValueEx(key, name)
        except OSError:
            return None
        return data.strip() if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(data, str) else None

    for root, view in roots:
        try:
            base = winreg.OpenKey(root, TENANT_REGISTRY_KEY, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with base:
            index = 0
            while True:
                try:
                    subkey = winreg.EnumKey(base, index)
                except OSError:
                    break
                index += 1
                if subkey.casefold() == 'system':
                    if default_url is None:
                        try:
                            with winreg.OpenKey(base, subkey) as key:
                                default = value(key, 'DefaultMandant')
                        except OSError:
                            default = None
                        if default:
                            default_url = default.strip('{}').casefold()
                    continue
                if not (subkey.startswith('{') and subkey.endswith('}')):
                    continue
                try:
                    with winreg.OpenKey(base, subkey) as key:
                        app_server = value(key, 'AppServer')
                        name = value(key, '') or value(key, 'Name') or value(key, 'Description')
                except OSError:
                    continue
                if not app_server or not name:
                    continue
                identifier = subkey.strip('{}')
                try:
                    tenant = validate_tenant(name, app_server.rstrip('/') + '/' + identifier)
                except ValueError:
                    continue
                if tenant['server_url'] not in urls:
                    urls.add(tenant['server_url'])
                    tenants.append((identifier.casefold(), tenant))
    selected = next((i for i, (identifier, _) in enumerate(tenants) if identifier == default_url), None)
    return [tenant for _, tenant in tenants], selected


class TenantStore:
    def __init__(self, path=None, system_path=..., registry=...):
        self.path = Path(path) if path is not None else TENANT_PATH_USER
        if system_path is ...:
            system_path = system_tenant_path()
        self.system_path = Path(system_path) if system_path is not None else None
        # Callable returning (tenants, selected); None disables the registry source.
        self.registry = registry_tenants if registry is ... else registry

    def load(self):
        personal, selected = self._load_file(self.path)
        system, system_selected = self._load_file(self.system_path) if self.system_path else ([], None)
        # Registry tenants follow the system configuration.
        registry, registry_selected = self.registry() if self.registry else ([], None)
        registry_url = registry[registry_selected]['server_url'] if registry_selected is not None else None
        system_urls = {tenant['server_url'] for tenant in system}
        system = system + [tenant for tenant in registry if tenant['server_url'] not in system_urls]
        if system_selected is None and registry_url is not None:
            system_selected = next(i for i, tenant in enumerate(system) if tenant['server_url'] == registry_url)
        # Follow system configuration order while retaining personal overrides.
        selected_url = (personal[selected]['server_url'] if selected is not None else
                        system[system_selected]['server_url'] if system_selected is not None else None)
        overrides = {tenant['server_url']: tenant for tenant in personal}
        tenants = [overrides.get(tenant['server_url'], tenant) for tenant in system]
        urls = {tenant['server_url'] for tenant in tenants}
        for tenant in personal:
            if tenant['server_url'] not in urls:
                tenants.append(tenant)
                urls.add(tenant['server_url'])
        selected = next((i for i, tenant in enumerate(tenants)
                         if tenant['server_url'] == selected_url), None)
        return tenants, selected

    @staticmethod
    def _load_file(path):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return [], None
        if not isinstance(data, dict) or not isinstance(data.get('tenants'), list):
            raise ValueError('Ungültige Mandantenkonfiguration: ' + str(path))
        tenants = []
        for entry in data['tenants']:
            if (not isinstance(entry, dict) or not isinstance(entry.get('name'), str)
                    or not isinstance(entry.get('server_url'), str)):
                raise ValueError('Ungültiger Mandanteneintrag: ' + str(path))
            tenants.append(validate_tenant(entry['name'], entry['server_url']))
        selected = data.get('selected')
        if selected is not None and (type(selected) is not int or not 0 <= selected < len(tenants)):
            raise ValueError('Ungültige Mandantenauswahl: ' + str(path))
        return tenants, selected

    def save(self, tenants, selected):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({'tenants': tenants, 'selected': selected}, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class TenantSelector(QDialog):
    login_requested = pyqtSignal(str)

    def __init__(self, store=None, initial_url=None):
        super().__init__()
        self.store = store or TenantStore()
        self.tenants, selected = self.store.load()
        self.server_url = None
        self.tenant_name = None
        self.busy = False
        self.setWindowTitle(APP_NAME + ' ' + VERSION + ' - Mandantenauswahl')
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / 'assets' / 'icons' / 'app.png')))
        self.resize(600, 380)
        layout = QVBoxLayout(self)
        self.tenant_list = QListWidget()
        layout.addWidget(self.tenant_list)
        form = QFormLayout()
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText('https://vis.example.org/vis/MANDANT')
        form.addRow('Mandant', self.name)
        form.addRow('Server-URL', self.url)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.edit_buttons = []
        for label, callback in (('Neu', self.new_tenant), ('Speichern', self.save_tenant),
                                ('Entfernen', self.remove_tenant)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
            self.edit_buttons.append(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.login_button = buttons.addButton('Anmelden', QDialogButtonBox.ButtonRole.AcceptRole)
        self.login_button.setIcon(QIcon(str(Path(__file__).resolve().parent / 'assets' / 'icons' / 'login-arrow.svg')))
        self.login_button.setIconSize(QSize(20, 20))
        buttons.accepted.connect(self.login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.tenant_list.currentRowChanged.connect(self.populate)
        self.refresh(selected)
        if initial_url:
            match = next((i for i, tenant in enumerate(self.tenants)
                          if tenant['server_url'] == initial_url.rstrip('/')), None)
            if match is not None:
                self.tenant_list.setCurrentRow(match)
            else:
                self.new_tenant()
                self.url.setText(initial_url)
                self.name.setFocus()

    def refresh(self, selected):
        self.tenant_list.clear()
        for tenant in self.tenants:
            self.tenant_list.addItem(tenant['name'] + ' — ' + tenant['server_url'])
        self.tenant_list.setCurrentRow(selected if selected is not None else -1)
        if selected is None:
            self.populate(-1)

    def populate(self, index):
        tenant = self.tenants[index] if 0 <= index < len(self.tenants) else {}
        self.name.setText(tenant.get('name', ''))
        self.url.setText(tenant.get('server_url', ''))

    def new_tenant(self):
        self.tenant_list.setCurrentRow(-1)
        self.populate(-1)
        self.name.setFocus()

    def persist(self, tenants, selected):
        try:
            self.store.save(tenants, selected)
        except OSError as error:
            QMessageBox.critical(self, 'Konfiguration konnte nicht gespeichert werden', str(error))
            return False
        self.tenants = tenants
        self.refresh(selected)
        return True

    def save_tenant(self):
        try:
            tenant = validate_tenant(self.name.text(), self.url.text())
        except ValueError as error:
            QMessageBox.warning(self, 'Ungültiger Mandant', str(error))
            return False
        index = self.tenant_list.currentRow()
        tenants = list(self.tenants)
        if index < 0:
            index = len(tenants)
            tenants.append(tenant)
        else:
            tenants[index] = tenant
        return self.persist(tenants, index)

    def remove_tenant(self):
        index = self.tenant_list.currentRow()
        if index < 0:
            return
        tenants = self.tenants[:index] + self.tenants[index + 1:]
        self.persist(tenants, min(index, len(tenants) - 1) if tenants else None)

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.tenant_list, self.name, self.url, self.login_button, *self.edit_buttons):
            widget.setEnabled(not busy)
        self.login_button.setText('Anmeldung läuft …' if busy else 'Anmelden')

    def login(self):
        if self.busy:
            return
        if self.save_tenant():
            self.server_url = self.tenants[self.tenant_list.currentRow()]['server_url']
            self.tenant_name = self.tenants[self.tenant_list.currentRow()]['name']
            self.set_busy(True)
            self.login_requested.emit(self.server_url)
