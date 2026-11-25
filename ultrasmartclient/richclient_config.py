"""Settings shared with an installed VIS RichClient configuration."""
import sys
from pathlib import Path

from defusedxml import ElementTree

from . import executable_dir

CONFIG_NAME = 'VISRichClientShell.exe.config'


def config_candidates():
    """Locations searched for the RichClient configuration, in order of precedence."""
    candidates = []
    if sys.platform != 'win32':
        candidates.append(Path('/etc/ultrasmartclient') / CONFIG_NAME)
    candidates.append(executable_dir() / CONFIG_NAME)
    if sys.platform == 'win32':
        candidates.append(Path(r'C:\Program Files (x86)\PDV-Systeme\SmartClient') / CONFIG_NAME)
    return candidates


def custom_wizard_fields(path=None):
    """Return the CustomWizardFields entries (identifiers or labels), one per non-empty line.

    Without a path, the first existing configuration from config_candidates() is used. A missing or
    unreadable file yields an empty list, so the new-object dialog keeps its default fields.
    """
    if path is None:
        path = next((candidate for candidate in config_candidates() if candidate.is_file()), None)
        if path is None:
            return []
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return []
    for setting in root.iter('setting'):
        if setting.get('name') == 'CustomWizardFields':
            text = setting.findtext('value') or ''
            return list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))
    return []
