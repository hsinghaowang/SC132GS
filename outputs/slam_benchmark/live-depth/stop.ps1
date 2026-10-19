$ErrorActionPreference = 'Stop'
Set-Content -LiteralPath (Join-Path $PSScriptRoot 'STOP') -Value 'Stop requested'
Write-Output 'Stop requested. The HTTP server and decoder will close cleanly; allow up to 12 seconds.'
