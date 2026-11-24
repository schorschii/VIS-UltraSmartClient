"""Make bundled Kerberos DLLs available before importing python-gssapi."""
import os
import sys

if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    # Retain the handle for the process lifetime.
    sys._ultrasmartclient_dll_directory = os.add_dll_directory(sys._MEIPASS)
