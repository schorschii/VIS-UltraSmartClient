"""Application-wide light/dark palette, following the desktop by default."""
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen, qGray
from PyQt6.QtWidgets import QProxyStyle, QStyle


def versiontuple(v):
    return tuple(map(int, (v.split('.'))))

def fusion_button_color(button):
    """The colour the Fusion style draws for a palette Button colour (it brightens dark ones)."""
    value = qGray(button.rgb())
    color = button.lighter(100 + max(1, (180 - value) // 6))
    color.setHsv(color.hue(), int(color.saturation() * 0.75), color.value())
    return color


def fusion_button_for(target):
    """A Button colour that the Fusion style draws as ``target``."""
    def distance(color):
        drawn = fusion_button_color(color)
        return sum(abs(a - b) for a, b in zip(drawn.getRgb()[:3], target.getRgb()[:3]))
    return min((target.darker(factor) for factor in range(100, 201)), key=distance)


class ComboFrameStyle(QProxyStyle):
    """Fusion, with combo boxes framed in the text boxes' border colours (QSS would disable native drawing)."""

    def sizeFromContents(self, contents, option, size, widget=None):
        size = super().sizeFromContents(contents, option, size, widget)
        if contents == QStyle.ContentsType.CT_ComboBox:
            # Text box height: text line (font + 1px margin above and below, stylesheet min-height 17px)
            # + 2 * 3px padding + 2 * 1px border.
            size.setHeight(max(size.height(), max(17, option.fontMetrics.height() + 2) + 8))
        return size

    def drawComplexControl(self, control, option, painter, widget=None):
        super().drawComplexControl(control, option, painter, widget)
        if control != QStyle.ComplexControl.CC_ComboBox or not getattr(option, 'frame', True):
            return
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        color = option.palette.color(QPalette.ColorRole.Link if focused else QPalette.ColorRole.Midlight)
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # Look like the text boxes: a square single-line frame. The field background covers
        # Fusion's rounded corners and its inner contrast line just inside the frame.
        background = option.palette.color(QPalette.ColorRole.Base)
        painter.setPen(QPen(background))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(1, 1, -2, -2))
        # The inner line's rounded corners reach one pixel further in.
        for x, y in ((2, 2), (rect.width() - 3, 2), (2, rect.height() - 3), (rect.width() - 3, rect.height() - 3)):
            painter.fillRect(rect.x() + x, rect.y() + y, 1, 1, background)
        painter.setPen(QPen(color))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.restore()


def is_fusion(style):
    if isinstance(style, QProxyStyle):
        style = style.baseStyle()
    return style.metaObject().className() == 'QFusionStyle'


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
            # Without a stylesheet, style() is the real style rather than Qt's stylesheet wrapper.
            if is_fusion(self.app.style()) and not isinstance(self.app.style(), ComboFrameStyle):
                self.app.setStyle(ComboFrameStyle(self.app.style()))
            self.app.setPalette(palette)
            # Combo boxes get the text boxes' background. A palette keeps them natively drawn,
            # which any QSS background rule would turn off.
            combo = QPalette(palette)
            fusion = is_fusion(self.app.style())
            for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
                base = palette.color(group, QPalette.ColorRole.Base)
                combo.setColor(group, QPalette.ColorRole.Button, fusion_button_for(base) if fusion else base)
            self.app.setPalette(combo, 'QComboBox')
            self.app.setStyleSheet(stylesheet)
        finally:
            self._applying = False
        self.changed.emit()
