$ErrorActionPreference = 'Stop'
$viewerPython = Join-Path $PSScriptRoot '..\depth-preview-venv\Scripts\python.exe'
$viewerStop = Join-Path $PSScriptRoot 'STOP-VIEWER'
if (Test-Path -LiteralPath $viewerStop) { Remove-Item -LiteralPath $viewerStop }
$viewerProcess = Start-Process -FilePath $viewerPython -ArgumentList @('-u', ('"' + (Join-Path $PSScriptRoot 'viewer.py') + '"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'viewer-stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'viewer-stderr.log')
$viewerProcess.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'viewer.pid')
Write-Output "PID $($viewerProcess.Id), http://127.0.0.1:8765/"
