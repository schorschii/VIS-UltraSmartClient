# macOS build

Run on macOS with Python 3.10+ of the architecture you want to distribute.
Prepare a build environment from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install . 'pyinstaller>=6,<7' Pillow
./installer/macos/build.sh
```

The script uses shell tools for packaging and Python only for dependency checking
and PyInstaller. It does not download or install dependencies itself. If building
python-gssapi from source, install the Xcode command-line tools first.

Outputs:

- `dist/macos/UltraSmartClient.app`: windowed app with Python, Qt and image assets.
- `dist/macos/UltraSmartClient.dmg`: compressed disk image containing the app and
  an Applications shortcut. Drag the app to Applications to install.

An optional first argument selects the output directory. Set `PYTHON` to choose
a Python executable. Set `CODESIGN_IDENTITY` to pass a Developer ID identity to
PyInstaller; notarization is a separate release step. Without that identity,
the build is intended for local testing, not a notarized public release.

Build separately on Intel and Apple Silicon for each architecture. The packaged
app still needs tenant configuration and a valid Kerberos ticket for server access.
Run `dist/macos/UltraSmartClient.app/Contents/MacOS/UltraSmartClient --smoke-test`
on the build host before distributing it.

See [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html) for native
build, bundle and signing options.
