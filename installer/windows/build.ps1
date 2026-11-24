# Run with a Windows Python environment containing the app, PyInstaller and Pillow.
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$OutputDir,
    [string]$KerberosBin = "$env:ProgramFiles\MIT\Kerberos\bin"
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on Windows.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $OutputDir) { $OutputDir = Join-Path $Root 'dist/windows' }
$OutputDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)
$BuildDir = Join-Path $Root 'build/windows'
if (-not (Test-Path -LiteralPath $KerberosBin -PathType Container)) {
    throw 'Install MIT Kerberos for Windows or supply -KerberosBin with its bin directory.'
}
$KerberosBin = (Resolve-Path -LiteralPath $KerberosBin).Path
$Dlls = @(Get-ChildItem -LiteralPath $KerberosBin -Filter '*.dll' -File)
if (-not ($Dlls | Where-Object { $_.Name -match '^gssapi(32|64)\.dll$' })) {
    throw 'KerberosBin does not contain the MIT GSSAPI DLL.'
}
$OldPath = $env:PATH
try {
    $env:PATH = "$KerberosBin;$env:PATH"
    & $Python -c 'import PyInstaller, PIL, ultrasmartclient.main'
    if ($LASTEXITCODE -ne 0) { throw 'Install the build dependencies in the selected Python environment.' }
    New-Item -ItemType Directory -Force -Path $OutputDir, $BuildDir | Out-Null
    $Arguments = @(
        '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed', '--noupx',
        '--name', 'UltraSmartClient', '--paths', $Root,
        '--distpath', $OutputDir, '--workpath', (Join-Path $BuildDir 'work'), '--specpath', $BuildDir,
        '--icon', (Join-Path $Root 'ultrasmartclient/assets/icons/app.png'),
        '--add-data', "${Root}/ultrasmartclient/assets:ultrasmartclient/assets",
        '--collect-all', 'gssapi', '--hidden-import', 'PyQt6.QtSvg',
        '--runtime-hook', (Join-Path $PSScriptRoot 'runtime_hook.py')
    )
    foreach ($Dll in $Dlls) { $Arguments += @('--add-binary', "$($Dll.FullName):.") }
    $Arguments += (Join-Path $Root 'installer/pyinstaller_entry.py')
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    Write-Output (Join-Path $OutputDir 'UltraSmartClient.exe')
} finally {
    $env:PATH = $OldPath
}
