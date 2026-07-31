Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
. (Join-Path $projectRoot "scripts\local_demo_common.ps1")

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$nodeModules = Join-Path $projectRoot "frontend\node_modules"
$viteEntry = Join-Path $projectRoot "frontend\node_modules\vite\bin\vite.js"
$envFile = Join-Path $projectRoot ".env"
$statePath = Get-IvidaDemoStatePath -ProjectRoot $projectRoot
$stateDirectory = Split-Path $statePath -Parent
$logDirectory = Join-Path $projectRoot "logs\local-demo"

foreach ($required in @($python, $nodeModules, $viteEntry, $envFile)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required local demo dependency is missing: $required"
    }
}

$node = (Get-Command node -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path $stateDirectory, $logDirectory | Out-Null

$existingRecords = @()
if (Test-Path -LiteralPath $statePath) {
    $loaded = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $existingRecords = @($loaded | Where-Object {
        Test-IvidaOwnedProcess -Record $_ -ProjectRoot $projectRoot
    })
}

$externalComponents = [System.Collections.Generic.HashSet[string]]::new()
$portComponents = @{
    8200 = @{
        name = "api"
        signatures = @("run_api.py", "app.main:app")
    }
    5274 = @{
        name = "frontend"
        signatures = @("vite", "frontend")
    }
}

foreach ($port in @(8200, 5274)) {
    $owner = Get-IvidaListeningProcessId -Port $port
    if ($null -ne $owner) {
        $known = $existingRecords | Where-Object { [int]$_.pid -eq $owner }
        if ($null -eq $known) {
            $commandLine = Get-IvidaProcessCommandLine -ProcessId $owner
            $definition = $portComponents[$port]
            $matches = @($definition.signatures | Where-Object {
                $commandLine -like "*$_*"
            })
            if ($matches.Count -gt 0) {
                $externalComponents.Add([string]$definition.name) | Out-Null
                Write-Host (
                    "$($definition.name) already runs outside the launcher " +
                    "(PID $owner); it will be reused but not stopped."
                )
            }
            else {
                throw "Port $port is already used by unknown PID $owner."
            }
        }
    }
}

$existingWorker = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*run_extraction_worker.py*" } |
    Select-Object -First 1
if ($null -ne $existingWorker) {
    $externalComponents.Add("worker") | Out-Null
    Write-Host (
        "worker already runs outside the launcher " +
        "(PID $($existingWorker.ProcessId)); it will be reused but not stopped."
    )
}

$created = [System.Collections.Generic.List[object]]::new()

function Start-IvidaComponent {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$CommandSignature
    )
    if ($externalComponents.Contains($Name)) {
        return $null
    }
    $existing = $existingRecords | Where-Object { $_.component -eq $Name }
    if ($null -ne $existing) {
        Write-Host "$Name already running (PID $($existing.pid))."
        return $existing
    }
    $stdout = Join-Path $logDirectory "$Name.out.log"
    $stderr = Join-Path $logDirectory "$Name.err.log"
    $process = Start-Process `
        -FilePath $Executable `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    $record = [pscustomobject]@{
        component = $Name
        pid = $process.Id
        started_at = $process.StartTime.ToUniversalTime().ToString("o")
        command_signature = $CommandSignature
        project_root = $projectRoot
    }
    $created.Add($record)
    Write-Host "$Name started (PID $($process.Id))."
    return $record
}

try {
    $api = Start-IvidaComponent `
        -Name "api" `
        -Executable $python `
        -Arguments @(
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", "8200"
        ) `
        -WorkingDirectory $projectRoot `
        -CommandSignature "app.main:app"
    $worker = Start-IvidaComponent `
        -Name "worker" `
        -Executable $python `
        -Arguments @("run_extraction_worker.py") `
        -WorkingDirectory $projectRoot `
        -CommandSignature "run_extraction_worker.py"
    $frontend = Start-IvidaComponent `
        -Name "frontend" `
        -Executable $node `
        -Arguments @($viteEntry, "--host", "127.0.0.1", "--port", "5274") `
        -WorkingDirectory (Join-Path $projectRoot "frontend") `
        -CommandSignature "vite.js"

    @($existingRecords + $created.ToArray()) |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $statePath -Encoding UTF8

    Wait-IvidaHttp -Uri "http://127.0.0.1:8200/api/health"
    Wait-IvidaHttp -Uri "http://127.0.0.1:5274"

    Write-Host ""
    Write-Host "IVIDA local demo is ready."
    Write-Host "UI:  http://127.0.0.1:5274"
    Write-Host "API: http://127.0.0.1:8200/docs"
    Write-Host "Logs: $logDirectory"
    Start-Process "http://127.0.0.1:5274"
}
catch {
    foreach ($record in $created) {
        Stop-IvidaRecord -Record $record -ProjectRoot $projectRoot
    }
    throw
}
