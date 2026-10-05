$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'RUBIK Pi Shared Console - COM5'

$python = 'D:\Program Files\Python312\python.exe'
$console = 'D:\projects\collision_avoid\outputs\sc132gs_v4l2_probe\recovery-tools\shared_serial_console.py'
$log = 'D:\projects\collision_avoid\outputs\sc132gs_v4l2_probe\recovery-tools\com5-live.log'

& $python $console --port COM5 --baud 115200 --log $log

Write-Host ''
Write-Host 'Serial console ended. Press Enter to close this window.'
[void](Read-Host)
