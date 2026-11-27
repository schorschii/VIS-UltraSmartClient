#!/bin/env python3

import argparse
import os
import sys

if sys.platform == 'win32':
    # Validate TLS certificates against the Windows certificate store (including
    # company root CAs deployed by group policy) instead of certifi's bundle only.
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

from PyQt6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PyQt6.QtWidgets import QApplication, QMessageBox

from .gui import Client, LoginStartup, STYLE, settings
from .tenants import TenantSelector
from .theme import ThemeManager


def main():
    parser = argparse.ArgumentParser(description='VIS UltraSmartClient')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--demo', action='store_true',
                        help='Hauptfenster mit Beispieldaten ohne Serververbindung starten')
    parser.add_argument('--debug', action='store_true',
                        help='SOAP-Anfragen und -Antworten auf stdout ausgeben')
    args, qt_args = parser.parse_known_args()
    app = QApplication([sys.argv[0], *qt_args])
    # Parent and retain the translator for the entire application lifetime.
    app.qt_translator = QTranslator(app)
    if app.qt_translator.load(QLocale.system(), 'qtbase', '_',
                             QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(app.qt_translator)
    app.soap_debug = args.debug
    # Keep Qt's platform-selected style for native controls such as scrollbars.
    app.theme_manager = ThemeManager(app)
    saved_theme = settings().value('appearance/theme', 'system')
    if saved_theme in ('light', 'dark'):
        app.theme_manager.set_mode(saved_theme)
    app.setStyleSheet(STYLE)
    if not args.smoke_test and not args.demo:
        app.setQuitOnLastWindowClosed(False)
        try:
            selector = TenantSelector(initial_url=os.environ.get('VIS_SERVER_URL'))
        except (OSError, ValueError) as error:
            QMessageBox.critical(None, 'Mandantenkonfiguration konnte nicht geladen werden', str(error))
            return 1
        startup = LoginStartup(app, selector=selector)
        selector.show()
        return app.exec()
    if args.demo:
        from .demo import create_demo_window
        window = create_demo_window()
    else:
        window = Client()
    window.show()
    result = [0]
    if args.smoke_test:
        def verify():
            try:
                from .smoke import smoke_test
                smoke_test(window)
            except Exception:
                import traceback
                traceback.print_exc()
                result[0] = 1
            finally:
                app.quit()
        QTimer.singleShot(250, verify)
    app.exec()
    return result[0]


if __name__ == '__main__':
    sys.exit(main())
