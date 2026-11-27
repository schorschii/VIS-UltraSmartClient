"""UltraSmartClient GUI components, background workers, and styling."""
import json
from datetime import date, datetime, timedelta
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QSize, QPoint, QEvent, QTimer, QUrl, QDate, QSettings, pyqtSignal
from PyQt6.QtGui import QColor, QAction, QDesktopServices, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget, QTabBar, QTableWidget, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import APP_NAME, VERSION
from .user_selection import UserSelectionDialog
from .stellvertreter import StellvertreterManagementDialog
from .history import HistoryStore
from .file_monitor import OpenFileMonitor
from .vapi import VapiClient, Repository, TreeItem, ObjectFile
from .theme import ThemeManager
from .table_sort import SORT_ROLE, SortableItem, enable_sorting, sorting_suspended
from .mail_options import MailOptionsDialog
from .file_templates import FileTemplateDialog
from .paste_dialog import PasteDialog
from .new_object import NewObjectDialog
from .link_dialog import LinkDialog
from .object_history import ObjectHistoryDialog
from .workflow_dialogs import WorkflowDialog, WorkflowTemplateDialog
from .workflow_template_management import WorkflowTemplateManagementDialog


ICON_DIR         = Path(__file__).resolve().parent / 'assets' / 'icons'
SETTINGS_PATH    = Path.home() / '.config' / 'ultrasmartclient' / 'settings.ini'

FILE_COLUMNS = [
    'Typ', 'Ausprägung', 'Version', 'Name', 'Größe', 'Geändert am', 'Geändert von', 'Angelegt am'
]
CONTAINER_COLUMNS = [
    'Typ', 'Geschäftszeichen', 'Name', 'Heftung', 'Kurzbezeichnung', 'Betreff', 'Geändert am', 'Geändert durch'
]
TASK_COLUMNS = [
    ('Stufe', 'stufe'), ('Kategorie', 'kategorie'), ('Erlassen von', 'erlassen_von_id'),
    ('Erlassen für', 'erlassen_fuer_id'), ('Fällig am', 'termin'), ('Aufgabe', 'aufgabe'),
    ('Freigabe', 'freigabe'), ('Erledigt am', 'erledigt_am'), ('Vermerk', 'erledigung'),
    ('Angelegt durch', 'angelegt_von_id'), ('Angelegt am', 'angelegt_am'),
    ('Geändert durch', 'geaendert_von'), ('Geändert am', 'geaendert_am'),
    ('Rechteerweiterung', 'rechteerweiterung'), ('Bearbeitungsstatus', 'state'),
    ('Zeichnungsfarbe', 'zeichnungsfarbe'),
]
REMINDER_COLUMNS = [
    ('Kategorie', ('kategorie',)),
    ('Vorlage für', ('vorlage_fuer_id', 'vorlage_fuer', 'erlassen_fuer_id')),
    ('Vorlage durch', ('vorlage_durch_id', 'vorlage_durch', 'erlassen_von_id')),
    ('Vorlage am', ('vorlage_am', 'termin')),
    ('Zyklus', ('zyklus',)), ('Aufgabe', ('aufgabe',)),
    ('Erledigt am', ('erledigt_am',)), ('Vermerk', ('erledigung',)),
    ('Angelegt durch', ('angelegt_von_id',)), ('Angelegt am', ('angelegt_am',)),
    ('Geändert durch', ('geaendert_von',)), ('Geändert am', ('geaendert_am',)),
    ('Rechteerweiterung', ('rechteerweiterung',)), ('Bearbeitungsstatus', ('state',)),
    ('Zeichnungsfarbe', ('zeichnungsfarbe',)),
]


def settings():
    return QSettings(str(SETTINGS_PATH), QSettings.Format.IniFormat)

def object_icon(typ, repository=False):
    filename = 'disabled.svg'
    if repository: filename = 'ablage.svg'
    elif typ == 1: filename = 'akte.svg'
    elif typ == 3: filename = 'vorgang.svg'
    elif typ == 12: filename = 'dokument-in.svg'
    elif typ == 15: filename = 'dokument-out.svg'
    elif typ == 14: filename = 'dokument.svg'
    return QIcon(str(ICON_DIR / filename))


def vertical_scroll_only(scroll):
    """Fit a scroll area's content to its width; only vertical scrolling remains."""
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


def shrinkable_combo(field):
    """Let a combo box narrow below its longest entry instead of widening the form."""
    field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    field.setMinimumContentsLength(6)
    return field


def property_field(attribute):
    """Create the input widget the VIS properties pane uses for an attribute's draw type."""
    name, value = attribute['name'], attribute['value']
    if attribute['draw_type'] == '6':
        field = QCheckBox()
        field.setChecked(value.lower() in ('1', 'true'))
    elif attribute['draw_type'] in ('3', '4'):
        field = shrinkable_combo(QComboBox())
        field.addItems(list(dict.fromkeys([value] + attribute['choices'])))
    elif attribute['draw_type'] == '2' or name in ('Name', 'Kurzbezeichnung', 'Betreff'):
        field = QPlainTextEdit(value)
        field.setFixedHeight(52)
    else:
        field = QLineEdit(value)
    return field


def property_field_change(field, attribute):
    """Return the value to send for an edited field, or None when it still holds the server value."""
    if isinstance(field, QCheckBox):
        value = '1' if field.isChecked() else '0'
        original = '1' if attribute['value'].lower() in ('true', '1') else '0'
    else:
        value = (field.currentText() if isinstance(field, QComboBox) else
                 field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text())
        original = attribute['value']
    if value == original:
        return None
    if isinstance(field, QComboBox):
        # Combo fields use their selected server ID.
        value = attribute.get('choice_ids', {}).get(value) or value
    return value


def box(horizontal=False, margin=0, spacing=0):
    widget = QWidget()
    layout = (QHBoxLayout if horizontal else QVBoxLayout)(widget)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return widget, layout


class LayoutButton(QPushButton):
    """Push button whose content is a layout of child widgets instead of text/icon."""

    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()

    def hasHeightForWidth(self):
        return self.layout().hasHeightForWidth() if self.layout() else super().hasHeightForWidth()

    def heightForWidth(self, width):
        return self.layout().totalHeightForWidth(width) if self.layout() else super().heightForWidth(width)


class ContentTable(QTableWidget):
    """Fill the viewport until the user chooses custom column widths."""

    def __init__(self, headers):
        super().__init__(0, len(headers))
        self.file_drop_handler = None
        self._custom_widths = False
        self._fitting = False
        self._type_column = headers[0] == 'Typ'
        if self._type_column:
            self.setColumnWidth(0, 44)
        self.horizontalHeader().sectionResized.connect(self._column_resized)

    def _dropped_files(self, event):
        if self.file_drop_handler is None or not event.mimeData().hasUrls():
            return []
        urls = event.mimeData().urls()
        if not urls or any(not url.isLocalFile() or not Path(url.toLocalFile()).is_file() for url in urls):
            return []
        return [url.toLocalFile() for url in urls]

    def dragEnterEvent(self, event):
        if self._dropped_files(event) and event.possibleActions() & Qt.DropAction.CopyAction:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self._dropped_files(event)
        if (paths and event.possibleActions() & Qt.DropAction.CopyAction
                and self.file_drop_handler(paths)):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def _column_resized(self, *_args):
        if not self._fitting:
            self._custom_widths = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._custom_widths or self._fitting:
            return
        self._fitting = True
        try:
            first = 1 if self._type_column else 0
            available = self.viewport().width() - (self.columnWidth(0) if first else 0)
            count = self.columnCount() - first
            if count:
                width, remainder = divmod(max(0, available), count)
                for index in range(first, self.columnCount()):
                    self.setColumnWidth(index, width + (index - first < remainder))
        finally:
            self._fitting = False


class Section(QWidget):
    def __init__(self, title, content):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.button = QPushButton('⌄  ' + title)
        self.button.setProperty('section_title', title)
        self.button.setObjectName('section')
        self.button.setCheckable(True)
        self.button.setChecked(True)
        self.button.toggled.connect(content.setVisible)
        self.button.toggled.connect(lambda checked: self.button.setText(('⌄  ' if checked else '›  ') + self.button.property('section_title')))
        layout.addWidget(self.button)
        layout.addWidget(content, 1)


class UserInfoLoader(QObject):
    loaded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def run(self, api):
        try:
            name = api.fetch_display_name()
        except Exception as error:
            self.failed.emit(''.join(traceback.format_exception(error)))
        else:
            try:
                api.fetch_user_picture()
            except Exception:
                api.user_picture = b''
            try:
                api.fetch_stellvertreter()
            except Exception as error:
                api.stellvertreter = []
                api.stellvertreter_error = str(error)
            self.loaded.emit(name)


class RepositoryLoader(QObject):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self, api):
        try:
            result = api.fetch_repositories()
        except Exception as error:
            self.failed.emit(''.join(traceback.format_exception(error)))
        else:
            self.loaded.emit(result)


class TreeLoader(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, repository_id, parent_id, token):
        try:
            children = api.fetch_children(repository_id, parent_id)
        except Exception as error:
            self.finished.emit(token, None, ''.join(traceback.format_exception(error)))
        else:
            self.finished.emit(token, children, '')


class FileLoader(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, bo_id, token):
        try:
            files = api.fetch_files(bo_id)
        except Exception as error:
            self.finished.emit(token, None, ''.join(traceback.format_exception(error)))
        else:
            self.finished.emit(token, files, '')


class MyTasksLoader(QObject):
    finished = pyqtSignal(object, str)

    def run(self, api):
        try:
            rows = api.fetch_my_tasks()
        except Exception as error:
            self.finished.emit(None, str(error))
        else:
            self.finished.emit(rows, '')


class FavoritesLoader(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, folder_id, token):
        try:
            entries = api.fetch_favorites(folder_id=folder_id)
        except Exception as error:
            self.finished.emit(token, None, ''.join(traceback.format_exception(error)))
        else:
            self.finished.emit(token, entries, '')


class SearchWorker(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, query, token):
        try:
            result = api.search_objects(query)
        except Exception as error:
            self.finished.emit(token, None, str(error))
        else:
            self.finished.emit(token, result, '')


class LinkLoader(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, object_id, object_kind, token):
        try:
            links = api.fetch_object_details(object_id, object_kind)
        except Exception as error:
            self.finished.emit(token, None, ''.join(traceback.format_exception(error)))
        else:
            self.finished.emit(token, links, '')


class UserPictureWorker(QObject):
    finished = pyqtSignal(object, str)

    def run(self, api, data):
        try:
            api.set_user_picture(data)
        except Exception as error:
            self.finished.emit(data, str(error))
        else:
            self.finished.emit(data, '')


class WorkflowWorker(QObject):
    finished = pyqtSignal(object, str)

    def run(self, api, operation, args):
        try:
            result = getattr(api, operation)(*args)
        except Exception as error:
            self.finished.emit(None, str(error))
        else:
            self.finished.emit(result, '')


class OptionalDateEdit(QDateEdit):
    """Keep an unset value blank, but start its calendar selection on today."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat('dd.MM.yyyy')
        self.setCalendarPopup(True)
        self.setSpecialValueText(' ')
        self.setDate(self.minimumDate())
        calendar = self.calendarWidget()
        calendar.installEventFilter(self)
        # Clicking today must commit even when it is already highlighted.
        calendar.clicked.connect(self.setDate)
        calendar.activated.connect(self.setDate)

    def eventFilter(self, watched, event):
        result = super().eventFilter(watched, event)
        if watched is self.calendarWidget() and event.type() == QEvent.Type.Show:
            if self.date() == self.minimumDate():
                blocked = watched.blockSignals(True)
                try:
                    watched.setSelectedDate(QDate.currentDate())
                finally:
                    watched.blockSignals(blocked)
        return result


class PropertyEditWorker(QObject):
    finished = pyqtSignal(str, object, str)

    def run(self, api, action, args):
        try:
            method = {'begin': api.begin_property_edit, 'save': api.save_properties,
                      'cancel': api.cancel_property_edit, 'new_task': api.create_workflow_task,
                      'new_reminder': api.create_reminder,
                      'delete_link': api.delete_link, 'open_link': api.open_link_editor,
                      'delete_task': api.delete_workflow_task, 'delete_reminder': api.delete_reminder,
                      'task_command': api.workflow_task_command,
                      'delete_references': api.delete_references,
                      'open_template': api.open_workflow_templates,
                      'prepare_task': api.prepare_existing_task_edit,
                      'open_task': api.open_workflow_task, 'unlock': api.unlock_object,
                      'complete_task': api.complete_object_task, 'reject_task': api.reject_object_task,
                      'redirect_task': api.redirect_object_task,
                      'task_categories': api.fetch_task_categories}[action]
            result = method(*args)
        except Exception as error:
            self.finished.emit(action, None, str(error))
        else:
            self.finished.emit(action, result, '')


class FileRenameWorker(QObject):
    finished = pyqtSignal(object, str)

    def run(self, api, object_kind, file, name):
        try:
            api.rename_file(object_kind, file, name)
        except Exception as error:
            self.finished.emit(file, str(error))
        else:
            self.finished.emit(file, '')


class FileDeletionWorker(QObject):
    finished = pyqtSignal(object, str)

    def run(self, api, request, confirm=False):
        try:
            if confirm:
                if request.get('cancelled'):
                    api.confirm_file_deletion(request['session_id'], confirmed=False)
                else:
                    api.confirm_file_deletion(request['session_id'])
                result = request
            else:
                result = api.prepare_file_deletion(*request)
        except Exception as error:
            self.finished.emit(None, str(error))
        else:
            self.finished.emit(result, '')


class UploadLoader(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, object_id, paths):
        uploaded, errors = [], []
        for path in paths:
            try:
                api.upload_file(object_id, path)
                uploaded.append(path)
            except Exception as error:
                errors.append(f'{Path(path).name}: {error}')
        self.finished.emit(object_id, uploaded, '\n'.join(errors))


class SaveFileLoader(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, file, destination, token):
        try:
            path = api.download_file(file, destination=destination)
        except Exception as error:
            self.finished.emit(token, None, str(error))
        else:
            self.finished.emit(token, path, '')


class DownloadLoader(QObject):
    finished = pyqtSignal(int, object, str)

    def run(self, api, file, token):
        try:
            path = api.download_file(file)
        except Exception as error:
            self.finished.emit(token, None, ''.join(traceback.format_exception(error)))
        else:
            self.finished.emit(token, path, '')


class LoginStartup(QObject):
    """Create the main window only after the background login succeeds."""
    def __init__(self, app, server_url=None, selector=None):
        super().__init__(app)
        self.app = app
        self.server_url = server_url
        self.selector = selector
        self.cancelled = False
        self.api = None
        if selector is not None:
            selector.login_requested.connect(self.start)
            selector.rejected.connect(self.cancel)
        self.window = None
        self.error_dialog = None
        self.loader = UserInfoLoader()
        self.loader.loaded.connect(self.succeeded)
        self.loader.failed.connect(self.failed)

    def cancel(self):
        self.cancelled = True
        self.app.quit()

    def start(self, server_url=None):
        if self.cancelled:
            return
        if server_url is not None:
            self.server_url = server_url
        # Keep the event loop alive while login runs without a main window.
        self.app.setQuitOnLastWindowClosed(False)
        if not self.server_url:
            self.failed('Kein Server konfiguriert. Bitte einen Server in der Mandantenauswahl angeben.')
            return
        try:
            if self.api is not None:
                self.api.close()
            self.api = VapiClient(self.server_url, debug=getattr(self.app, 'soap_debug', False))
            self.app.aboutToQuit.connect(self.api.close)
        except Exception as error:
            self.failed(''.join(traceback.format_exception(error)))
            return
        threading.Thread(target=self.loader.run, args=(self.api,), daemon=True).start()

    def succeeded(self, display_name):
        if self.cancelled:
            return
        self.window = Client(self.server_url, display_name, api=self.api,
                             tenant_name=self.selector.tenant_name if self.selector else None)
        self.window.show()
        if self.selector is not None:
            self.selector.accept()
        self.app.setQuitOnLastWindowClosed(True)

    def failed(self, details):
        if self.cancelled:
            return
        self.error_dialog = QMessageBox(self.selector)
        self.error_dialog.setIcon(QMessageBox.Icon.Critical)
        self.error_dialog.setWindowTitle('Anmeldung fehlgeschlagen')
        self.error_dialog.setTextFormat(Qt.TextFormat.PlainText)
        self.error_dialog.setText('Benutzerinformationen konnten nicht geladen werden.')
        self.error_dialog.setInformativeText(details.strip().splitlines()[-1])
        self.error_dialog.setDetailedText(details)
        self.error_dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        self.error_dialog.exec()
        if self.selector is not None:
            self.selector.set_busy(False)
        else:
            self.app.exit(1)


class Client(QMainWindow):
    command_message = pyqtSignal(str, str)

    def __init__(self, server_url=None, display_name=None, api=None, history_store=None, tenant_name=None,
                 load_repositories_on_start=True):
        super().__init__()
        app = QApplication.instance()
        if not hasattr(app, 'theme_manager'):
            app.theme_manager = ThemeManager(app)
        self.theme = app.theme_manager
        if history_store is None:
            if not hasattr(app, 'history_store'):
                app.history_store = HistoryStore(parent=app)
            history_store = app.history_store
        self.history_store = history_store
        self._favorite_jobs = {}
        self._favorite_token = 0

        self.setWindowTitle(APP_NAME + ' ' + VERSION)
        self.setWindowIcon(QIcon(str(ICON_DIR / 'app.png')))
        self.resize(1492, 905)
        self.setMinimumSize(1000, 650)
        self.server_url = server_url
        self._property_edit = None
        self._property_worker = None
        self._property_attributes = []
        self._current_entry = None
        self.tenant_name = tenant_name
        self.api = api or (VapiClient(server_url, debug=getattr(app, 'soap_debug', False)) if server_url else None)
        self._command_message_dialogs = []
        self.command_message.connect(self.show_command_message, Qt.ConnectionType.QueuedConnection)
        if self.api is not None:
            self.api.command_message_handler = self.command_message.emit
        if self.api is not None and api is None:
            app.aboutToQuit.connect(self.api.close)
        self._download_token = 0
        self._download_jobs = {}
        self._save_jobs = {}
        self._upload_worker = None
        self._edited_upload = None
        self.file_monitor = OpenFileMonitor(self)
        self.file_monitor.changed.connect(self.confirm_edited_file)
        self._delete_worker = None
        self._picture_worker = None
        self._file_token = 0
        self._object_history = None
        self._file_jobs = {}
        self._link_jobs = {}
        self._tree_generation = 0
        self._tree_jobs = {}
        self._tree_token = 0
        self.document = None
        self.attachments = []
        self.fields = {}
        root, layout = box()
        self.setCentralWidget(root)
        top, row = box(True)
        self.tabs = QTabBar()
        for name in ('Start', 'Objekt', 'Einfügen'):
            self.tabs.addTab(name)
        row.addWidget(self.tabs)
        row.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Suchworte eingeben')
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(500)
        self._search_token = 0
        self._search_ready = False
        self._search_jobs = {}
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self.start_search)
        self.search_popup = QFrame(self, Qt.WindowType.ToolTip)
        self.search_popup.setFixedWidth(500)
        search_layout = QVBoxLayout(self.search_popup)
        search_layout.setContentsMargins(2, 2, 2, 2)
        self.search_status = QLabel()
        search_layout.addWidget(self.search_status)
        self.search_results = QListWidget()
        self.search_results.setObjectName('searchResults')
        self.search_results.setMouseTracking(True)
        self.search_results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.search_results.itemClicked.connect(self.open_search_result)
        search_layout.addWidget(self.search_results)
        self.search.textChanged.connect(self.search_changed)
        QApplication.instance().installEventFilter(self)
        row.addWidget(self.search)
        self.theme_selector = QComboBox()
        self.theme_selector.setAccessibleName('Farbschema')
        self.theme_selector.setToolTip('Farbschema')
        for label, mode in [('System', 'system'), ('Hell', 'light'), ('Dunkel', 'dark')]:
            self.theme_selector.addItem(label, mode)
        self.theme_selector.setCurrentIndex(self.theme_selector.findData(self.theme.mode))
        self.theme_selector.currentIndexChanged.connect(
            lambda _: self.theme.set_mode(self.theme_selector.currentData()))
        row.addWidget(self.theme_selector)
        layout.addWidget(top)
        self.ribbon = QStackedWidget()
        self.ribbon.setFixedHeight(112)
        self.build_ribbon()
        self.tabs.currentChanged.connect(self.ribbon.setCurrentIndex)
        self.tabs.setCurrentIndex(1)
        layout.addWidget(self.ribbon)
        self.breadcrumb, self.breadcrumb_layout = box(True, 3, 5)
        self.breadcrumb.setObjectName('breadcrumb')
        self.breadcrumb.setFixedHeight(28)
        layout.addWidget(self.breadcrumb)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.sidebar())
        self.center_view = QStackedWidget()
        self.center_view.addWidget(QWidget())
        self.center_view.addWidget(self.center())
        split.addWidget(self.center_view)
        self.properties_view = QStackedWidget()
        self.properties_view.setMinimumWidth(270)
        self.properties_view.addWidget(QWidget())
        self.properties_view.addWidget(self.properties())
        split.addWidget(self.properties_view)
        self.tree.currentItemChanged.connect(self.update_breadcrumb)
        self.update_breadcrumb(self.tree.currentItem())
        split.setSizes([320, 860, 310])
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)
        self.statusBar().showMessage('Bitte ein Objekt auswählen.')
        self.theme.changed.connect(self.refresh_theme)
        self.refresh_theme()
        self.display_name = display_name
        self.history_store.changed.connect(self.refresh_history)
        self.refresh_history()
        if display_name:
            self.user_info_loaded(display_name)
        if self.server_url and load_repositories_on_start:
            QTimer.singleShot(0, self.load_repositories)

    def load_repositories(self):
        if not self.server_url or not self.reload_repositories_action.isEnabled():
            return
        self.refresh_favorites()
        self.reload_repositories_action.setEnabled(False)
        self.statusBar().showMessage('Ablagen werden geladen …')
        self.repository_loader = RepositoryLoader()
        self.repository_loader.loaded.connect(self.repositories_loaded)
        self.repository_loader.failed.connect(self.repositories_failed)
        threading.Thread(target=self.repository_loader.run,
                         args=(self.api,), daemon=True).start()

    def repositories_loaded(self, repositories):
        self._tree_generation += 1
        self.clear_object_files()
        self.tree.clear()
        for repository in repositories:
            item = self.add_node(self.tree, repository.name, 'ablage.svg')
            item.setData(0, Qt.ItemDataRole.UserRole, repository)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            item.setToolTip(0, f'{repository.name}\nID: {repository.id}')
        pending_entry = getattr(self, '_open_after_repository_refresh', None)
        if pending_entry is not None:
            self._open_after_repository_refresh = None
            self.open_history_object(pending_entry)
        self.statusBar().showMessage('Make Dokumentenmanagement great again.' if repositories else 'Keine Ablagen vorhanden.')
        self.reload_repositories_action.setEnabled(True)
        self.filter_tree('')
        self.update_breadcrumb(self.tree.currentItem())

    def load_tree_children(self, item):
        node = item.data(0, Qt.ItemDataRole.UserRole)
        state_role = Qt.ItemDataRole.UserRole + 1
        if (self.api is None or not isinstance(node, (Repository, TreeItem))
                or item.data(0, state_role) in ('loading', 'loaded')
                or isinstance(node, TreeItem) and not node.has_children):
            return
        item.setData(0, state_role, 'loading')
        self.statusBar().showMessage('Untergeordnete Objekte werden geladen: ' + item.text(0))
        self._tree_token += 1
        token = self._tree_token
        worker = TreeLoader()
        self._tree_jobs[token] = (self._tree_generation, item, worker)
        worker.finished.connect(self.tree_children_finished)
        root = item
        while root.parent() is not None:
            root = root.parent()
        repository_id = root.data(0, Qt.ItemDataRole.UserRole).id
        parent_id = -1 if isinstance(node, Repository) else int(node.id)
        threading.Thread(target=worker.run,
                         args=(self.api, repository_id, parent_id, token), daemon=True).start()

    def tree_children_finished(self, token, children, error):
        job = self._tree_jobs.pop(token, None)
        if job is None or job[0] != self._tree_generation:
            return  # A repository refresh deleted the old QTreeWidgetItems.
        _, item, _worker = job
        state_role = Qt.ItemDataRole.UserRole + 1
        if error:
            item.setData(0, state_role, None)
            item.setExpanded(False)
            self.statusBar().showMessage('Laden fehlgeschlagen. Zum Wiederholen erneut aufklappen.')
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Critical)
            dialog.setWindowTitle('Untergeordnete Objekte laden fehlgeschlagen')
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText('Objekte unter „' + item.text(0) + '“ konnten nicht geladen werden.')
            dialog.setInformativeText(error.strip().splitlines()[-1])
            dialog.setDetailedText(error)
            dialog.exec()
            return
        for child in children:
            node = self.add_node(item, child.text)
            node.setIcon(0, object_icon(child.icon_id))
            if child.completed:
                node.setIcon(1, QIcon(str(ICON_DIR / 'lock.svg')))
            node.setData(0, Qt.ItemDataRole.UserRole, child)
            node.setToolTip(0, (
                str(child.text)
                + '\n' + 'ID: ' + str(child.id)
                + ('\n' + 'Abgeschlossen' if child.completed else '')
            ))
            node.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator if child.has_children
                else QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        item.setData(0, state_role, 'loaded')
        self.statusBar().showMessage(f'{len(children)} Objekte unter „{item.text(0)}“ geladen.')
        self.filter_tree('')

    def clear_object_files(self):
        self._object_history = None
        self._current_entry = None
        self.center_view.setCurrentIndex(0)
        self.properties_view.setCurrentIndex(0)
        self._file_token += 1
        self.content.setRowCount(0)
        self.links.setRowCount(0)
        self.show_tasks([])
        self.show_reminders([])
        self.references.setRowCount(0)
        self._displayed_references = []
        self.references_empty.setText('Dieses Objekt hat keine Bezüge.')
        self.references_empty.setToolTip('')
        self.references_empty.show()
        self.links_empty.setText('Dieses Objekt hat keine Verknüpfung.')
        self.links_empty.show()
        self.empty.setText('Bitte ein Objekt auswählen.')
        self.empty.show()
        if self.server_url:
            self.show_properties([])
        if 'Anlagen' in self.fields:
            self.fields['Anlagen'].setText('0')

    def load_object_files(self, item, _column=0):
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if self.api is None or not isinstance(node, (Repository, TreeItem)):
            return
        entry = {'id': int(node.id), 'name': item.text(0), 'typ': node.typ,
                 'repository': isinstance(node, Repository)}
        root = item
        while root.parent() is not None:
            root = root.parent()
        repository = root.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(repository, Repository):
            entry['repository_id'] = repository.id
        if isinstance(node, Repository):
            entry['object_kind'] = node.object_kind
        if isinstance(node, TreeItem):
            entry['object_kind'] = node.object_kind
            entry['icon_id'] = node.icon_id
        entry['container'] = isinstance(node, Repository) or node.has_children or node.typ in (-1000001, -150)
        self.update_breadcrumb(item)
        self.open_history_object(entry)

    def refresh_history(self, server_url=None):
        if server_url is not None and server_url != (self.server_url or '').rstrip('/'):
            return
        try:
            entries = self.history_store.entries(self.server_url)
        except (OSError, ValueError) as error:
            self.statusBar().showMessage('Verlauf konnte nicht geladen werden: ' + str(error))
            return
        self.history_list.clear()
        for entry in entries:
            item = QListWidgetItem(entry['name'])
            item.setIcon(object_icon(entry.get('icon_id', 0), entry['repository']))
            item.setToolTip(f"{entry['name']}\nID: {entry['id']}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.history_list.addItem(item)

    def load_my_tasks(self):
        if self.api is None or self._my_tasks_loading:
            return
        self._my_tasks_loading = True
        self.my_tasks_status.setText('Aufgaben werden geladen …')
        self.my_tasks_status.show()
        self.my_tasks_loader = MyTasksLoader()
        self.my_tasks_loader.finished.connect(self.my_tasks_finished)
        threading.Thread(target=self.my_tasks_loader.run, args=(self.api,), daemon=True).start()

    def my_tasks_finished(self, rows, error):
        self._my_tasks_loading = False
        if error:
            self.my_tasks_status.setText('Aufgaben konnten nicht geladen werden: ' + error)
            self.my_tasks_status.show()
            return
        self._my_tasks_loaded = True
        self.my_tasks_status.setText('' if rows else 'Keine Aufgaben vorhanden.')
        self.my_tasks_status.setVisible(not rows)
        self.tasks.clear()
        root = QTreeWidgetItem(self.tasks, [f'Meine Aufgaben ({len(rows)})'])
        groups = {}
        for task in rows:
            category = 'Wiedervorlagen' if task.get('kategorie_typ') == 'Wiedervorlagen' else 'Geschäftsgangverfügungen'
            due = task.get('termin', '')
            bucket = 'Ohne Fälligkeit'
            if due:
                try:
                    deadline = datetime.strptime(due, '%d.%m.%Y').date()
                    today = date.today()
                    week_end = today + timedelta(days=6 - today.weekday())
                    bucket = 'Überfällig' if deadline < today else 'Diese Woche' if deadline <= week_end else 'Später'
                except ValueError:
                    bucket = due
            if category not in groups:
                groups[category] = (QTreeWidgetItem(root, [category]), {})
            group, buckets = groups[category]
            if bucket not in buckets:
                buckets[bucket] = QTreeWidgetItem(group, [bucket])
            parent = buckets[bucket]
            name = task.get('name') or task.get('betreff') or task.get('obj_id', '')
            item = QTreeWidgetItem(parent, [(task.get('kategorie') or 'Aufgabe') + '\n' + name])
            item.setData(0, Qt.ItemDataRole.UserRole, task)
            item.setToolTip(0, f"{name}\n{task.get('aufgabe', '')}\nID: {task.get('obj_id', '')}\nFällig: {due}")
            try:
                item.setIcon(0, object_icon(int(task.get('objekticon_id') or 0)))
            except ValueError:
                pass
        for category, (group, buckets) in groups.items():
            count = sum(parent.childCount() for parent in buckets.values())
            group.setText(0, f'{category} ({count})')
            for bucket, parent in buckets.items():
                parent.setText(0, f'{bucket} ({parent.childCount()})')
        self.tasks.expandAll()
        self.filter_my_tasks()

    def filter_my_tasks(self, _text=''):
        terms = self.task_filter.text().casefold().split()
        def visit(item):
            if item.childCount():
                visible = [visit(item.child(i)) for i in range(item.childCount())]
                match = any(visible)
            else:
                match = all(term in (item.text(0) + ' ' + item.toolTip(0)).casefold() for term in terms)
            item.setHidden(not match)
            return match
        for index in range(self.tasks.topLevelItemCount()):
            visit(self.tasks.topLevelItem(index))

    def activate_my_task(self, item, _column=0):
        task = item.data(0, Qt.ItemDataRole.UserRole)
        if not task:
            return
        try:
            entry = dict(id=int(task['obj_id']), name=task.get('name') or task['obj_id'],
                         typ=int(task.get('objekttyp_id') or 0), object_kind=int(task['objektart_id']),
                         icon_id=int(task.get('objekticon_id') or 0), repository=False, container=True)
        except (KeyError, ValueError):
            self.my_tasks_status.setText('Die Aufgabe enthält keine gültige Objekt-ID oder Objektart.')
            self.my_tasks_status.show()
            return
        self.navigate_content(entry, [])

    def refresh_favorites(self, item=None):
        if self.api is None:
            return
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole + 1) in ('loading', 'loaded'):
            return
        if item is None:
            self._favorite_token += 1
            self.favorites.clear()
        else:
            item.setData(0, Qt.ItemDataRole.UserRole + 1, 'loading')
        self._favorite_job_id = getattr(self, '_favorite_job_id', 0) + 1
        job_id = self._favorite_job_id
        worker = FavoritesLoader()
        self._favorite_jobs[job_id] = (self._favorite_token, item, worker)
        worker.finished.connect(self.favorites_finished)
        folder_id = item.data(0, Qt.ItemDataRole.UserRole)['favorite_id'] if item else None
        threading.Thread(target=worker.run, args=(self.api, folder_id, job_id), daemon=True).start()

    def favorites_finished(self, job_id, entries, error):
        job = self._favorite_jobs.pop(job_id, None)
        if job is None or job[0] != self._favorite_token:
            return
        _, parent, _worker = job
        if error:
            if parent is not None:
                parent.setData(0, Qt.ItemDataRole.UserRole + 1, None)
                parent.setExpanded(False)
            self.statusBar().showMessage('Favoriten konnten nicht geladen werden: ' + error.strip().splitlines()[-1])
            return
        for entry in entries:
            item = QTreeWidgetItem(parent if parent is not None else self.favorites, [entry['name']])
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            item.setIcon(0, QIcon(str(ICON_DIR / 'favorite-folder.svg')) if entry['folder'] else object_icon(entry['icon_id']))
            item.setToolTip(0, f"{entry['name']}\nID: {entry['id']}\nFavoriten-ID: {entry['favorite_id']}")
            if entry['folder']:
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        if parent is not None:
            parent.setData(0, Qt.ItemDataRole.UserRole + 1, 'loaded')
        self.statusBar().showMessage(f'{len(entries)} Favoriten geladen.')

    def activate_favorite(self, item, _column=0):
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if entry['folder']:
            item.setExpanded(True)
            self.refresh_favorites(item)
        else:
            self.navigate_content(entry, [])

    def selected_favorite_folder(self):
        """Return the selected favorite folder item, or the folder containing the selected favorite."""
        # The current item survives deselection (Ctrl+click, click on empty space); only honour a real selection.
        selected = self.favorites.selectedItems()
        return self.favorite_folder_of(selected[0] if selected else None)

    def add_favorite(self):
        entry = self._current_entry
        if self.api is None or not entry or entry.get('id') is None:
            self.statusBar().showMessage('Bitte zuerst ein VIS-Objekt öffnen.')
            return
        if getattr(self, '_add_favorite_worker', None) is not None:
            return
        folder = self.selected_favorite_folder()
        parent_id = folder.data(0, Qt.ItemDataRole.UserRole)['favorite_id'] if folder is not None else 0
        worker = WorkflowWorker()
        self._add_favorite_worker = worker
        token = self._favorite_token
        worker.finished.connect(lambda _result, error: self.add_favorite_finished(entry['name'], folder, token, error))
        self.statusBar().showMessage('Favorit wird hinzugefügt: ' + entry['name'])
        threading.Thread(target=worker.run,
                         args=(self.api, 'add_favorite', (entry['id'], entry['name'], parent_id)),
                         daemon=True).start()

    def add_favorite_finished(self, name, folder, token, error):
        self._add_favorite_worker = None
        if error:
            self.statusBar().showMessage('Favorit konnte nicht hinzugefügt werden: ' + error.strip().splitlines()[-1])
            return
        self.statusBar().showMessage('Als Favorit hinzugefügt: ' + name)
        self.reload_favorite_folder(folder, token)

    def reload_favorite_folder(self, folder, token):
        """Reload a favorite folder (or the whole tree) after it changed on the server."""
        if folder is None or token != self._favorite_token:
            self.refresh_favorites()
        elif folder.data(0, Qt.ItemDataRole.UserRole + 1) != 'loading':
            folder.takeChildren()
            folder.setData(0, Qt.ItemDataRole.UserRole + 1, None)
            folder.setExpanded(True)
            self.refresh_favorites(folder)

    def favorites_context_menu(self, position):
        menu = QMenu(self)
        item = self.favorites.itemAt(position)
        remove_action = folder_action = None
        if self.api is not None:
            folder_action = menu.addAction('Neuer Favoritenordner …')
            folder_action.setEnabled(getattr(self, '_create_folder_worker', None) is None)
        if item is not None and self.api is not None:
            remove_action = menu.addAction('Aus Favoriten entfernen')
            remove_action.setEnabled(getattr(self, '_remove_favorite_worker', None) is None)
        if self.api is not None:
            menu.addSeparator()
        reload_action = menu.addAction('Favoriten aktualisieren')
        chosen = menu.exec(self.favorites.viewport().mapToGlobal(position))
        if chosen is None:
            return
        if chosen == reload_action:
            self.refresh_favorites()
        elif chosen == remove_action:
            self.remove_favorite(item)
        elif chosen == folder_action:
            self.create_favorite_folder(item)

    def favorite_folder_of(self, item):
        """Return the folder item itself, or the folder containing the given favorite."""
        while item is not None:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry and entry.get('folder'):
                return item
            item = item.parent()
        return None

    def create_favorite_folder(self, item=None):
        if self.api is None or getattr(self, '_create_folder_worker', None) is not None:
            return
        folder = self.favorite_folder_of(item)
        name, accepted = QInputDialog.getText(self, 'Neuer Favoritenordner', 'Name des Ordners:')
        name = name.strip()
        if not accepted or not name:
            return
        parent_id = folder.data(0, Qt.ItemDataRole.UserRole)['favorite_id'] if folder is not None else 0
        worker = WorkflowWorker()
        self._create_folder_worker = worker
        token = self._favorite_token
        worker.finished.connect(lambda _result, error: self.create_favorite_folder_finished(name, folder, token, error))
        self.statusBar().showMessage('Favoritenordner wird angelegt: ' + name)
        threading.Thread(target=worker.run, args=(self.api, 'create_favorite_folder', (name, parent_id)),
                         daemon=True).start()

    def create_favorite_folder_finished(self, name, folder, token, error):
        self._create_folder_worker = None
        if error:
            self.statusBar().showMessage('Favoritenordner konnte nicht angelegt werden: '
                                         + error.strip().splitlines()[-1])
            return
        self.statusBar().showMessage('Favoritenordner angelegt: ' + name)
        self.reload_favorite_folder(folder, token)

    def remove_favorite(self, item):
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if self.api is None or not entry or getattr(self, '_remove_favorite_worker', None) is not None:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Favorit entfernen')
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        kind = 'Den Favoritenordner' if entry['folder'] else 'Den Favoriten'
        dialog.setText(f'{kind} „{entry["name"]}“ aus den Favoriten entfernen?')
        if entry['folder']:
            dialog.setInformativeText('Enthaltene Favoriten werden ebenfalls entfernt.')
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return
        worker = WorkflowWorker()
        self._remove_favorite_worker = worker
        token = self._favorite_token
        worker.finished.connect(lambda _result, error: self.remove_favorite_finished(item, entry, token, error))
        self.statusBar().showMessage('Favorit wird entfernt: ' + entry['name'])
        threading.Thread(target=worker.run, args=(self.api, 'delete_favorite', (entry['favorite_id'],)),
                         daemon=True).start()

    def remove_favorite_finished(self, item, entry, token, error):
        self._remove_favorite_worker = None
        if error:
            self.statusBar().showMessage('Favorit konnte nicht entfernt werden: ' + error.strip().splitlines()[-1])
            return
        self.statusBar().showMessage('Aus Favoriten entfernt: ' + entry['name'])
        if token != self._favorite_token:
            # The tree was reloaded meanwhile and may still list the removed entry.
            self.refresh_favorites()
            return
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            self.favorites.takeTopLevelItem(self.favorites.indexOfTopLevelItem(item))

    def activate_history(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or self.api is None:
            return
        # Reveal the object if it is already loaded; reopening does not require
        # downloading the tree path after an application restart.
        pending = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        match = None
        while pending:
            node_item = pending.pop()
            node = node_item.data(0, Qt.ItemDataRole.UserRole)
            if (isinstance(node, (Repository, TreeItem)) and int(node.id) == entry['id']
                    and isinstance(node, Repository) == entry['repository']):
                match = node_item
                break
            pending.extend(node_item.child(i) for i in range(node_item.childCount()))
        self.tree.setCurrentItem(match)
        if match is not None:
            self.tree.scrollToItem(match)
            self.load_object_files(match)
        else:
            self.navigate_content(entry, [])

    def open_history_object(self, entry):
        if self.property_edit_active():
            return
        try:
            self.history_store.record(self.server_url, entry)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Verlauf konnte nicht gespeichert werden', str(error))
        self.clear_object_files()
        self._current_entry = dict(entry)
        self.center_view.setCurrentIndex(1)
        self.properties_view.setCurrentIndex(1)
        if self.server_url and 'Name' in self.fields:
            self.fields['Name'].setPlainText(entry['name'])
            self.fields['Name'].setToolTip(entry['name'])
        self.center_tabs.setCurrentIndex(0)
        self.center_tabs.setTabIcon(0, object_icon(entry.get('icon_id', 0), entry['repository']))
        self.center_tabs.setTabText(0, entry['name'])
        self.center_tabs.setTabToolTip(0, entry['name'])
        self.empty.setText('Inhalt wird geladen …')
        self.statusBar().showMessage('Inhalt wird geladen: ' + entry['name'])
        token = self._file_token
        if entry.get('object_kind') is not None:
            for widget in [self.links_empty, self.references_empty, self.properties_status, self.tasks_empty, self.reminders_empty]:
                widget.setText('Wird geladen …')
            link_worker = LinkLoader()
            self._link_jobs[token] = link_worker
            link_worker.finished.connect(self.links_finished)
            threading.Thread(target=link_worker.run,
                             args=(self.api, entry['id'], entry['object_kind'], token), daemon=True).start()
        elif not entry['repository']:
            for widget in [self.links_empty, self.references_empty, self.properties_status, self.tasks_empty, self.reminders_empty]:
                widget.setText('Nicht verfügbar: Objekttyp fehlt.')
        self._content_repository = entry.get('repository_id', entry['id'] if entry['repository'] else None)
        container = entry.get('container', entry['repository'])
        self._content_parent = (-1 if entry['repository'] else entry['id']) if container else None
        self.content.setHorizontalHeaderLabels(FILE_COLUMNS)
        worker = FileLoader()
        self._file_jobs[token] = worker
        worker.finished.connect(self.object_files_finished)
        threading.Thread(target=worker.run, args=(self.api, entry['id'], token), daemon=True).start()

    def object_files_finished(self, token, files, error):
        self._file_jobs.pop(token, None)
        if token != self._file_token:
            return
        if error:
            self.empty.setText('Inhalt konnte nicht geladen werden. Zum Wiederholen Objekt erneut anklicken.')
            self.statusBar().showMessage('Inhalt konnte nicht geladen werden.')
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Critical)
            dialog.setWindowTitle('Inhalt laden fehlgeschlagen')
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText('Der Inhalt des ausgewählten Objekts konnte nicht geladen werden.')
            dialog.setInformativeText(error.strip().splitlines()[-1])
            dialog.setDetailedText(error)
            dialog.exec()
            return
        if not files and self._content_parent is not None:
            self.content.setHorizontalHeaderLabels(CONTAINER_COLUMNS)
            worker = TreeLoader()
            self._file_jobs[token] = worker
            worker.finished.connect(self.container_contents_finished)
            threading.Thread(target=worker.run,
                             args=(self.api, self._content_repository, self._content_parent, token),
                             daemon=True).start()
            return
        self.content.setHorizontalHeaderLabels(FILE_COLUMNS)
        with sorting_suspended(self.content):
            self.content.setRowCount(len(files))
            for row, file in enumerate(files):
                values = (Path(file.name).suffix.lstrip('.').upper(), '—', '—', file.name,
                          f'{file.size / 1024:.1f} KiB', file.modified.replace('T', ' '),
                          file.modified_by, file.created.replace('T', ' '))
                for column, value in enumerate(values):
                    cell = SortableItem(value)
                    if column == 4:
                        cell.setData(SORT_ROLE, file.size)
                    cell.setData(Qt.ItemDataRole.UserRole, file)
                    cell.setToolTip(file.comment or file.name)
                    self.content.setItem(row, column, cell)
        self.empty.setText('Dieses Objekt besitzt keinen Inhalt.')
        self.empty.setVisible(not files)
        if 'Anlagen' in self.fields and 'Anlagen' not in getattr(self, '_server_property_names', set()):
            self.fields['Anlagen'].setText(str(len(files)))
        self.statusBar().showMessage(f'{len(files)} Dateien geladen.')

    def links_finished(self, token, relations, error):
        self._link_jobs.pop(token, None)
        if token != self._file_token or self._property_edit is not None or self._property_worker is not None:
            return
        if error:
            for widget in [self.links_empty, self.references_empty, self.properties_status, self.tasks_empty, self.reminders_empty]:
                widget.setText('Konnte nicht geladen werden. Zum Wiederholen Objekt erneut anklicken.')
                widget.setToolTip(error)
            return
        self.show_tasks(relations[3] if len(relations) > 3 else [])
        self.show_reminders(relations[4] if len(relations) > 4 else [])
        self._object_history = relations[5] if len(relations) > 5 else []
        links, references = relations[:2]
        if len(relations) > 2 and self._property_edit is None and self._property_worker is None:
            self.show_properties(relations[2])
        self.show_links(links)
        self.show_references(references)

    def show_references(self, references):
        self._displayed_references = list(references)
        self.references_empty.setToolTip('')
        with sorting_suspended(self.references):
            self.references.setRowCount(len(references))
            for row, reference in enumerate(references):
                entry = {'id': reference.id, 'name': reference.name or str(reference.id),
                         'typ': reference.object_kind, 'object_kind': reference.object_kind,
                         'repository': False}
                values = (str(reference.object_kind), reference.name, reference.relation,
                          reference.comment, reference.sequence)
                for column, value in enumerate(values):
                    cell = SortableItem(value)
                    cell.setData(Qt.ItemDataRole.UserRole, entry)
                    cell.setToolTip(f'{value}\nID: {reference.id}')
                    cell.setData(Qt.ItemDataRole.UserRole + 1, reference)
                    if column == 0:
                        cell.setText('')
                        cell.setData(SORT_ROLE, reference.object_kind)
                        cell.setIcon(object_icon(reference.icon_id or reference.object_kind))
                    self.references.setItem(row, column, cell)
        self.references_empty.setText('Dieses Objekt hat keine Bezüge.')
        self.references_empty.setVisible(not references)

    def show_links(self, links):
        self.links_empty.setToolTip('')
        with sorting_suspended(self.links):
            self.links.setRowCount(len(links))
            for row, link in enumerate(links):
                for column, value in enumerate(link):
                    cell = SortableItem(value)
                    cell.setToolTip(value)
                    self.links.setItem(row, column, cell)
        self.links_empty.setText('Dieses Objekt hat keine Verknüpfung.')
        self.links_empty.setVisible(not links)
    def current_links(self):
        return [(self.links.item(row, 0).text(), self.links.item(row, 1).text())
                for row in range(self.links.rowCount())]

    def workflow_context_menu(self, table, position):
        item = table.itemAt(position)
        if item is None or self._property_edit is None:
            self.table_reload_menu(table, position)
            return
        table.selectRow(item.row())
        row = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        idle = (self.api is not None and self._property_worker is None
                and row is not None and row.get('_session_index') is not None)
        delete_action = menu.addAction('Löschen')
        delete_action.setEnabled(idle)
        row_actions = {}
        if table is self.task_table:
            # Position in the session's order, which the table's sorting may not show.
            order = [str(task.get('_session_index')) for task in self._property_edit.get('tasks', [])]
            position_in_session = order.index(str(row['_session_index'])) if idle and str(row['_session_index']) in order else -1
            first, last = position_in_session == 0, position_in_session == len(order) - 1
            available = self.api.workflow_task_commands(self._property_edit) if self.api is not None else {}
            for label, action, allowed in (
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
                entry.setEnabled(idle and position_in_session >= 0 and allowed and action in available)
                if action not in available:
                    entry.setToolTip('Der Server bietet diesen Befehl für dieses Objekt nicht an.')
                row_actions[entry] = action
            menu.setToolTipsVisible(True)
        chosen = menu.exec(table.viewport().mapToGlobal(position))
        if chosen is None or not chosen.isEnabled():
            return
        if chosen == delete_action:
            self.create_workflow_task('delete_task' if table is self.task_table else 'delete_reminder',
                                      (row['_session_index'],))
        elif chosen in row_actions:
            self.create_workflow_task('task_command', (row_actions[chosen], row['_session_index']))

    def references_context_menu(self, position):
        item = self.references.itemAt(position)
        if item is None:
            self.table_reload_menu(self.references, position)
            return
        if not item.isSelected():
            self.references.selectRow(item.row())
        references = [self.references.item(index.row(), 0).data(Qt.ItemDataRole.UserRole + 1)
                      for index in self.references.selectionModel().selectedRows()]
        menu = QMenu(self)
        delete_action = menu.addAction('Bezüge löschen')
        delete_action.setEnabled(bool(references) and self.api is not None and bool(self._current_entry)
                                 and self._current_entry.get('object_kind') is not None
                                 and self._property_worker is None)
        reload_action = menu.addAction('Neu laden')
        reload_action.setEnabled(self._property_edit is None and self._property_worker is None)
        selected = menu.exec(self.references.viewport().mapToGlobal(position))
        if selected == delete_action:
            self.create_workflow_task('delete_references', (references,))
        elif selected == reload_action:
            self.reload_object_tables()

    def links_context_menu(self, position):
        item = self.links.itemAt(position)
        can_edit = (self.api is not None and bool(self._current_entry)
                    and self._current_entry.get('object_kind') is not None and self._property_worker is None)
        menu = QMenu(self)
        open_action = delete_action = None
        if item is not None:
            self.links.selectRow(item.row())
            link = self.current_links()[item.row()]
            open_action = menu.addAction('URL öffnen')
            open_action.setEnabled(bool(link[1]))
        new_action = menu.addAction('Neue Verknüpfung …')
        new_action.setEnabled(can_edit)
        if item is not None:
            delete_action = menu.addAction('Verknüpfung löschen')
            delete_action.setEnabled(can_edit)
        menu.addSeparator()
        reload_action = menu.addAction('Neu laden')
        reload_action.setEnabled(self._property_edit is None and self._property_worker is None)
        selected = menu.exec(self.links.viewport().mapToGlobal(position))
        if selected is None:
            return
        if selected == new_action:
            if self._property_edit is not None and not hasattr(self, '_original_links'):
                self._original_links = self.current_links()
                self._original_references = list(getattr(self, '_displayed_references', []))
            # Without an open edit session, cancelling the dialog closes the one opened for it.
            self._link_session_was_open = self._property_edit is not None
            self.create_workflow_task('open_link')
        elif selected == open_action:
            QDesktopServices.openUrl(QUrl(link[1]))
        elif selected == delete_action:
            if self._property_edit is not None and not hasattr(self, '_original_links'):
                self._original_links = self.current_links()
                self._original_references = list(getattr(self, '_displayed_references', []))
            self.create_workflow_task('delete_link', (link,))
        elif selected == reload_action:
            self.reload_object_tables()

    def container_contents_finished(self, token, children, error):
        self._file_jobs.pop(token, None)
        if token != self._file_token:
            return
        if error:
            self.object_files_finished(token, None, error)
            return
        with sorting_suspended(self.content):
            self.content.setRowCount(len(children))
            for row, child in enumerate(children):
                values = ('', child.reference, child.text, child.sequence, child.short_name,
                          child.subject, child.modified.replace('T', ' '), child.modified_by)
                for column, value in enumerate(values):
                    cell = SortableItem(value)
                    cell.setData(Qt.ItemDataRole.UserRole, child)
                    cell.setToolTip(value or child.text)
                    if column == 0:
                        cell.setData(SORT_ROLE, child.icon_id)
                        cell.setIcon(object_icon(child.icon_id))
                    self.content.setItem(row, column, cell)
        self.empty.setText('Dieses Objekt besitzt keinen Inhalt.')
        self.empty.setVisible(not children)
        self.statusBar().showMessage(f'{len(children)} Objekte geladen.')

    def open_content_file(self, item):
        file = item.data(Qt.ItemDataRole.UserRole)
        if self.api is not None and isinstance(file, TreeItem):
            entry = {'id': int(file.id), 'name': file.text, 'typ': file.typ,
                                      'repository': False, 'repository_id': self._content_repository,
                                      'object_kind': file.object_kind, 'icon_id': file.icon_id,
                                      'container': file.has_children or file.typ in (-1000001, -150)}
            self.navigate_content(entry, self._breadcrumb_path)
            return
        if self.api is None or not isinstance(file, ObjectFile):
            return
        if any(active.file_id == file.file_id and active.bo_id == file.bo_id
               for active, _worker in self._download_jobs.values()):
            return
        self._download_token += 1
        token = self._download_token
        worker = DownloadLoader()
        entry = self._current_entry or {}
        worker.object_name = entry.get('name', '') if entry.get('id') == file.bo_id else ''
        self._download_jobs[token] = (file, worker)
        worker.finished.connect(self.download_finished)
        self.statusBar().showMessage('Datei wird heruntergeladen: ' + file.name)
        threading.Thread(target=worker.run, args=(self.api, file, token), daemon=True).start()

    def download_finished(self, token, path, error):
        job = self._download_jobs.pop(token, None)
        if job is None:
            return
        file, _worker = job
        if not error:
            try:
                self.file_monitor.watch(file, path, _worker.object_name)
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                    raise RuntimeError('Keine Anwendung konnte die Datei öffnen. Die Datei liegt unter: ' + str(path))
            except Exception as exception:
                error = str(exception)
        if error:
            if path:
                self.file_monitor.files.pop(Path(path), None)
            self.statusBar().showMessage('Datei konnte nicht geöffnet werden: ' + file.name)
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Critical)
            dialog.setWindowTitle('Datei öffnen fehlgeschlagen')
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText('Die Datei „' + file.name + '“ konnte nicht geöffnet werden.')
            dialog.setInformativeText(error.strip().splitlines()[-1])
            dialog.setDetailedText(error)
            dialog.exec()
            return
        self.statusBar().showMessage('Datei geöffnet: ' + file.name)

    def confirm_edited_file(self, file, path, snapshot, temporary):
        if self._upload_worker is not None or self._delete_worker is not None or self.property_edit_active():
            temporary.cleanup()
            self.file_monitor.retry(path)
            self.file_monitor.busy = False
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Geänderte Datei hochladen')
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f'Die Datei „{file.name}“ wurde geändert. Die aktualisierte Version hochladen?')
        object_name = self.file_monitor.files[path]['object_name']
        dialog.setInformativeText(f'Zielobjekt: {object_name or "Unbekanntes Objekt"}')
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            temporary.cleanup()
            self.file_monitor.busy = False
            return
        self._edited_upload = (path, temporary)
        worker = UploadLoader()
        self._upload_worker = worker
        worker.finished.connect(self.upload_finished)
        self.statusBar().showMessage('Geänderte Datei wird hochgeladen: ' + file.name)
        threading.Thread(target=worker.run, args=(self.api, file.bo_id, [snapshot]), daemon=True).start()

    def repositories_failed(self, details):
        pending_entry = getattr(self, '_open_after_repository_refresh', None)
        if pending_entry is not None:
            self._open_after_repository_refresh = None
            self.open_history_object(pending_entry)
        self.statusBar().showMessage('Ablagen konnten nicht geladen werden.')
        self.reload_repositories_action.setEnabled(True)
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle('Ablagen laden fehlgeschlagen')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText('Ablagen konnten nicht geladen werden.')
        dialog.setInformativeText(details.strip().splitlines()[-1])
        dialog.setDetailedText(details)
        dialog.exec()

    def user_picture_menu(self, *_args):
        if self.api is None or self._picture_worker is not None:
            return
        menu = QMenu(self)
        change = menu.addAction('Benutzerbild ändern …')
        delete = menu.addAction('Benutzerbild löschen')
        menu.addSection('Stellvertreter')
        none = menu.addAction('Keine Stellvertretung')
        none.setToolTip(f'Benutzer-ID: {self.api.main_user_id}' if self.api.main_user_id else '')
        none.setCheckable(True)
        none.setChecked(self.api.selected_stellvertreter_id == -10000)
        delegates = {none: -10000}
        entries = self.api.stellvertreter
        if isinstance(entries, list) and entries:
            for entry in entries:
                label = entry['name']
                action = menu.addAction(label.replace('&', '&&'))
                action.setToolTip(f"Benutzer-ID: {entry['id']}")
                action.setCheckable(True)
                action.setChecked(self.api.selected_stellvertreter_id == entry['id'])
                delegates[action] = entry['id']
        else:
            error = self.api.stellvertreter_error
            label = 'Stellvertreter konnten nicht geladen werden' if isinstance(error, str) and error else 'Keine Stellvertreter vorhanden'
            menu.addAction(label).setEnabled(False)
        menu.setToolTipsVisible(True)
        selected = menu.exec(self.user_button.mapToGlobal(self.user_button.rect().bottomLeft()))
        if selected in delegates:
            windows = [window for window in QApplication.topLevelWidgets()
                       if isinstance(window, Client) and window.api is self.api]
            if any(window.property_edit_active() for window in windows):
                return
            worker = WorkflowWorker()
            self._picture_worker = worker
            self.user_button.setEnabled(False)
            worker.finished.connect(self.stellvertreter_finished)
            self.statusBar().showMessage('Stellvertretung wird gewechselt …')
            threading.Thread(target=worker.run,
                args=(self.api, 'switch_stellvertreter', (delegates[selected],)), daemon=True).start()
            return
        if selected == change:
            path, _ = QFileDialog.getOpenFileName(self, 'Benutzerbild auswählen', '',
                                                'Bilder (*.png *.jpg *.jpeg *.bmp *.gif *.webp)')
            if not path:
                return
            try:
                data = Path(path).read_bytes()
                pixmap = QPixmap()
                if not data or not pixmap.loadFromData(data):
                    raise ValueError('Die Datei enthält kein lesbares Bild.')
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Benutzerbild konnte nicht geladen werden', str(error))
                return
        elif selected == delete:
            data = b''
        else:
            return
        worker = UserPictureWorker()
        self._picture_worker = worker
        self.user_button.setEnabled(False)
        worker.finished.connect(self.user_picture_finished)
        self.statusBar().showMessage('Benutzerbild wird aktualisiert …')
        threading.Thread(target=worker.run, args=(self.api, data), daemon=True).start()

    def stellvertreter_finished(self, result, error):
        self._picture_worker = None
        self.user_button.setEnabled(True)
        if error:
            QMessageBox.warning(self, 'Stellvertreterwechsel fehlgeschlagen', error)
            return
        for window in QApplication.topLevelWidgets():
            if isinstance(window, Client) and window.api is self.api:
                window.display_name = result['name']
                window.user_info_loaded(result['name'])
                window._my_tasks_loaded = False
                window.show_tasks([])
                window.reload_object_tables()
                if result['warnings']:
                    window.statusBar().showMessage('Stellvertretung gewechselt. ' + ' '.join(result['warnings']))

    def user_picture_finished(self, data, error):
        self._picture_worker = None
        self.user_button.setEnabled(self.api is not None)
        if error:
            dialog = QMessageBox(self)
            dialog.setWindowTitle('Benutzerbild konnte nicht aktualisiert werden')
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(error)
            dialog.exec()
            self.statusBar().showMessage('Benutzerbild konnte nicht aktualisiert werden.')
            return
        self.display_user_picture(data)
        self.statusBar().showMessage('Benutzerbild aktualisiert.' if data else 'Benutzerbild gelöscht.')

    def display_user_picture(self, data):
        pixmap = QPixmap()
        if isinstance(data, bytes) and data and pixmap.loadFromData(data):
            self.avatar.setPixmap(QIcon(pixmap).pixmap(QSize(48, 48)))
        else:
            self.avatar.setPixmap(QIcon(str(ICON_DIR / 'user-placeholder.svg')).pixmap(QSize(48, 48)))

    def update_user_button_tooltip(self):
        user_id = self.api.user_id if self.api is not None else None
        lines = [f'Benutzer-ID: {user_id}' if user_id else '',
                 'Klicken um Benutzerbild zu ändern/löschen oder Stellvertretung zu aktivieren/deaktivieren']
        self.user_button.setToolTip('\n'.join(line for line in lines if line))

    def user_info_loaded(self, display_name):
        self.display_user_picture(self.api.user_picture if self.api is not None else b'')
        self.user_name.setText(display_name)
        self.update_user_button_tooltip()
        self.statusBar().showMessage('Angemeldet als ' + display_name)

    def update_breadcrumb(self, item, _previous=None):
        path = []
        while item is not None:
            path.append((item.text(0), item.icon(0),
                         lambda target=item: self.navigate_to(target)))
            item = item.parent()
        self.render_breadcrumb(list(reversed(path)))

    def navigate_content(self, entry, parent_path):
        if self.property_edit_active():
            return
        self.open_history_object(entry)
        path = parent_path + [(entry['name'], object_icon(entry.get('icon_id', 0)),
                               lambda: self.navigate_content(entry, parent_path))]
        self.render_breadcrumb(path)

    BREADCRUMB_BUTTON_WIDTH = 160
    def render_breadcrumb(self, path):
        self._breadcrumb_path = path
        while self.breadcrumb_layout.count():
            widget = self.breadcrumb_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        root = QToolButton()
        root.setText(self.tenant_name or 'MANDANT')
        root.setToolTip('')
        root.setFixedWidth(self.BREADCRUMB_BUTTON_WIDTH)
        root.setIcon(self.windowIcon())
        root.setIconSize(QSize(16, 16))
        root.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        root.setAutoRaise(True)
        root.clicked.connect(lambda: self.navigate_to(self.tree.topLevelItem(0)))
        self.breadcrumb_layout.addWidget(root)
        for name, icon, navigate in path:
            self.breadcrumb_layout.addWidget(QLabel('›'))
            button = QToolButton()
            button.setText(name)
            button.setToolTip(name)
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setAutoRaise(True)
            button.clicked.connect(lambda checked=False, callback=navigate: callback())
            button.setFixedWidth(self.BREADCRUMB_BUTTON_WIDTH)
            self.breadcrumb_layout.addWidget(button)
        self.breadcrumb_layout.addStretch()

    def navigate_to(self, item):
        if item is None:
            return
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self.load_object_files(item)

    def refresh_theme(self):
        icon_directory = ICON_DIR / 'dark' if self.theme.dark else ICON_DIR
        self.center_tabs.setTabIcon(1, QIcon(str(icon_directory / 'ribbon-new-task.svg')))
        self.theme_selector.blockSignals(True)
        self.theme_selector.setCurrentIndex(self.theme_selector.findData(self.theme.mode))
        self.theme_selector.blockSignals(False)
        for button in self.ribbon.findChildren(QToolButton):
            icon_file = button.property('icon_file')
            if icon_file:
                directory = ICON_DIR / 'dark' if self.theme.dark else ICON_DIR
                button.setIcon(QIcon(str(directory / icon_file)))

    def build_ribbon(self):
        groups = [
            [
                ('Navigation', [
                    ('Suchen', 'search', 'ribbon-search.svg')
                ]),
                ('Einstellungen', [
                    ('Stellvertreterverwaltung', 'stellvertreter-management', 'ribbon-stellvertreter.svg'),
                    ('E-Mail-Optionen', 'mail-options', 'ribbon-mail-options.svg'),
                    ('Geschäftsgangmuster-\nVerwaltung', 'workflow-template-management', 'ribbon-workflow-template.svg')
                ]),
                #('Administration', [
                #])
            ],
            [
                ('Zwischenablage', [
                    ('Kopieren', 'copy', 'ribbon-copy.svg'),
                    ('Ausschneiden', None, 'ribbon-cut.svg'),
                    ('Einfügen\nals …', 'paste', 'ribbon-paste.svg')
                ]),
                ('Favorit', [
                    ('Als\nFavorit', 'favorite', 'ribbon-favorite.svg')
                ]),
                ('Ausgabe', [
                    ('Senden', None, 'ribbon-send.svg'),
                    ('Drucken', None, 'ribbon-print.svg'),
                    ('Exportieren', 'export', 'ribbon-export.svg')
                ]),
                ('Status', [
                   ('Bearbeitungs-\nsperre setzen', None, 'ribbon-edit-lock.svg'),
                   ('Abschließen', None, 'ribbon-complete.svg'),
                   ('Zugriffsrechte\nanzeigen', None, 'ribbon-permissions.svg'),
                   ('Entsperren', 'unlock', 'ribbon-edit-lock.svg')
                ]),
                ('Bearbeitungsverlauf', [
                    ('Historie', 'history', 'ribbon-history.svg'),
                    ('Bei Änderung\nbenachrichtigen', None, 'ribbon-notify.svg')
                ]),
                ('Bearbeiten', [
                    ('Umprotokollieren', None, 'ribbon-refile.svg'),
                    ('Spezifische\nInformationen', None, 'ribbon-info.svg'),
                    ('Ausgang\nerstellen', None, 'ribbon-outgoing.svg')
                ]),
                ('Mappe', [
                    ('Mappe\nerstellen', None, 'ribbon-new-vorgang.svg')
                ]),
                ('Öffnen', [
                    ('In neuem\nFenster', 'window', 'ribbon-new-window.svg'),
                    ('Lesen', None, 'ribbon-read.svg')
                ])
            ],
            [
                ('Neu', [
                    ('Neues Objekt', 'new-object', 'ribbon-template.svg')
                ]),
                ('Attribute', [
                    ('Adresse', None, 'ribbon-address.svg'),
                    ('Schlagworte', None, 'ribbon-keywords.svg')
                ]),
                ('Datei', [
                    ('Datei aus\nVorlage', 'file-template', 'ribbon-template.svg'),
                    ('Hochladen', 'upload', 'ribbon-upload.svg'),
                    ('Scannen', None, 'ribbon-scan.svg')
                ]),
                ('Geschäftsgangverfügung', [
                    ('Neue Geschäfts-\ngangverfügung', 'task', 'ribbon-new-task.svg'),
                    ('Neue Wieder-\nvorlage', 'reminder', 'ribbon-reminder.svg'),
                    ('Geschäftsgang-\nmuster hinzufügen', 'template', 'ribbon-workflow-template.svg')
                ])
            ],
        ]
        for page_groups in groups:
            page, row = box(True, 3)
            for group_index, (title, actions) in enumerate(page_groups):
                group, column = box(False, 2)
                buttons, buttons_row = box(True)
                for name, action, icon_file in actions:
                    button = QToolButton()
                    button.setText(name)
                    button.setProperty('icon_file', icon_file)
                    button.setIcon(QIcon(str(ICON_DIR / icon_file)))
                    button.setIconSize(QSize(30, 30))
                    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                    button.setMinimumHeight(74)
                    button.setEnabled(action is not None)
                    if action:
                        button.clicked.connect(lambda checked=False, a=action: self.act(a))
                    else:
                        button.setToolTip('Im Prototyp nicht implementiert')
                    buttons_row.addWidget(button)
                column.addWidget(buttons)
                caption = QLabel(title)
                caption.setObjectName('groupLabel')
                caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
                column.addWidget(caption)
                row.addWidget(group)
                if group_index < len(page_groups) - 1:  # separators only between groups
                    line = QFrame()
                    line.setFrameShape(QFrame.Shape.VLine)
                    row.addWidget(line)
            row.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.ribbon.addWidget(scroll)
        # Reserve room for the tallest page and a horizontal scrollbar so that
        # narrow windows cannot introduce a vertical scroll range.
        self.ribbon.setFixedHeight(max(
            self.ribbon.widget(index).widget().minimumSizeHint().height()
            + self.ribbon.widget(index).horizontalScrollBar().sizeHint().height()
            + 2 * self.ribbon.widget(index).frameWidth()
            for index in range(self.ribbon.count())
        ))

    def sidebar(self):
        panel, layout = box()
        panel.setMinimumWidth(240)
        user, row = box(True, 5)
        # Picture, user name and tenant form one button that opens the user menu.
        self.user_button = LayoutButton()
        self.user_button.setObjectName('userButton')
        self.user_button.setAccessibleName('Benutzermenü')
        self.user_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.user_button.setEnabled(self.api is not None)
        self.user_button.clicked.connect(self.user_picture_menu)
        self.user_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.user_button.customContextMenuRequested.connect(self.user_picture_menu)
        button_row = QHBoxLayout(self.user_button)
        button_row.setContentsMargins(6, 6, 6, 6)
        button_row.setSpacing(12)
        self.avatar = QLabel()
        self.avatar.setObjectName('avatar')
        self.avatar.setFixedSize(48, 48)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setPixmap(QIcon(str(ICON_DIR / 'user-placeholder.svg')).pixmap(QSize(48, 48)))
        button_row.addWidget(self.avatar)
        self.user_name = QLabel('Nicht verbunden')
        self.user_name.setTextFormat(Qt.TextFormat.PlainText)
        self.user_name.setWordWrap(True)
        self.user_name.setStyleSheet('font-size: 20px;')
        identity, identity_layout = box(spacing=3)
        identity_layout.addWidget(self.user_name)
        self.tenant_label = QLabel(self.tenant_name or '')
        self.tenant_label.setTextFormat(Qt.TextFormat.PlainText)
        self.tenant_label.setWordWrap(True)
        self.tenant_label.setVisible(bool(self.tenant_name))
        identity_layout.addWidget(self.tenant_label)
        button_row.addWidget(identity, 1)
        # Clicks and hover go to the button, not to its labels.
        for child in (self.avatar, identity, self.user_name, self.tenant_label):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.update_user_button_tooltip()
        row.addWidget(self.user_button, 1)
        layout.addWidget(user)
        tabs = QTabBar()
        for title in ('Favoriten', 'Aufgaben', 'Ablagen'):
            tabs.addTab(title)
        layout.addWidget(tabs)
        pages = QStackedWidget()
        self.favorites = QTreeWidget()
        self.favorites.setHeaderHidden(True)
        self.favorites.itemClicked.connect(self.activate_favorite)
        self.favorites.itemExpanded.connect(self.refresh_favorites)
        self.favorites.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites.customContextMenuRequested.connect(self.favorites_context_menu)
        task_panel, task_layout = box(False, 6, 5)
        self.task_filter = QLineEdit()
        self.task_filter.setPlaceholderText('Aufgaben filtern')
        self.task_filter.setClearButtonEnabled(True)
        self.task_filter.textChanged.connect(self.filter_my_tasks)
        task_layout.addWidget(self.task_filter)
        self.my_tasks_status = QLabel('')
        self.my_tasks_status.setWordWrap(True)
        self.my_tasks_status.hide()
        task_layout.addWidget(self.my_tasks_status)
        self.tasks = QTreeWidget()
        self.tasks.setHeaderHidden(True)
        self.tasks.setIndentation(17)
        self.tasks.itemClicked.connect(self.activate_my_task)
        task_layout.addWidget(self.tasks)
        reload_tasks = QAction('Aufgaben aktualisieren', self.tasks)
        reload_tasks.triggered.connect(self.load_my_tasks)
        self.tasks.addAction(reload_tasks)
        self.tasks.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self._my_tasks_loading = False
        self._my_tasks_loaded = False
        pages.addWidget(self.favorites)
        pages.addWidget(task_panel)
        storage, column = box(False, 6, 5)
        self.tree_filter = QLineEdit()
        self.tree_filter.setPlaceholderText('Ablagen filtern')
        self.tree_filter.setClearButtonEnabled(True)
        self.tree_filter.textChanged.connect(self.filter_tree)
        column.addWidget(self.tree_filter)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 24)
        self.tree.setIndentation(17)
        self.tree.itemExpanded.connect(self.load_tree_children)
        self.tree.itemClicked.connect(self.load_object_files)
        column.addWidget(self.tree)
        self.reload_repositories_action = QAction('Ablagen neu laden', self.tree)
        self.reload_repositories_action.setEnabled(bool(self.server_url))
        self.reload_repositories_action.triggered.connect(self.load_repositories)
        self.tree.addAction(self.reload_repositories_action)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        pages.addWidget(storage)
        tabs.currentChanged.connect(pages.setCurrentIndex)
        tabs.currentChanged.connect(lambda index: self.load_my_tasks() if index == 1 and not self._my_tasks_loaded else None)
        tabs.currentChanged.connect(lambda index: settings().setValue('sidebar/tab', index))
        saved_tab = settings().value('sidebar/tab', 2, type=int)
        tabs.setCurrentIndex(saved_tab if 0 <= saved_tab < tabs.count() else 2)
        pages.setCurrentIndex(tabs.currentIndex())
        layout.addWidget(pages, 1)
        self.history_list = QListWidget()
        self.history_list.setAccessibleName('Verlauf')
        self.history_list.setMaximumHeight(180)
        self.history_list.itemClicked.connect(self.activate_history)
        history_section = Section('◷  Verlauf', self.history_list)
        history_section.button.setChecked(settings().value('sidebar/history_expanded', True, type=bool))
        history_section.button.toggled.connect(lambda checked: settings().setValue('sidebar/history_expanded', checked))
        layout.addWidget(history_section)
        return panel

    @staticmethod
    def add_node(parent, text, icon_file='dokument.svg'):
        item = QTreeWidgetItem(parent, [text])
        item.setIcon(0, QIcon(str(ICON_DIR / icon_file)))
        item.setToolTip(0, text)
        return item

    def center(self):
        panel, layout = box()
        self.center_tabs = QTabBar()
        self.center_tabs.setObjectName('centerTabs')
        self.center_tabs.setExpanding(True)
        self.center_tabs.setIconSize(QSize(30, 30))
        self.center_tabs.addTab(QIcon(str(ICON_DIR / 'dokument.svg')), 'Objekt')
        self.center_tabs.setTabToolTip(0, '')
        self.center_tabs.addTab('Aufgaben')
        layout.addWidget(self.center_tabs)
        self.center_pages = QStackedWidget()
        self.center_tabs.currentChanged.connect(self.center_pages.setCurrentIndex)
        layout.addWidget(self.center_pages, 1)
        sections = QSplitter(Qt.Orientation.Vertical)
        wrapper, self.content, self.empty = self.table(FILE_COLUMNS, 'Dieses Objekt besitzt keinen Inhalt.')
        self.content.itemDoubleClicked.connect(self.open_content_file)
        self.content.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.content.customContextMenuRequested.connect(self.file_context_menu)
        self.content.file_drop_handler = self.upload_files
        self.content.setAcceptDrops(True)
        self.content.setDragDropMode(QTableWidget.DragDropMode.DropOnly)
        sections.addWidget(Section('Inhalt', wrapper))
        wrapper, self.references, self.references_empty = self.table(
            ['Typ', 'Name', 'Bezugstyp', 'Bemerkung', 'Reihenfolge'], 'Dieses Objekt hat keine Bezüge.')
        self.references.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.references.itemDoubleClicked.connect(self.activate_history)
        sections.addWidget(Section('Bezüge', wrapper))
        wrapper, self.links, self.links_empty = self.table(['Name', 'URL'], '')
        sections.addWidget(Section('Verknüpfungen', wrapper))
        sections.setSizes([225, 225, 190])
        self.center_pages.addWidget(sections)
        wrapper, self.task_table, self.tasks_empty = self.table([label for label, _ in TASK_COLUMNS])
        self.task_table.itemDoubleClicked.connect(self.edit_workflow_task)
        for column, width in enumerate((55, 170, 145, 190, 100, 230, 80, 100, 160, 150, 100, 130, 100, 90, 140, 130)):
            self.task_table.setColumnWidth(column, width)
        task_sections = QSplitter(Qt.Orientation.Vertical)
        task_sections.addWidget(Section('Aufgaben', wrapper))
        wrapper, self.reminder_table, self.reminders_empty = self.table([label for label, _ in REMINDER_COLUMNS])
        for column, width in enumerate((130, 150, 150, 110, 100, 220, 100, 160, 150, 100, 130, 100, 90, 140, 130)):
            self.reminder_table.setColumnWidth(column, width)
        self.reminders_section = Section('Wiedervorlagen (0)', wrapper)
        task_sections.addWidget(self.reminders_section)
        task_sections.setSizes([300, 200])
        self.center_pages.addWidget(task_sections)
        for table in (self.references, self.links, self.task_table, self.reminder_table):
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.customContextMenuRequested.connect(
                lambda position, table=table: self.links_context_menu(position) if table is self.links else self.references_context_menu(position) if table is self.references else self.workflow_context_menu(table, position))
        self.show_tasks([])
        self.show_reminders([])
        return panel

    def show_tasks(self, tasks):
        self._displayed_tasks = tasks
        if hasattr(self, 'quick_tasks_box'):
            self.update_quick_tasks()
        with sorting_suspended(self.task_table):
            self.task_table.setRowCount(len(tasks))
            for row, task in enumerate(tasks):
                for column, (_label, key) in enumerate(TASK_COLUMNS):
                    value = task.get(key, '')
                    cell = SortableItem(value)
                    cell.setToolTip(value)
                    cell.setData(Qt.ItemDataRole.UserRole, task)
                    if key == 'freigabe':
                        cell.setText('')
                        cell.setData(SORT_ROLE, int(value.lower() in ('1', 'true')))
                        cell.setCheckState(Qt.CheckState.Checked if value.lower() in ('1', 'true') else Qt.CheckState.Unchecked)
                        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    elif key == 'state' and task.get('freigabe', '').lower() not in ('1', 'true'):
                        cell.setText('')
                        cell.setData(SORT_ROLE, -1)
                        cell.setToolTip('')
                    elif key == 'state':
                        completed = bool(task.get('erledigt_am'))
                        cell.setText('●')
                        cell.setData(SORT_ROLE, int(completed))
                        cell.setForeground(QColor('#87996b' if completed else '#c68b32'))
                        cell.setToolTip(('Erledigt' if completed else 'Offen') + f' (Status: {value})')
                    elif key == 'zeichnungsfarbe' and value == '-2700':
                        cell.setText('')
                    self.task_table.setItem(row, column, cell)
        self.tasks_empty.setToolTip('')
        self.tasks_empty.setText('Dieses Objekt hat keine Aufgaben.')
        self.tasks_empty.setVisible(not tasks)
        count = sum(not task.get('erledigt_am') for task in tasks)
        description = ('1 offene Geschäftsgangverfügung' if count == 1
                       else f'{count} offene Geschäftsgangverfügungen')
        self.center_tabs.setTabText(1, 'Aufgaben\n' + description)
        self.center_tabs.setTabToolTip(1, description)

    def show_reminders(self, reminders):
        self._displayed_reminders = list(reminders)
        with sorting_suspended(self.reminder_table):
            self.reminder_table.setRowCount(len(reminders))
            for row, reminder in enumerate(reminders):
                for column, (_label, keys) in enumerate(REMINDER_COLUMNS):
                    value = next((reminder[key] for key in keys if reminder.get(key)), '')
                    cell = SortableItem(value)
                    cell.setToolTip(value)
                    cell.setData(Qt.ItemDataRole.UserRole, reminder)
                    if keys[0] == 'state':
                        completed = bool(reminder.get('erledigt_am'))
                        cell.setText('●')
                        cell.setData(SORT_ROLE, int(completed))
                        cell.setForeground(QColor('#87996b' if completed else '#c68b32'))
                        cell.setToolTip(('Erledigt' if completed else 'Offen') + f' (Status: {value})')
                    elif keys[0] == 'zeichnungsfarbe' and value == '-2700':
                        cell.setText('')
                    self.reminder_table.setItem(row, column, cell)
        title = f'Wiedervorlagen ({len(reminders)})'
        button = self.reminders_section.findChild(QPushButton)
        button.setProperty('section_title', title)
        button.setText(('⌄  ' if button.isChecked() else '›  ') + title)
        self.reminders_empty.setText('Dieses Objekt hat keine Wiedervorlagen.')
        self.reminders_empty.setToolTip('')
        self.reminders_empty.setVisible(not reminders)

    def table(self, headers, message=''):
        wrapper, layout = box()
        table = ContentTable(headers)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().hide()
        table.setShowGrid(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if headers[0] == 'Typ':
            table.setColumnWidth(0, 44)
        enable_sorting(table)
        label = QLabel(message)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setObjectName('emptyMessage')
        overlay = QVBoxLayout(table.viewport())
        overlay.setContentsMargins(0, 4, 0, 0)
        overlay.addWidget(label)
        overlay.addStretch()
        label.setVisible(bool(message))
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(table)
        return wrapper, table, label

    def properties(self):
        panel, layout = box()
        panel.setMinimumWidth(270)
        title = QLabel('Eigenschaften')
        title.setFixedHeight(34)
        title.setContentsMargins(8, 0, 0, 0)
        header, buttons = box(True, 0, 0)
        header.setObjectName('propertiesHeader')
        header.setFixedHeight(34)
        buttons.addWidget(title)
        buttons.addStretch()
        self.edit_properties_button = QPushButton('Bearbeiten')
        self.save_properties_button = QPushButton('Speichern')
        self.cancel_properties_button = QPushButton('Abbrechen')
        self.edit_properties_button.clicked.connect(self.begin_property_edit)
        self.save_properties_button.clicked.connect(self.save_property_edit)
        self.cancel_properties_button.clicked.connect(self.cancel_property_edit)
        for button, icon, role in (
                (self.edit_properties_button, 'property-edit.svg', 'edit'),
                (self.save_properties_button, 'property-save.svg', 'commit'),
                (self.cancel_properties_button, 'property-cancel.svg', 'commit')):
            button.setObjectName('propertyAction')
            button.setProperty('role', role)
            button.setIcon(QIcon(str(ICON_DIR / icon)))
            button.setIconSize(QSize(12, 12))
            button.setFixedHeight(28)
            buttons.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(header)
        self.update_property_buttons()
        scroll = vertical_scroll_only(QScrollArea())
        body, column = box(False, 8, 8)
        column.addWidget(QLabel('Metadaten'))
        groups = [
            ('Eingang', [('Name', ''), ('Geschäftszeichen', ''), ('Dokumententyp', 'Sonstige'), ('Kurzbezeichnung', ''), ('Betreff', ''), ('Betreff (Vorgang)', 'Posteingang'), ('Bemerkung', ''), ('Fremd-GZ', ''), ('Barcode', ''), ('Bezugs-GZ', ''), ('Dok.Datum', '08.08.2024'), ('Schlagworte', ''), ('Anlagen', '0')]),
            ('Registratur', [('Ablage', 'Abteilung 2'), ('APL.-Kz.', '0429'), ('Aktenplan', 'LEAP'), ('Aufbewahrung', '10 Jahre')]),
        ]
        for heading, entries in groups:
            widget = QWidget()
            form = QFormLayout(widget)
            form.setContentsMargins(0, 8, 0, 8)
            form.setVerticalSpacing(9)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for name, value in entries:
                if self.server_url:
                    value = ''
                if name == 'Dokumententyp':
                    field = shrinkable_combo(QComboBox())
                    field.addItems(['Sonstige', 'Vereinbarung', 'Schreiben', 'Vermerk'])
                    if self.server_url:
                        field.setCurrentIndex(-1)
                elif name in ('Name', 'Kurzbezeichnung', 'Betreff'):
                    field = QPlainTextEdit(value)
                    field.setFixedHeight(52 if name == 'Betreff' else 42)
                    field.setTabChangesFocus(True)
                else:
                    field = QLineEdit(value)
                    field.setCursorPosition(0)
                field.setMinimumWidth(120)
                field.setToolTip(value)
                self.fields[name] = field
                label = QLabel(name)
                label.setWordWrap(True)
                label.setFixedWidth(96)
                form.addRow(label, field)
            column.addWidget(Section(heading, widget))
        self.fields['Anlagen'].setReadOnly(True)
        column.addStretch()
        scroll.setWidget(body)
        self.properties_scroll = scroll
        self.properties_status = QLabel()
        self.properties_status.setWordWrap(True)
        layout.addWidget(self.properties_status)
        layout.addWidget(scroll)
        self.quick_tasks_box, quick_layout = box(False, 4, 3)
        self.quick_tasks_title = QLabel('Meine aktuellen Aufgaben')
        self.quick_tasks_title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        title_font = self.quick_tasks_title.font()
        title_font.setBold(True)
        self.quick_tasks_title.setFont(title_font)
        quick_layout.addWidget(self.quick_tasks_title)
        self.quick_task_details = QLabel()
        self.quick_task_details.setWordWrap(True)
        self.quick_task_details.setTextFormat(Qt.TextFormat.PlainText)
        self.quick_task_details.setStyleSheet('background: #79983b; color: white; padding: 10px;')
        quick_layout.addWidget(self.quick_task_details)
        self.quick_task_tabs = QTabBar()
        self.quick_task_tabs.setExpanding(False)
        for symbol, label in [('✓', 'Erledigen'), ('✕', 'Ablehnen'), ('→', 'Weiterleiten')]:
            index = self.quick_task_tabs.addTab(symbol)
            self.quick_task_tabs.setTabToolTip(index, label)
        quick_layout.addWidget(self.quick_task_tabs)
        self.quick_redirect = QWidget()
        redirect_form = QFormLayout(self.quick_redirect)
        redirect_form.setContentsMargins(0, 0, 0, 0)
        self.quick_recipient = QPushButton('Empfänger auswählen …')
        self.quick_recipient.setObjectName('quickRecipient')
        self.quick_recipient.clicked.connect(self.choose_quick_recipient)
        self.quick_category = QComboBox()
        self.quick_redirect_task = QLineEdit()
        self.quick_redirect_note = QLineEdit()
        self.quick_due = QDateEdit(QDate.currentDate())
        self.quick_due.setObjectName('quickDue')
        self.quick_due.setDisplayFormat('dd.MM.yyyy')
        self.quick_due.setCalendarPopup(True)
        for label, field in [
            ('Empfänger', self.quick_recipient),
            ('Kategorie', self.quick_category),
            ('Aufgabe', self.quick_redirect_task),
            ('Erledigungsvermerk', self.quick_redirect_note),
            ('Termin', self.quick_due)
        ]:
            redirect_form.addRow(label, field)
        quick_layout.addWidget(self.quick_redirect)
        self.quick_redirect.hide()
        self.quick_task_note = QPlainTextEdit()
        self.quick_task_note.setPlaceholderText('Vermerk')
        self.quick_task_note.setFixedHeight(60)
        quick_layout.addWidget(self.quick_task_note)
        self.quick_task_complete = QPushButton('Erledigen')
        self.quick_task_complete.clicked.connect(self.complete_quick_task)
        self.quick_task_tabs.currentChanged.connect(self.quick_task_action_changed)
        quick_layout.addWidget(self.quick_task_complete, 0, Qt.AlignmentFlag.AlignRight)
        layout.insertWidget(layout.indexOf(scroll), self.quick_tasks_box)
        self.update_quick_tasks()
        return panel

    def update_quick_tasks(self):
        user_id = getattr(self.api, 'selected_stellvertreter_id', -10000)
        if not isinstance(user_id, int) or user_id == -10000:
            user_id = getattr(self.api, 'user_id', None)
        tasks = [task for task in getattr(self, '_displayed_tasks', [])
                 if user_id and task.get('_assignee_id') == str(user_id)
                 and task.get('freigabe', '').lower() in ('1', 'true')
                 and not task.get('erledigt_am') and task.get('ggv_id')]
        self._quick_task = tasks[0] if tasks else None
        self.quick_tasks_title.setText(f'Meine aktuellen Aufgaben ({len(tasks)})')
        self.quick_tasks_box.setVisible(bool(tasks))
        self.show_quick_task()

    def choose_quick_recipient(self):
        entry = self._current_entry
        if not entry or not self._quick_task or self.api is None:
            return
        dialog = UserSelectionDialog(self.api, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selection:
            identifier, name = dialog.selection
            self.quick_recipient.setText(name)
            self.quick_recipient.setProperty('recipient_id', identifier)

    def quick_task_action_changed(self, index):
        self.quick_redirect.setVisible(index == 2)
        self.quick_task_note.setVisible(index != 2)
        self.quick_task_complete.setText('Weiterleiten' if index == 2 else 'Ablehnen' if index == 1 else 'Erledigen')
        if index == 2 and not self._quick_categories_loaded:
            entry = self._current_entry
            if self.api is not None and entry and entry.get('object_kind') is not None and self._quick_task:
                if not self.property_edit_active():
                    self.run_property_operation('task_categories',
                        (entry['object_kind'], self._quick_task))

    def show_quick_task(self, *_args):
        self.quick_task_tabs.setCurrentIndex(0)
        task = self._quick_task or {}
        self.quick_recipient.setText('Empfänger auswählen …')
        self.quick_recipient.setProperty('recipient_id', None)
        self.quick_category.clear()
        self._quick_categories_loaded = False
        self.quick_redirect_task.setText(task.get('aufgabe', ''))
        self.quick_redirect_note.clear()
        due = QDate.fromString(task.get('termin', ''), 'dd.MM.yyyy')
        self.quick_due.setDate(due if due.isValid() else QDate.currentDate())
        self.quick_task_details.setText('\n'.join(filter(None, [
            str(task.get('erlassen_von_id'))+' ('+str(task.get('angelegt_am'))+')',
            task.get('kategorie'),
            task.get('aufgabe'),
            'Fällig am: ' + task['termin'] if task.get('termin') else ''
        ])))
        self.quick_task_note.setPlainText(task.get('erledigung', ''))

    def complete_quick_task(self):
        task = self._quick_task
        entry = self._current_entry
        if self.api is None or not task or not entry or entry.get('object_kind') is None:
            return
        if self.property_edit_active():
            return
        if self.quick_task_tabs.currentIndex() == 2:
            recipient = self.quick_recipient.property('recipient_id')
            if not recipient or self.quick_category.currentData() is None:
                QMessageBox.warning(self, 'Weiterleiten', 'Bitte Empfänger und Kategorie auswählen.')
                return
            self.run_property_operation('redirect_task',
                (entry['id'], entry['object_kind'], task['ggv_id'], self.quick_redirect_note.text(),
                 {'recipient_id': recipient, 'recipient_name': self.quick_recipient.text(),
                  'category': self.quick_category.currentData(), 'task': self.quick_redirect_task.text(),
                  'due': self.quick_due.date().toString('dd.MM.yyyy')}))
            return
        self.run_property_operation('reject_task' if self.quick_task_tabs.currentIndex() == 1 else 'complete_task',
            (entry['id'], entry['object_kind'], task['ggv_id'], self.quick_task_note.toPlainText()))

    def property_edit_active(self):
        active = self._property_edit is not None or self._property_worker is not None
        if active:
            self.statusBar().showMessage('Bitte Eigenschaften zuerst speichern oder abbrechen.')
        return active

    def update_property_buttons(self):
        editing = self._property_edit is not None
        busy = self._property_worker is not None
        self.edit_properties_button.setVisible(not editing)
        self.edit_properties_button.setEnabled(not busy and self.api is not None
                                              and bool(self._current_entry)
                                              and self._current_entry.get('object_kind') is not None)
        for button in (self.save_properties_button, self.cancel_properties_button):
            button.setVisible(editing)
            button.setEnabled(not busy)
        if hasattr(self, 'quick_tasks_box'):
            self.quick_tasks_box.setEnabled(not busy and not editing)
        if hasattr(self, 'properties_scroll'):
            self.properties_scroll.setEnabled(not busy)

    def run_property_operation(self, action, args):
        worker = PropertyEditWorker()
        self._property_worker = worker
        worker.finished.connect(self.property_operation_finished)
        self.update_property_buttons()
        threading.Thread(target=worker.run, args=(self.api, action, args), daemon=True).start()

    def create_workflow_task(self, action='new_task', extra_args=()):
        entry = self._current_entry
        if self.api is None or not entry or entry.get('object_kind') is None:
            self.statusBar().showMessage('Bitte zuerst ein VIS-Objekt auswählen.')
            return
        if self._property_worker is not None:
            return
        if self._property_edit is None:
            self._property_original = self._property_attributes
            self._original_tasks = list(self._displayed_tasks)
            self._original_reminders = list(self._displayed_reminders)
            self._original_links = self.current_links()
            self._original_references = list(getattr(self, '_displayed_references', []))
        # Adding another task must not discard unsaved metadata in the same session.
        self._workflow_property_values = {}
        if self._property_edit is not None:
            for key, field in self._property_widgets.items():
                self._workflow_property_values[key] = (
                    field.isChecked() if isinstance(field, QCheckBox) else
                    field.currentText() if isinstance(field, QComboBox) else
                    field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text())
        self.run_property_operation(action, (entry['id'], entry['object_kind'], self._property_edit) + extra_args)

    def edit_workflow_task(self, item):
        if self._property_worker is not None:
            return
        task = item.data(Qt.ItemDataRole.UserRole)
        if not task or task.get('erledigt_am'):
            self.statusBar().showMessage('Nur offene Geschäftsgangverfügungen können bearbeitet werden.')
            return
        if self._property_edit is None:
            if task.get('ggv_id'):
                self.create_workflow_task('prepare_task', (task['ggv_id'],))
            return
        if task.get('_session_index') is None:
            return
        self.run_property_operation('open_task', (self._property_edit, task['_session_index']))

    def begin_property_edit(self):
        entry = self._current_entry
        if self.api is None or not entry or entry.get('object_kind') is None or self.property_edit_active():
            return
        self._property_original = self._property_attributes
        self._original_links = self.current_links()
        self._original_references = list(getattr(self, '_displayed_references', []))
        self._original_tasks = list(self._displayed_tasks)
        self._original_reminders = list(self._displayed_reminders)
        self.run_property_operation('begin', (entry['id'], entry['object_kind']))

    def save_property_edit(self):
        if self._property_edit is None or self._property_worker is not None:
            return
        changes = {}
        for attribute in self._property_attributes:
            identifier = attribute['identifier']
            field = self._property_widgets.get(identifier)
            if field is None or attribute['behavior'] != '1':
                continue
            value = property_field_change(field, attribute)
            if value is not None:
                changes[identifier] = value
        self.run_property_operation('save', (self._property_edit['session_id'], changes))

    def cancel_property_edit(self):
        if self._property_edit is not None and self._property_worker is None:
            self.run_property_operation('cancel', (self._property_edit['session_id'],))

    def property_operation_finished(self, action, result, error):
        self._property_worker = None
        if error:
            self.properties_status.clear()
            self.statusBar().showMessage('Eigenschaften-Befehl fehlgeschlagen.')
        elif action == 'task_categories':
            self.quick_category.clear()
            choices = result.get('choice_ids', {})
            for label in dict.fromkeys(result['choices'] + [result['value']]):
                identifier = choices.get(label) or (result.get('idvalue') if label == result['value'] else None)
                if identifier is not None:
                    self.quick_category.addItem(label, identifier)
            current = self.quick_category.findData(result.get('idvalue'))
            if current >= 0:
                self.quick_category.setCurrentIndex(current)
            self._quick_categories_loaded = True
        elif action in ('complete_task', 'reject_task', 'redirect_task'):
            self.show_tasks([])
            self.reload_object_tables()
            self._my_tasks_loaded = False
            self.statusBar().showMessage('Aufgabe weitergeleitet.' if action == 'redirect_task' else 'Aufgabe abgelehnt.' if action == 'reject_task' else 'Aufgabe erledigt.')
        elif action == 'unlock':
            self.statusBar().showMessage('Objekt entsperrt.')
            self.reload_object_tables()
        elif action == 'open_link':
            dialog = LinkDialog(self.api, result, self)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            state = dialog.result_state
            if accepted:
                self.property_operation_finished('new_link', state, '')
            elif state is not None and not getattr(self, '_link_session_was_open', True):
                self._property_edit = state
                self.run_property_operation('cancel', (state['session_id'],))
            elif state is not None:
                self._property_edit = state
        elif action == 'open_template':
            dialog = WorkflowTemplateDialog(self.api, result, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.property_operation_finished('new_task', dialog.result_state, '')
        elif action == 'prepare_task':
            self.property_operation_finished('new_task', result['state'], '')
            self.run_property_operation('open_task', (result['state'], result['index']))
        elif action == 'open_task':
            dialog = WorkflowDialog(self.api, result, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                for task in self._property_edit['tasks']:
                    if int(task['_session_index']) == result['index']:
                        for key, (value, _idvalue) in dialog.changes.items():
                            task[key] = value.split(';')[2] if key == 'erlassen_fuer_id' and value.startswith('--;') else value
                self.show_tasks(self._property_edit['tasks'])
        elif action in ('new_task', 'new_reminder', 'new_link', 'delete_link', 'delete_references', 'delete_task', 'delete_reminder',
                        'task_command'):
            self._property_edit = result
            self.show_properties(result['attributes'])
            for key, value in getattr(self, '_workflow_property_values', {}).items():
                field = self._property_widgets.get(key)
                if isinstance(field, QCheckBox):
                    field.setChecked(value)
                elif isinstance(field, QComboBox):
                    field.setCurrentText(value)
                elif isinstance(field, QPlainTextEdit):
                    field.setPlainText(value)
                elif isinstance(field, QLineEdit):
                    field.setText(value)
            self.show_tasks(result.get('tasks', self._displayed_tasks))
            if 'reminders' in result:
                self.show_reminders(result['reminders'])
            if 'links' in result:
                self.show_links(result['links'])
            if 'references' in result:
                self.show_references(result['references'])
            if action in ('delete_task', 'delete_reminder'):
                self.statusBar().showMessage('Eintrag entfernt. Bitte speichern, um die Änderung zu übernehmen.')
            elif action == 'task_command':
                self.statusBar().showMessage('Geschäftsgangverfügungen geändert. Bitte speichern, um die Änderung zu übernehmen.')
            elif action == 'delete_references':
                self.statusBar().showMessage('Bezüge entfernt. Bitte speichern, um die Änderung zu übernehmen.')
            elif action == 'new_link':
                self.statusBar().showMessage('Verknüpfung hinzugefügt. Bitte speichern, um die Änderung zu übernehmen.')
            elif action == 'delete_link':
                self.statusBar().showMessage('Verknüpfung entfernt. Bitte speichern, um die Änderung zu übernehmen.')
            else:
                self.center_tabs.setCurrentIndex(1)
        elif action == 'begin':
            self.show_tasks(result.get('tasks', self._displayed_tasks))
            self.show_reminders(result.get('reminders', self._displayed_reminders))
            self._property_edit = result
            self.show_properties(result['attributes'])
        else:
            if action == 'cancel' and hasattr(self, '_original_links'):
                self.show_links(self._original_links)
                self.show_references(self._original_references)
            if action == 'cancel' and hasattr(self, '_original_tasks'):
                self.show_tasks(self._original_tasks)
                self.show_reminders(self._original_reminders)
            self._property_edit = None
            self.show_properties(self._property_original if action == 'cancel' else self._property_attributes)
            self.reload_object_tables()
        self.update_property_buttons()

    def show_command_message(self, text, message_type):
        # VIS message types: 1 = information, 3 = error, others = warning.
        icon, title = {'1': (QMessageBox.Icon.Information, 'Hinweis'),
                       '3': (QMessageBox.Icon.Critical, 'Befehl fehlgeschlagen')}.get(
                           message_type, (QMessageBox.Icon.Warning, 'Warnung'))
        dialog = QMessageBox(self)
        dialog.setIcon(icon)
        dialog.setWindowTitle(title)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._command_message_dialogs.append(dialog)
        def finished(_result):
            self._command_message_dialogs.remove(dialog)
            dialog.deleteLater()
        dialog.finished.connect(finished)
        dialog.open()

    def closeEvent(self, event):
        if self.property_edit_active() or self._upload_worker is not None or self.file_monitor.busy:
            event.ignore()
        else:
            self.file_monitor.timer.stop()
            super().closeEvent(event)

    def show_properties(self, attributes):
        """Render server values in the groups used by the VIS properties pane."""
        self._property_attributes = attributes
        self.fields = {}
        self._property_widgets = {}
        self._server_property_names = {a['name'] for a in attributes}
        self.properties_status.setToolTip('')
        self.properties_status.setText('' if attributes else 'Keine Eigenschaften verfügbar.')
        body, column = box(False, 8, 8)
        values = {attribute['identifier']: attribute for attribute in attributes}
        kind = values.get('objektart_id', {}).get('value', '')
        heading = {'1': 'Akte', '2': 'Ablage', '3': 'Vorgang', '14': 'Dokument'}.get(kind, 'Objekt')
        main_names = ['Name', 'Geschäftszeichen', 'Aktentyp', 'Vorgangstyp', 'Dokumententyp',
                      'Kurzbezeichnung', 'Betreff', 'Betreff (Akte)', 'Betreff (Vorgang)',
                      'Fremd-GZ', 'Dringlich', 'Status', 'Bemerkung', 'Barcode', 'Bezugs-GZ',
                      'Dok.Datum', 'Schlagworte', 'Anlagen', 'Altes GZ']
        registry_ids = ['pool_id', 'aktpl1_schl', 'katalog1_id', 'aktenplanbetreff',
                        'standort', 'medium', 'akte_nr', 'z2int', 'aktpl_nr', 'lfnd_nr',
                        'laufzeit_von', 'laufzeit_bis', 'aufbewahrfrist', 'aussondstatus',
                        'aussonderungsart', 'aussonderung_am', 'transferfrist', 'transfer_am']
        audit_ids = ['erzeugt_am', 'erzeugt_von', 'geaendert_am', 'geaendert_von']
        visible = [a for a in attributes if a['behavior'] != '4' and
                   a['identifier'] not in {'objektart_id', 'objekticon_id', 'objekttyp_id',
                                           'aktpl1_id', 'uablage_id', 'obj_hierarchie', 'guid'}
                   and not a['name'].startswith('Reserve')]
        main = sorted((a for a in visible if a['name'] in main_names),
                      key=lambda a: main_names.index(a['name']))
        registry = [values[key] for key in registry_ids if key in values and values[key] in visible]
        audit = [values[key] for key in audit_ids if key in values and values[key] in visible]
        other = [a for a in visible if a not in main + registry + audit]
        # Keep a small, blank placeholder while the asynchronous response is pending.
        if not attributes:
            main = [dict(name=name, value='', draw_type='2' if name == 'Name' else '1', choices=[])
                    for name in ('Name', 'Anlagen')]
        for title, entries in [(heading, main), ('Registratur', registry),
                               ('Weitere Eigenschaften', other), ('Bearbeitung', audit)]:
            if not entries:
                continue
            widget = QWidget()
            form = QFormLayout(widget)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for attribute in entries:
                name, value = attribute['name'], attribute['value']
                field = property_field(attribute)
                identifier = attribute.get('identifier')
                writable = self._property_edit is not None and attribute.get('behavior') == '1'
                if isinstance(field, (QCheckBox, QComboBox)):
                    field.setEnabled(writable)
                else:
                    field.setReadOnly(not writable)
                if identifier:
                    self._property_widgets[identifier] = field
                field.setToolTip(value)
                self.fields[name] = field
                label = QLabel(name)
                label.setWordWrap(True)
                label.setFixedWidth(96)
                form.addRow(label, field)
            column.addWidget(Section(title, widget))
        column.addStretch()
        self.properties_scroll.setWidget(body)
        self.update_property_buttons()

    def eventFilter(self, watched, event):
        popup = getattr(self, 'search_popup', None)
        if (popup is not None and watched is self.search
                and event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress)
                and self.search.text().strip() and self.api is not None):
            if self._search_ready:
                self.show_search_popup()
            elif not self.search_timer.isActive():
                self.search_timer.start()
        if popup is not None and popup.isVisible():
            escape = event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
            outside = (event.type() == QEvent.Type.MouseButtonPress
                       and isinstance(watched, QWidget)
                       and watched is not self.search and not self.search.isAncestorOf(watched)
                       and watched is not popup and not popup.isAncestorOf(watched))
            if escape or outside:
                self._search_token += 1
                self.search_timer.stop()
                popup.hide()
                if escape:
                    return True
        return super().eventFilter(watched, event)

    def search_changed(self, text):
        self._search_ready = False
        self._search_token += 1
        self.search_timer.stop()
        self.search_results.clear()
        self.search_popup.hide()
        if text.strip() and self.api is not None:
            self.search_timer.start()

    def show_search_popup(self):
        self.search_popup.move(self.search.mapToGlobal(QPoint(0, self.search.height())))
        self.search_popup.resize(self.search.width(), min(400, max(90, 50 + self.search_results.count() * 26)))
        self.search_popup.show()

    def start_search(self):
        if self.api is None or not self.search.text().strip():
            return
        token = self._search_token
        worker = SearchWorker()
        self._search_jobs[token] = worker
        worker.finished.connect(self.search_finished)
        self.search_status.setText('Suche läuft …')
        self.show_search_popup()
        threading.Thread(target=worker.run, args=(self.api, self.search.text().strip(), token), daemon=True).start()

    def search_finished(self, token, result, error):
        self._search_jobs.pop(token, None)
        if token != self._search_token or not self.search.text().strip():
            return
        self.search_results.clear()
        if error:
            self.search_status.setText('Suche fehlgeschlagen: ' + error)
        else:
            self._search_ready = True
            entries, total = result
            self.search_status.setText(f'{len(entries)} von {total} Treffern')
            best = max(entries, key=lambda entry: entry['score']) if entries else None
            groups = {}
            for entry in entries:
                group = ('Höchste Übereinstimmung' if entry is best else
                         {12: 'Eingängen', 14: 'Internen Schreiben', 15: 'Ausgängen',
                          1: 'Akten', 3: 'Vorgängen'}.get(entry['object_kind'], 'Objekten'))
                groups.setdefault(group, []).append(entry)
            order = ['Höchste Übereinstimmung', 'Eingängen', 'Internen Schreiben', 'Ausgängen', 'Akten', 'Vorgängen', 'Objekten']
            for group in order:
                if group not in groups:
                    continue
                heading = QListWidgetItem(f'In {group} ({len(groups[group])})')
                font = heading.font()
                font.setBold(True)
                heading.setFont(font)
                heading.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.search_results.addItem(heading)
                for entry in groups[group]:
                    item = QListWidgetItem(object_icon(entry['icon_id']), entry['name'])
                    item.setToolTip(entry['name'])
                    item.setData(Qt.ItemDataRole.UserRole, entry)
                    self.search_results.addItem(item)
        self.show_search_popup()

    def open_search_result(self, item):
        if not item.data(Qt.ItemDataRole.UserRole):
            return
        if self.property_edit_active():
            return
        self._search_token += 1
        self.search_timer.stop()
        self.search_popup.hide()
        self.activate_history(item)

    def filter_tree(self, _text):
        if not hasattr(self, 'tree'):
            return
        terms = self.tree_filter.text().casefold().split()
        def visit(item):
            children = [visit(item.child(i)) for i in range(item.childCount())]
            matches = all(term in item.text(0).casefold() for term in terms) or any(children)
            item.setHidden(not matches)
            return matches
        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def metadata(self):
        values = {}
        for name, field in self.fields.items():
            if isinstance(field, QCheckBox):
                values[name] = field.isChecked()
            elif isinstance(field, QComboBox):
                values[name] = field.currentText()
            elif isinstance(field, QPlainTextEdit):
                values[name] = field.toPlainText()
            else:
                values[name] = field.text()
        values['Dateianhänge'] = list(self.attachments)
        return values

    def reload_object_tables(self):
        if self.property_edit_active():
            return
        entry = self._current_entry
        if self.api is None or entry is None:
            return
        self.refresh_current_files(entry['id'])
        if entry.get('object_kind') is not None:
            token = self._file_token
            worker = LinkLoader()
            self._link_jobs[token] = worker
            worker.finished.connect(self.links_finished)
            threading.Thread(target=worker.run,
                             args=(self.api, entry['id'], entry['object_kind'], token), daemon=True).start()
        self.statusBar().showMessage('Objektdaten werden neu geladen …')

    def table_reload_menu(self, table, position):
        menu = QMenu(self)
        action = menu.addAction('Neu laden')
        action.setEnabled(self.api is not None and self._current_entry is not None)
        if menu.exec(table.viewport().mapToGlobal(position)) == action:
            self.reload_object_tables()

    def file_context_menu(self, position):
        item = self.content.itemAt(position)
        if self.api is None or item is None or not isinstance(item.data(Qt.ItemDataRole.UserRole), ObjectFile):
            self.table_reload_menu(self.content, position)
            return
        if not item.isSelected():
            self.content.clearSelection()
            self.content.selectRow(item.row())
        files = [self.content.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                 for index in self.content.selectionModel().selectedRows()]
        if not files or any(not isinstance(file, ObjectFile) for file in files):
            self.table_reload_menu(self.content, position)
            return
        menu = QMenu(self)
        delete = menu.addAction('Datei löschen' if len(files) == 1 else 'Dateien löschen')
        delete.setEnabled(self._delete_worker is None and self._upload_worker is None
                          and bool(self._current_entry)
                          and self._current_entry.get('object_kind') is not None)
        rename = menu.addAction('Datei umbenennen …')
        rename.setEnabled(delete.isEnabled() and len(files) == 1)
        download = menu.addAction('Datei herunterladen …')
        download.setEnabled(len(files) == 1)
        menu.addSeparator()
        reload_action = menu.addAction('Neu laden')
        reload_action.setEnabled(self.api is not None and self._current_entry is not None)
        selected = menu.exec(self.content.viewport().mapToGlobal(position))
        if selected == reload_action:
            self.reload_object_tables()
        elif selected == delete:
            self.delete_files(files)
        elif selected == rename:
            self.rename_file(files[0])
        elif selected == download:
            self.save_content_file(files[0])

    def save_content_file(self, file):
        if self.api is None:
            return
        filename = Path(file.name.replace('\\', '/')).name
        destination, _ = QFileDialog.getSaveFileName(self, 'Datei herunterladen', filename, 'Alle Dateien (*)')
        if not destination:
            return
        self._download_token += 1
        token = self._download_token
        worker = SaveFileLoader()
        self._save_jobs[token] = worker
        worker.finished.connect(self.save_file_finished)
        self.statusBar().showMessage('Datei wird heruntergeladen: ' + file.name)
        threading.Thread(target=worker.run, args=(self.api, file, destination, token), daemon=True).start()

    def save_file_finished(self, token, path, error):
        if self._save_jobs.pop(token, None) is None:
            return
        if error:
            self.statusBar().showMessage('Datei konnte nicht gespeichert werden.')
            dialog = QMessageBox(self)
            dialog.setWindowTitle('Download fehlgeschlagen')
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(error)
            dialog.exec()
            return
        self.statusBar().showMessage('Datei gespeichert: ' + str(path))

    def rename_file(self, file):
        entry = self._current_entry
        if (self.api is None or not entry or entry.get('object_kind') is None
                or entry['id'] != file.bo_id or self._delete_worker is not None or self._upload_worker is not None):
            return
        name, accepted = QInputDialog.getText(self, 'Datei umbenennen',
                                             'Neuer Dateiname (ohne Erweiterung):', text=Path(file.name).stem)
        if not accepted or name == Path(file.name).stem:
            return
        worker = FileRenameWorker()
        self._delete_worker = worker
        worker.finished.connect(self.file_rename_finished)
        self.statusBar().showMessage('Datei wird umbenannt …')
        threading.Thread(target=worker.run, args=(self.api, entry['object_kind'], file, name), daemon=True).start()

    def file_rename_finished(self, file, error):
        self._delete_worker = None
        if error:
            dialog = QMessageBox(self)
            dialog.setWindowTitle('Umbenennen fehlgeschlagen')
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(error)
            dialog.exec()
            self.statusBar().showMessage('Datei konnte nicht umbenannt werden.')
            return
        self.refresh_current_files(file.bo_id)
        self.statusBar().showMessage('Datei umbenannt.')

    def delete_files(self, files):
        entry = self._current_entry
        if (self.api is None or not entry or entry.get('object_kind') is None
                or self._delete_worker is not None or self._upload_worker is not None):
            return
        worker = FileDeletionWorker()
        self._delete_worker = worker
        worker.finished.connect(self.file_deletion_prepared)
        self.statusBar().showMessage('Löschbestätigung wird geladen …')
        threading.Thread(target=worker.run,
                         args=(self.api, (entry['id'], entry['object_kind'], files)), daemon=True).start()

    def file_deletion_prepared(self, request, error):
        if error:
            self.file_deletion_finished(None, error)
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Dateien löschen')
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(request['message'])
        dialog.setInformativeText('\n'.join(request['names']))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            request = dict(request, cancelled=True)
        worker = FileDeletionWorker()
        self._delete_worker = worker
        worker.finished.connect(self.file_deletion_finished)
        self.statusBar().showMessage('Löschen wird abgebrochen …' if request.get('cancelled')
                                     else 'Dateien werden gelöscht …')
        threading.Thread(target=worker.run, args=(self.api, request, True), daemon=True).start()

    def file_deletion_finished(self, request, error):
        self._delete_worker = None
        if error:
            self.statusBar().showMessage('Dateien konnten nicht gelöscht werden.')
            dialog = QMessageBox(self)
            dialog.setWindowTitle('Löschen fehlgeschlagen')
            dialog.setIcon(QMessageBox.Icon.Critical)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(error)
            dialog.exec()
            return
        if request.get('cancelled'):
            self.statusBar().showMessage('Löschen abgebrochen.')
            return
        self.refresh_current_files(request['object_id'])
        self.statusBar().showMessage(f"{len(request['names'])} Dateien gelöscht.")

    def refresh_current_files(self, object_id):
        if self._current_entry and self._current_entry['id'] == object_id:
            self._file_token += 1
            token = self._file_token
            worker = FileLoader()
            self._file_jobs[token] = worker
            worker.finished.connect(self.object_files_finished)
            threading.Thread(target=worker.run, args=(self.api, object_id, token), daemon=True).start()

    def upload_finished(self, object_id, uploaded, error):
        self._upload_worker = None
        if self._edited_upload is not None:
            path, temporary = self._edited_upload
            temporary.cleanup()
            self._edited_upload = None
            if error:
                self.file_monitor.retry(path)
        if uploaded:
            self.refresh_current_files(object_id)
        self.statusBar().showMessage(f'{len(uploaded)} Dateien hochgeladen.')
        if error:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle('Upload fehlgeschlagen')
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(error)
            dialog.exec()
        self.file_monitor.busy = False

    def add_attachment(self, path):
        file = Path(path)
        size = file.stat().st_size
        row = self.content.rowCount()
        with sorting_suspended(self.content):
            self.content.insertRow(row)
            for col, value in enumerate([file.suffix.lstrip('.').upper(), 'Original', '1', file.name, f'{size / 1024:.1f} KB', 'Heute', 'Benutzername', 'Heute']):
                self.content.setItem(row, col, SortableItem(value))
            self.content.item(row, 4).setData(SORT_ROLE, size)
        self.attachments.append(str(file.resolve()))
        self.empty.hide()
        if 'Anlagen' in self.fields:
            self.fields['Anlagen'].setText(str(len(self.attachments)))

    def can_upload_files(self):
        if self._delete_worker is not None:
            self.statusBar().showMessage('Ein Löschvorgang läuft bereits.')
            return False
        if self._upload_worker is not None:
            self.statusBar().showMessage('Ein Upload läuft bereits.')
            return False
        if self.api is not None and (not self._current_entry or self._current_entry.get('repository')):
            self.statusBar().showMessage('Bitte zuerst ein VIS-Objekt für den Upload auswählen.')
            return False
        return True

    def upload_files(self, paths):
        if not paths or not self.can_upload_files():
            return False
        if self.api is not None:
            worker = UploadLoader()
            self._upload_worker = worker
            worker.finished.connect(self.upload_finished)
            self.statusBar().showMessage('Dateien werden hochgeladen …')
            threading.Thread(target=worker.run,
                             args=(self.api, self._current_entry['id'], paths), daemon=True).start()
            return True
        for path in paths:
            try:
                self.add_attachment(path)
            except OSError as error:
                QMessageBox.warning(self, 'Datei nicht verfügbar', str(error))
        return True

    def act(self, action):
        if action == 'stellvertreter-management':
            if self.api is not None:
                StellvertreterManagementDialog(self.api, self).exec()
        elif action == 'mail-options':
            if self.api is not None:
                MailOptionsDialog(self.api, self).exec()
        elif action == 'workflow-template-management':
            if self.api is not None:
                WorkflowTemplateManagementDialog(self.api, self).exec()
        elif action == 'new-object':
            if self.api is None or not self._current_entry or self._current_entry.get('object_kind') is None:
                self.statusBar().showMessage('Bitte zuerst einen Speicherort auswählen.')
            elif not self.property_edit_active():
                dialog = NewObjectDialog(self.api, self._current_entry, self)
                if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_entry:
                    self._open_after_repository_refresh = dialog.created_entry
                    self.load_repositories()
        elif action == 'history':
            if not self._current_entry:
                self.statusBar().showMessage('Bitte zuerst ein VIS-Objekt auswählen.')
            elif self._object_history is None:
                self.statusBar().showMessage('Historie ist noch nicht geladen. Bitte gegebenenfalls das Objekt neu laden.')
            else:
                ObjectHistoryDialog(self._object_history, self).exec()
        elif action == 'copy':
            entry = self._current_entry
            if self.api is None or not entry or entry.get('repository') or entry.get('object_kind') is None:
                self.statusBar().showMessage('Bitte zuerst ein VIS-Objekt auswählen.')
            else:
                self._clipboard_entry = dict(entry)
                self.statusBar().showMessage('Kopiert: ' + entry.get('name', ''))
        elif action == 'paste':
            entry, source = self._current_entry, getattr(self, '_clipboard_entry', None)
            if self.api is None or not entry or entry.get('repository') or entry.get('object_kind') is None:
                self.statusBar().showMessage('Bitte zuerst das Zielobjekt auswählen.')
            elif source is None:
                self.statusBar().showMessage('Bitte zuerst ein Objekt kopieren.')
            elif source['id'] == entry['id']:
                self.statusBar().showMessage('Ein Objekt kann nicht in sich selbst eingefügt werden.')
            elif not self.property_edit_active():
                dialog = PasteDialog(self.api, source, entry, self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self.reload_object_tables()
                    self.statusBar().showMessage('Bezug angelegt: ' + source.get('name', ''))
        elif action == 'file-template':
            entry = self._current_entry
            if self.api is None or not entry or entry.get('repository') or entry.get('object_kind') is None:
                self.statusBar().showMessage('Bitte zuerst ein VIS-Objekt auswählen.')
            else:
                dialog = FileTemplateDialog(self.api, entry['id'], entry['object_kind'], self)
                if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_file:
                    self.refresh_current_files(entry['id'])
                    self.statusBar().showMessage('Datei angelegt: ' + dialog.created_file)
        elif action == 'upload':
            if not self.can_upload_files():
                return
            paths, _ = QFileDialog.getOpenFileNames(self, 'Dateien als Anlagen hinzufügen')
            self.upload_files(paths)
        elif action == 'export':
            path, _ = QFileDialog.getSaveFileName(self, 'Metadaten exportieren', 'dokument.json', 'JSON (*.json)')
            if path:
                try:
                    Path(path).write_text(json.dumps(self.metadata(), ensure_ascii=False, indent=2), encoding='utf-8')
                    self.statusBar().showMessage('Metadaten gespeichert: ' + path)
                except OSError as error:
                    QMessageBox.warning(self, 'Speichern fehlgeschlagen', str(error))
        elif action == 'favorite':
            self.add_favorite()
        elif action == 'search':
            self.search.setFocus()
        elif action == 'unlock':
            entry = self._current_entry
            if self.api is None or not entry or entry.get('object_kind') is None:
                self.statusBar().showMessage('Bitte zuerst ein VIS-Objekt auswählen.')
                return
            if self.property_edit_active():
                return
            self.run_property_operation('unlock', (entry['id'], entry['object_kind']))
            self.statusBar().showMessage('Objekt wird entsperrt …')
        elif action == 'task':
            self.create_workflow_task()
        elif action == 'template':
            self.create_workflow_task('open_template')
        elif action == 'reminder':
            self.create_workflow_task('new_reminder')
        elif action == 'tasks':
            self.center_view.setCurrentIndex(1)
            self.center_tabs.setCurrentIndex(1)
        elif action == 'window':
            if not hasattr(self, 'windows'):
                self.windows = []
            window = Client(self.server_url, self.display_name, api=self.api, history_store=self.history_store,
                            tenant_name=self.tenant_name, load_repositories_on_start=False)
            window.refresh_favorites()
            for index in range(self.tree.topLevelItemCount()):
                window.tree.addTopLevelItem(self.tree.topLevelItem(index).clone())
            pending = [window.tree.topLevelItem(i) for i in range(window.tree.topLevelItemCount())]
            while pending:
                node = pending.pop()
                # In-flight requests belong to the original window; allow retries here.
                if node.data(0, Qt.ItemDataRole.UserRole + 1) == 'loading':
                    node.setData(0, Qt.ItemDataRole.UserRole + 1, None)
                pending.extend(node.child(i) for i in range(node.childCount()))
            if self._current_entry is not None:
                selection = QListWidgetItem()
                selection.setData(Qt.ItemDataRole.UserRole, dict(self._current_entry))
                window.activate_history(selection)
            elif self.tree.currentItem() is not None:
                source = self.tree.currentItem()
                indices = []
                while source.parent() is not None:
                    indices.append(source.parent().indexOfChild(source))
                    source = source.parent()
                target = window.tree.topLevelItem(self.tree.indexOfTopLevelItem(source))
                for index in reversed(indices):
                    target = target.child(index)
                window.navigate_to(target)
            if window.tree.topLevelItemCount() == 0 and self._current_entry is None:
                window.load_repositories()
            self.windows.append(window)
            window.show()


STYLE = '''
QWidget { font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 12px; color: palette(window-text); background: palette(window); }
QMenu { background: palette(base); border: 1px solid palette(mid); padding: 4px; }
QMenu::item { color: palette(text); background: transparent; padding: 6px 24px; border: 1px solid transparent; }
QMenu::item:selected:enabled { color: palette(highlighted-text); background: palette(highlight); border: 1px solid palette(link); }
QMenu::item:disabled { color: palette(placeholder-text); }
QMenu::separator { height: 1px; background: palette(mid); margin: 4px 8px; }
QPushButton#quickRecipient, QDateEdit#quickDue, QPushButton#workflowRecipient, QDateEdit#workflowDue { background: palette(base); color: palette(text); }
QLineEdit, QPlainTextEdit { background: palette(base); border: 1px solid palette(midlight); padding: 3px; min-height: 17px; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid palette(link); }
/* Leave combo boxes unstyled so Qt draws them with the native platform style;
   the line edit inside editable combo boxes must not get its own frame. */
QComboBox { background: none; }
QComboBox QLineEdit, QComboBox QLineEdit:focus { background: none; border: none; padding: 0; min-height: 0; }
QTabBar#centerTabs::tab { padding: 10px 12px; min-height: 42px; }
QTabBar::tab { padding: 6px 13px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: palette(link); border-bottom: 2px solid palette(link); background: palette(base); }
QToolButton { border: 1px solid transparent; padding: 2px 3px; }
QToolButton:hover, QPushButton:hover { background: palette(highlight); border: 1px solid palette(link); }
QToolButton:disabled { color: palette(placeholder-text); }
QLabel#groupLabel { color: palette(placeholder-text); font-size: 11px; }
QWidget#breadcrumb { border-top: 1px solid palette(mid); border-bottom: 1px solid palette(mid); }
QPushButton { border: 1px solid palette(mid); padding: 5px; text-align: left; }
QWidget#propertiesHeader { border-bottom: 1px solid palette(mid); }
QPushButton#propertyAction { color: white; border: none; border-radius: 0; padding: 4px 7px; font-size: 11px; text-align: center; }
QPushButton#propertyAction[role="edit"] { background: #606060; }
QPushButton#propertyAction[role="commit"] { background: #609bd3; }
QPushButton#propertyAction:hover, QPushButton#propertyAction:focus { background: #397bb8; color: white; }
QPushButton#propertyAction:pressed { background: #285d8e; }
QPushButton#propertyAction:disabled { background: palette(mid); color: palette(placeholder-text); }
QDialogButtonBox QPushButton { min-height: 20px; text-align: center; }
QPushButton#section { background: palette(alternate-base); border: none; border-top: 1px solid palette(mid); border-bottom: 1px solid palette(mid); min-height: 19px; padding: 4px 7px; }
QTreeWidget, QListWidget { border: none; outline: none; }
QListWidget#searchResults::item:hover { background: palette(highlight); color: palette(highlighted-text); }
QTreeWidget::item, QListWidget::item { min-height: 30px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QTableWidget, QTableWidget > QWidget { background: palette(base); border: none; }
QHeaderView::section { background: palette(base); color: palette(placeholder-text); border: none; border-right: 1px solid palette(mid); border-bottom: 1px solid palette(mid); padding: 5px; }
QSplitter::handle { background: palette(mid); width: 1px; height: 1px; }
QScrollArea { border: none; }
/* Leave scrollbars unstyled so Qt draws them with the native platform style. */
QScrollBar { background: none; }
QStatusBar { border-top: 1px solid palette(mid); color: palette(placeholder-text); }
QLabel#emptyMessage { color: palette(placeholder-text); background: palette(base); }
QPushButton#userButton { background: transparent; border: 1px solid transparent; padding: 0; }
QPushButton#userButton:focus { border: 1px solid palette(link); }
QPushButton#userButton:hover, QPushButton#userButton:pressed { background: palette(highlight); border: 1px solid palette(link); }
QPushButton#userButton QWidget { background: transparent; }
QToolTip { color: palette(tool-tip-text); background: palette(tool-tip-base); border: 1px solid palette(mid); }
QTableWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QToolButton:hover, QPushButton:hover { color: palette(highlighted-text); }
'''
