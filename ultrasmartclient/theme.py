"""Application-wide light/dark palette, following the desktop by default."""
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette


def versiontuple(v):
    return tuple(map(int, (v.split('.'))))

class ThemeManager(QObject):
    changed = pyqtSignal()

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.mode = 'system'
        self.dark = False
        self._applying = False
        self._system_dark = self.palette_is_dark(app.palette())
        app.paletteChanged.connect(self.palette_changed)
        if hasattr(app.styleHints(), 'colorSchemeChanged'):
            app.styleHints().colorSchemeChanged.connect(self.system_changed)
        self.apply()

    def system_changed(self, _scheme):
        if self.mode == 'system':
            self.apply()

    def set_mode(self, mode):
        if mode not in ('system', 'light', 'dark'):
            raise ValueError(mode)
        self.mode = mode
        self.apply()

    @staticmethod
    def palette_is_dark(palette):
        return (palette.color(QPalette.ColorRole.Window).lightness()
                < palette.color(QPalette.ColorRole.WindowText).lightness())

    def palette_changed(self, palette):
        # Ignore palettes installed by our own Light/Dark controls.
        if self._applying:
            return
        self._system_dark = self.palette_is_dark(palette)
        self.apply()

    def system_is_dark(self):
        hints = self.app.styleHints()
        schemes = getattr(Qt, 'ColorScheme', None)
        if hasattr(hints, 'colorScheme') and schemes is not None:
            scheme = hints.colorScheme()
            if scheme == schemes.Dark:
                return True
            if scheme == schemes.Light:
                return False
        return self._system_dark

    def apply(self):
        self.dark = self.mode == 'dark' or (self.mode == 'system' and self.system_is_dark())
        colors = {
            'Window': '#26292e' if self.dark else '#efefef',
            'WindowText': '#e6e9ed' if self.dark else '#252525',
            'Base': '#1c1f23' if self.dark else '#ffffff',
            'AlternateBase': '#30343b' if self.dark else '#f7f7f7',
            'Text': '#e6e9ed' if self.dark else '#252525',
            'Button': '#30343b' if self.dark else '#efefef',
            'ButtonText': '#e6e9ed' if self.dark else '#252525',
            'Highlight': '#355f8b' if self.dark else '#abc5e6',
            'HighlightedText': '#ffffff' if self.dark else '#111111',
            'Link': '#99c5ff' if self.dark else '#233f70',
            'PlaceholderText': '#a6adb7' if self.dark else '#666666',
            'Mid': '#505761' if self.dark else '#cccccc',
            'Dark': '#17191d' if self.dark else '#888888',
            'Light': '#606873' if self.dark else '#fafafa',
            'Midlight': '#3b4149' if self.dark else '#dedede',
            'Shadow': '#101215' if self.dark else '#777777',
            'ToolTipBase': '#353b43' if self.dark else '#ffffef',
            'ToolTipText': '#f0f2f5' if self.dark else '#252525',
        }
        palette = QPalette()
        for role, color in colors.items():
            palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
        for role in ('Text', 'WindowText', 'ButtonText'):
            palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role),
                             QColor('#9199a5' if self.dark else '#999999'))
        # QSS caches palette() brushes; rebuild it when switching themes.
        stylesheet = self.app.styleSheet()
        self._applying = True
        try:
            self.app.setStyleSheet('')
            self.app.setPalette(palette)
            self.app.setStyleSheet(stylesheet)
        finally:
            self._applying = False
        self.changed.emit()
