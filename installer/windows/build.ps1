# Run with a Windows Python environment containing the app, PyInstaller and Pillow.
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$OutputDir
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on Windows.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $OutputDir) { $OutputDir = Join-Path $Root 'dist/windows' }
$OutputDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)
$BuildDir = Join-Path $Root 'build/windows'
& $Python -c 'import PyInstaller, PIL, winkerberos, ultrasmartclient.main'
if ($LASTEXITCODE -ne 0) { throw 'Install the build dependencies in the selected Python environment.' }
New-Item -ItemType Directory -Force -Path $OutputDir, $BuildDir | Out-Null
$Arguments = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed', '--noupx',
    '--name', 'UltraSmartClient', '--paths', $Root,
    '--distpath', $OutputDir, '--workpath', (Join-Path $BuildDir 'work'), '--specpath', $BuildDir,
    '--icon', (Join-Path $Root 'ultrasmartclient/assets/icons/app.png'),
    '--add-data', "${Root}/ultrasmartclient/assets:ultrasmartclient/assets",
    '--hidden-import', 'winkerberos', '--hidden-import', 'ultrasmartclient.sspi_auth',
    '--hidden-import', 'PyQt6.QtSvg'
)
$Arguments += (Join-Path $Root 'installer/pyinstaller_entry.py')
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Write-Output (Join-Path $OutputDir 'UltraSmartClient.exe')
