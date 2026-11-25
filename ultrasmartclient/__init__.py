"""VIS UltraSmartClient desktop application."""

APP_NAME = "UltraSmartClient"
VERSION  = "0.2.0"

import sys
from pathlib import Path

def executable_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path.cwd()
