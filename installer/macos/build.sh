#!/bin/sh
# Run on macOS with the application, PyInstaller and Pillow installed.
set -eu
packaging=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$packaging/../.." && pwd)
python=${PYTHON:-python3}
output=${1:-"$root/dist/macos"}
[ "$#" -le 1 ] || { echo "Usage: $0 [output-directory]" >&2; exit 1; }
[ "$(uname -s)" = Darwin ] || { echo 'Build this package on macOS.' >&2; exit 1; }
"$python" -c 'import PyInstaller, PIL, ultrasmartclient.main'
mkdir -p -- "$output" "$root/build/macos"
output=$(CDPATH= cd -- "$output" && pwd)
# Preserve argument boundaries when optionally adding a signing identity.
set --
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    set -- --codesign-identity "$CODESIGN_IDENTITY"
fi
"$python" -m PyInstaller --noconfirm --clean --windowed --onedir --noupx \
    --name UltraSmartClient --osx-bundle-identifier de.ultrasmartclient.desktop \
    --paths "$root" --distpath "$output" \
    --workpath "$root/build/macos/work" --specpath "$root/build/macos" \
    --icon "$root/ultrasmartclient/assets/icons/app.png" \
    --add-data "$root/ultrasmartclient/assets:ultrasmartclient/assets" \
    --collect-all gssapi --hidden-import PyQt6.QtSvg \
    "$@" "$root/installer/pyinstaller_entry.py"
staging=$(mktemp -d "${TMPDIR:-/tmp}/ultrasmartclient-dmg.XXXXXXXX")
trap 'rm -rf -- "$staging"' EXIT
trap 'exit 1' HUP INT TERM
ditto "$output/UltraSmartClient.app" "$staging/UltraSmartClient.app"
ln -s /Applications "$staging/Applications"
hdiutil create -ov -volname UltraSmartClient -srcfolder "$staging" \
    -format UDZO "$output/UltraSmartClient.dmg"
echo "$output/UltraSmartClient.dmg"
