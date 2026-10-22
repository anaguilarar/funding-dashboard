# Runs the full monitoring pipeline and appends output to logs\run-YYYY-MM.log
# Used by the Windows scheduled task (see register_task.ps1). Can also be run by hand.
param([string]$Python = "")
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
$log = Join-Path $root ("logs\run-" + (Get-Date -Format "yyyy-MM") + ".log")
$python = if ($Python) { $Python } else { "python" }
"==== $(Get-Date -Format s) ====" | Out-File -FilePath $log -Append -Encoding utf8
$env:PYTHONIOENCODING = "utf-8"
& $python -m fundintel run *>&1 | Out-File -FilePath $log -Append -Encoding utf8
"exit code: $LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
exit $LASTEXITCODE
