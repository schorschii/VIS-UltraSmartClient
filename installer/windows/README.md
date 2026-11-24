# Windows portable build

Run on Windows with Python 3.10+ and MIT Kerberos for Windows installed, both of
matching architecture. From the repository root, prepare a build environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install . 'pyinstaller>=6,<7' Pillow
.\installer\windows\build.ps1 -Python .\.venv\Scripts\python.exe
```

If pip needs to compile python-gssapi, the matching Microsoft C++ build tools
and Kerberos development headers/libraries must also be available.
The script uses the existing environment and does not install dependencies.

The output is `dist/windows/UltraSmartClient.exe`, a windowed portable single-file
executable. Python, Qt, image assets and MIT Kerberos DLLs are bundled; PyInstaller
extracts runtime files to a temporary directory when it starts. No application
installer or Python installation is required on the target machine.

Options:

- `-Python`: Python executable in the prepared build environment.
- `-OutputDir`: alternative output directory.
- `-KerberosBin`: MIT Kerberos DLL directory (default:
  `C:\Program Files\MIT\Kerberos\bin`). DLLs are included in the executable and
  a runtime hook makes them discoverable before GSSAPI loads.

Build separately for each Windows architecture. Tenant configuration, Kerberos
realm configuration and valid credentials are still required for server access;
packaging does not provision tickets. The binary is not Authenticode-signed.
Test on a clean Windows machine as well as running this local smoke check:

```powershell
$process = Start-Process .\dist\windows\UltraSmartClient.exe -ArgumentList '--smoke-test' -Wait -PassThru
if ($process.ExitCode -ne 0) { throw 'Smoke test failed' }
```

See [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html) and
[python-gssapi's Windows loader](https://github.com/pythongssapi/python-gssapi/blob/main/gssapi/_win_config.py).
