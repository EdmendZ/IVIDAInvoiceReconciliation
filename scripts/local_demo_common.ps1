Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-IvidaDemoStatePath {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)
    return Join-Path $ProjectRoot ".local-demo\processes.json"
}

function Get-IvidaProcessCommandLine {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $item = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if ($null -eq $item) {
        return $null
    }
    return [string]$item.CommandLine
}

function Test-IvidaOwnedProcess {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )
    if ([string]$Record.project_root -ne $ProjectRoot) {
        return $false
    }
    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    $recordedStart = [datetime]::Parse([string]$Record.started_at).ToUniversalTime()
    $actualStart = $process.StartTime.ToUniversalTime()
    if ([math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) {
        return $false
    }
    $commandLine = Get-IvidaProcessCommandLine -ProcessId ([int]$Record.pid)
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        return $false
    }
    return $commandLine.Contains([string]$Record.command_signature)
}

function Get-IvidaListeningProcessId {
    param([Parameter(Mandatory = $true)][int]$Port)
    $listener = Get-NetTCPConnection `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return $null
    }
    return [int]$listener.OwningProcess
}

function Wait-IvidaHttp {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$TimeoutSeconds = 30
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timed out waiting for $Uri"
}

function Stop-IvidaRecord {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )
    if (-not (Test-IvidaOwnedProcess -Record $Record -ProjectRoot $ProjectRoot)) {
        Write-Warning "Skipped PID $($Record.pid): ownership could not be verified."
        return
    }
    Stop-Process -Id ([int]$Record.pid) -ErrorAction Stop
}
