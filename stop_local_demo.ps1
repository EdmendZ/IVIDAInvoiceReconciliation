Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
. (Join-Path $projectRoot "scripts\local_demo_common.ps1")
$statePath = Get-IvidaDemoStatePath -ProjectRoot $projectRoot

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host "No IVIDA local demo process record was found."
    exit 0
}

$records = @(Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json)
foreach ($record in ($records | Sort-Object component -Descending)) {
    Stop-IvidaRecord -Record $record -ProjectRoot $projectRoot
}

Remove-Item -LiteralPath $statePath -Force
Write-Host "IVIDA local demo processes stopped."
