"""GUI smoke check used by python -m ultrasmartclient --smoke-test."""
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from .vapi import Repository


def smoke_test(window):
    import tempfile
    window.tabs.setCurrentIndex(2)
    assert window.ribbon.currentIndex() == 2
    window.repositories_loaded([Repository(1, 1, 'Smoke-Test', '', 0, 2)])
    window.center_view.setCurrentIndex(1)
    window.properties_view.setCurrentIndex(1)
    assert not window.windowIcon().isNull()
    window.search.setText('unauffindbar')
    assert window.tree.topLevelItem(0).isHidden()
    window.search.clear()
    assert not window.tree.topLevelItem(0).isHidden()
    window.fields['Bemerkung'].setText('Test')
    assert window.metadata()['Bemerkung'] == 'Test'
    window.fields['Name'].setPlainText('Smoke-Test')
    assert window.metadata()['Name'] == 'Smoke-Test'
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'anlage.txt'
        path.write_text('Demo', encoding='utf-8')
        window.add_attachment(path)
        assert window.content.rowCount() == 1
        assert window.metadata()['Anlagen'] == '1'
        assert window.metadata()['Dateianhänge'] == [str(path.resolve())]
    window.content.setRowCount(0)
    window.attachments.clear()
    window.fields['Anlagen'].setText('0')
    window.fields['Bemerkung'].clear()
    window.empty.show()
    window.tabs.setCurrentIndex(1)
    QApplication.processEvents()
    window.grab().save('/tmp/ultrasmartclient-pyqt6.png')
    print('Smoke-Test erfolgreich', flush=True)
