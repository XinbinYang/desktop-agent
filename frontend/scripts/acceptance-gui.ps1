param(
    [string]$ReleaseDir,
    [int]$TimeoutSeconds = 90,
    [switch]$ForceStop,
    [switch]$KeepUserData
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent $FrontendDir
$LatestFile = Join-Path $FrontendDir "release-packaged\latest.txt"
$AcceptanceDir = Join-Path $FrontendDir "release-packaged\acceptance"
$ReportPath = Join-Path $AcceptanceDir "latest-report.json"
$ScreenshotPath = Join-Path $AcceptanceDir "latest-screenshot.png"
$HelperPath = Join-Path $ScriptDir "acceptance_gui_helper.py"
$VenvPython = Join-Path $RepoRoot "backend\venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

function Resolve-ReleaseDir {
    param([string]$Candidate)

    if (![string]::IsNullOrWhiteSpace($Candidate)) {
        return (Resolve-Path -LiteralPath $Candidate).Path
    }

    if (!(Test-Path $LatestFile)) {
        throw "Latest packaged release marker is missing: $LatestFile. Run npm run dist first."
    }

    $latest = (Get-Content -LiteralPath $LatestFile -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($latest)) {
        throw "Latest packaged release marker is empty: $LatestFile"
    }
    return (Resolve-Path -LiteralPath $latest).Path
}

function Get-ProcessByPath {
    param([string[]]$Paths)

    $resolved = @{}
    foreach ($path in $Paths) {
        if (![string]::IsNullOrWhiteSpace($path)) {
            $resolved[(Resolve-Path -LiteralPath $path -ErrorAction SilentlyContinue).Path] = $true
        }
    }

    Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try {
            $_.Path -and $resolved.ContainsKey($_.Path)
        }
        catch {
            $false
        }
    }
}

function Stop-MatchingProcesses {
    param([string[]]$Paths)

    $matches = @(Get-ProcessByPath -Paths $Paths)
    foreach ($proc in $matches) {
        Write-Host "[acceptance-gui] Stopping $($proc.ProcessName) PID $($proc.Id)"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($matches.Count -gt 0) {
        Start-Sleep -Seconds 2
    }
}

function Test-IsDesktopAgentProcess {
    param($Process)

    $name = $Process.ProcessName
    if ($name -in @("Desktop Agent", "desktop-agent-backend")) {
        return $true
    }

    try {
        return $Process.Path -like "*\Desktop Agent\*"
    }
    catch {
        return $false
    }
}

function Get-DesktopAgentPortOwners {
    param([int]$Port)

    $connections = @(Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    $connections |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            Get-Process -Id $_ -ErrorAction SilentlyContinue
        }
}

function Stop-DesktopAgentPortOwners {
    param([int]$Port)

    $owners = @(Get-DesktopAgentPortOwners -Port $Port)
    if ($owners.Count -eq 0) {
        return
    }

    $nonAgentOwners = @($owners | Where-Object { !(Test-IsDesktopAgentProcess -Process $_) })
    if ($nonAgentOwners.Count -gt 0) {
        $details = ($nonAgentOwners | ForEach-Object { "$($_.ProcessName):$($_.Id)" }) -join ", "
        throw "Port $Port is already in use by a non-Desktop-Agent process ($details). Stop that process before running GUI acceptance."
    }

    if (!$ForceStop) {
        $details = ($owners | ForEach-Object { "$($_.ProcessName):$($_.Id)" }) -join ", "
        throw "Port $Port is already in use by Desktop Agent ($details). Re-run with -ForceStop to stop Desktop Agent-owned processes for acceptance."
    }

    foreach ($proc in $owners) {
        Write-Host "[acceptance-gui] Stopping port $Port owner $($proc.ProcessName) PID $($proc.Id)"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

$ResolvedReleaseDir = Resolve-ReleaseDir -Candidate $ReleaseDir
$WinUnpackedDir = Join-Path $ResolvedReleaseDir "win-unpacked"
$ExePath = Join-Path $WinUnpackedDir "Desktop Agent.exe"
$BackendExePath = Join-Path $WinUnpackedDir "resources\backend\desktop-agent-backend.exe"
$PackageJson = Get-Content -LiteralPath (Join-Path $FrontendDir "package.json") -Raw | ConvertFrom-Json
$InstallerPath = Join-Path $ResolvedReleaseDir ("Desktop-Agent-Setup-{0}.exe" -f $PackageJson.version)

if (!(Test-Path $ExePath)) {
    throw "Packaged Desktop Agent executable is missing: $ExePath"
}
if (!(Test-Path $BackendExePath)) {
    throw "Packaged backend executable is missing: $BackendExePath. Run npm run build:backend before packaging."
}
if (!(Test-Path $InstallerPath)) {
    throw "Packaged Desktop Agent installer is missing: $InstallerPath"
}
if (!(Test-Path $HelperPath)) {
    throw "Acceptance helper is missing: $HelperPath"
}

$targetPaths = @($ExePath, $BackendExePath)
$existing = @(Get-ProcessByPath -Paths $targetPaths)
if ($existing.Count -gt 0) {
    if (!$ForceStop) {
        $pids = ($existing | ForEach-Object { "$($_.ProcessName):$($_.Id)" }) -join ", "
        throw "Existing Desktop Agent processes from this packaged release are running ($pids). Re-run with -ForceStop to stop only these packaged processes."
    }
    Stop-MatchingProcesses -Paths $targetPaths
}
Stop-DesktopAgentPortOwners -Port 8765

New-Item -ItemType Directory -Force -Path $AcceptanceDir | Out-Null
$FreshUserData = Join-Path $env:TEMP ("desktop-agent-acceptance-userdata-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $FreshUserData | Out-Null

Write-Host "[acceptance-gui] Release: $ResolvedReleaseDir"
Write-Host "[acceptance-gui] User data: $FreshUserData"
Write-Host "[acceptance-gui] Starting packaged GUI"

$started = $null
$PreviousUserDataEnv = $env:DESKTOP_AGENT_USER_DATA_DIR
try {
    $env:DESKTOP_AGENT_USER_DATA_DIR = $FreshUserData

    $started = Start-Process `
        -FilePath $ExePath `
        -WorkingDirectory $WinUnpackedDir `
        -ArgumentList @("--user-data-dir=$FreshUserData") `
        -PassThru

    Write-Host "[acceptance-gui] Electron PID: $($started.Id)"

    & $Python $HelperPath `
        --release-dir $ResolvedReleaseDir `
        --exe $ExePath `
        --backend-exe $BackendExePath `
        --installer $InstallerPath `
        --user-data-dir $FreshUserData `
        --report $ReportPath `
        --screenshot $ScreenshotPath `
        --timeout-seconds $TimeoutSeconds
    $helperExitCode = $LASTEXITCODE

    if ($helperExitCode -ne 0) {
        throw "GUI acceptance failed. See report: $ReportPath"
    }

    Write-Host "[acceptance-gui] Passed"
    Write-Host "[acceptance-gui] Report: $ReportPath"
    Write-Host "[acceptance-gui] Screenshot: $ScreenshotPath"
}
finally {
    if ($null -eq $PreviousUserDataEnv) {
        Remove-Item Env:DESKTOP_AGENT_USER_DATA_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:DESKTOP_AGENT_USER_DATA_DIR = $PreviousUserDataEnv
    }

    Stop-MatchingProcesses -Paths $targetPaths
    if (!$KeepUserData -and (Test-Path $FreshUserData)) {
        Remove-Item -LiteralPath $FreshUserData -Recurse -Force -ErrorAction SilentlyContinue
    }
}
