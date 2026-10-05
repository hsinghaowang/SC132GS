$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'Sc132gsLiveViewer.csproj'
dotnet run --project $project --configuration Release --no-restore -- 'ubuntu@pi-ubuntu'
