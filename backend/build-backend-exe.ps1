param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $BackendDir
$ExePath = Join-Path $BackendDir "desktop-agent-backend.exe"
$VenvPython = Join-Path $BackendDir "venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

function Get-RunningBackendExeProcess {
    Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try {
            $_.Path -eq $ExePath
        }
        catch {
            $false
        }
    }
}

function Remove-ExistingBackendExe {
    if (!(Test-Path $ExePath)) {
        return
    }

    $running = @(Get-RunningBackendExeProcess)
    if ($running.Count -gt 0) {
        $pids = ($running | Select-Object -ExpandProperty Id) -join ", "
        Write-Error "Backend executable is currently running (PID: $pids). Stop it before rebuilding: $ExePath"
    }

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Remove-Item -LiteralPath $ExePath -Force
            return
        }
        catch {
            if ($attempt -eq 5) {
                Write-Error "Unable to remove existing backend executable after retries: $ExePath. Last error: $_"
            }
            Start-Sleep -Seconds 2
        }
    }
}

if ($CheckOnly) {
    if (Test-Path $ExePath) {
        Write-Host "[build-backend] Found $ExePath"
        exit 0
    }
    Write-Error "Backend executable is missing: $ExePath. Run npm run build:backend from frontend/."
}

Write-Host "[build-backend] Using Python: $Python"

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$versionOutput = & $Python -m PyInstaller --version 2>&1
$pyinstallerExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if ($pyinstallerExitCode -ne 0) {
    Write-Error "PyInstaller is not installed. Install backend requirements first: pip install -r requirements.txt"
}
Write-Host "[build-backend] PyInstaller: $($versionOutput | Select-Object -Last 1)"

$WorkDir = Join-Path $BackendDir "build\pyinstaller"
$ConfigDir = Join-Path $RepoRoot "config"
$PromptsDir = Join-Path $BackendDir "prompts"
$AgentsDir = Join-Path $RepoRoot "AGENTS"

$addData = @()
if (Test-Path $ConfigDir) {
    $addData += @("--add-data", "$ConfigDir;config")
}
if (Test-Path $PromptsDir) {
    $addData += @("--add-data", "$PromptsDir;prompts")
}
if (Test-Path $AgentsDir) {
    $addData += @("--add-data", "$AgentsDir;AGENTS")
}

Push-Location $BackendDir
try {
    Remove-ExistingBackendExe

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name desktop-agent-backend `
        --distpath $BackendDir `
        --workpath $WorkDir `
        --specpath $WorkDir `
        --collect-submodules app `
        --collect-submodules tiktoken_ext `
        --hidden-import numpy._core._exceptions `
        --hidden-import openpyxl `
        --hidden-import xlsxwriter `
        --hidden-import pptx `
        --collect-all sqlite_vec `
        --collect-data litellm `
        --exclude-module pandas.tests `
        --exclude-module matplotlib.tests `
        --exclude-module scipy.tests `
        --exclude-module sklearn.tests `
        --exclude-module torch.utils.tensorboard `
        @addData `
        start.py
    $pyinstallerExitCode = $LASTEXITCODE
    $ErrorActionPreference = $PreviousErrorActionPreference

    if ($pyinstallerExitCode -ne 0) {
        Write-Error "PyInstaller failed with exit code $pyinstallerExitCode"
    }

    if (!(Test-Path $ExePath)) {
        Write-Error "PyInstaller finished but did not create $ExePath"
    }

    Write-Host "[build-backend] Created $ExePath"
}
finally {
    Pop-Location
}
