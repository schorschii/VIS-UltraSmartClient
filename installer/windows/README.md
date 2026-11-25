# Windows portable build

Run on Windows with Python 3.10+ of the target architecture. MIT Kerberos is not
needed: authentication uses [winkerberos](https://github.com/mongodb-labs/winkerberos),
which talks to Windows SSPI and uses the ticket of the logged-on domain user.
From the repository root, prepare a build environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install . 'pyinstaller>=6,<7' Pillow
.\installer\windows\build.ps1 -Python .\.venv\Scripts\python.exe
```

pip installs winkerberos as a prebuilt wheel; on Windows, python-gssapi and
requests-gssapi are not installed. The script uses the existing environment and does not install dependencies.

The output is `dist/windows/UltraSmartClient.exe`, a windowed portable single-file
executable. Python, Qt, image assets and winkerberos are bundled; PyInstaller
extracts runtime files to a temporary directory when it starts. No application
installer or Python installation is required on the target machine.

Options:

- `-Python`: Python executable in the prepared build environment.
- `-OutputDir`: alternative output directory.

Build separately for each Windows architecture. Tenant configuration and a
Windows domain logon (Kerberos ticket from the domain controller) are still
required for server access; `klist` shows the current tickets. The binary is not Authenticode-signed.
Test on a clean Windows machine as well as running this local smoke check:

```powershell
$process = Start-Process .\dist\windows\UltraSmartClient.exe -ArgumentList '--smoke-test' -Wait -PassThru
if ($process.ExitCode -ne 0) { throw 'Smoke test failed' }
```

See [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html).
