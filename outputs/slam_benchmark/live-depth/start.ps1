$ErrorActionPreference = 'Stop'
$depthPython = Join-Path $PSScriptRoot '..\depth-preview-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $depthPython)) {
    throw 'Missing environment. Create ../depth-preview-venv and install live-depth/requirements.txt first.'
}
$depthStop = Join-Path $PSScriptRoot 'STOP'
if (Test-Path -LiteralPath $depthStop) { Remove-Item -LiteralPath $depthStop }
$depthProcess = Start-Process -FilePath $depthPython -ArgumentList @('-u', ('"' + (Join-Path $PSScriptRoot 'server.py') + '"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'stderr.log')
$depthProcess.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'server.pid')
Write-Output "PID $($depthProcess.Id), http://127.0.0.1:8765/"
