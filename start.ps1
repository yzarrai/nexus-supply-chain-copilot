$nexusPython = Get-Command python -ErrorAction SilentlyContinue
if ($nexusPython) { $nexusExecutable = $nexusPython.Source }
else { $nexusExecutable = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' }
if (-not (Test-Path -LiteralPath $nexusExecutable)) { throw 'Install Python 3.11 or newer, then run python app.py.' }
Set-Location -LiteralPath $PSScriptRoot
& $nexusExecutable app.py
