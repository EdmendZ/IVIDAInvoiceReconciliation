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

function Convert-IvidaUtcDateTime {
    param([Parameter(Mandatory = $true)]$Value)
    if ($Value -is [datetime]) {
        return ([datetime]$Value).ToUniversalTime()
    }
    return [datetime]::Parse(
        [string]$Value,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    ).ToUniversalTime()
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
    $recordedStart = Convert-IvidaUtcDateTime -Value $Record.started_at
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

function Get-IvidaDescendantProcessIds {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $processes = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId)
    $children = @{}
    foreach ($process in $processes) {
        $parent = [int]$process.ParentProcessId
        if (-not $children.ContainsKey($parent)) {
            $children[$parent] = [System.Collections.Generic.List[int]]::new()
        }
        $children[$parent].Add([int]$process.ProcessId)
    }
    $result = [System.Collections.Generic.List[int]]::new()
    function Add-IvidaDescendants {
        param([int]$ParentId)
        if (-not $children.ContainsKey($ParentId)) {
            return
        }
        foreach ($childId in $children[$ParentId]) {
            Add-IvidaDescendants -ParentId $childId
            $result.Add($childId)
        }
    }
    Add-IvidaDescendants -ParentId $ProcessId
    return $result.ToArray()
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
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
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
    $processId = [int]$Record.pid
    foreach ($descendantId in @(Get-IvidaDescendantProcessIds -ProcessId $processId)) {
        Stop-Process -Id $descendantId -ErrorAction SilentlyContinue
        Wait-Process -Id $descendantId -Timeout 10 -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
    Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
}
