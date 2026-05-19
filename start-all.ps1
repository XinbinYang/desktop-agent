# Desktop Agent - One-click launcher.
# Double-click start-all.bat or run from PowerShell: .\start-all.ps1

# NOTE: This launcher is for development/source mode. Customer installs should use the Windows installer.
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }

$backendDir  = Join-Path $scriptDir 'backend'
$frontendDir = Join-Path $scriptDir 'frontend'
$userDataDir = Join-Path $env:APPDATA 'Desktop Agent'
$venvPython  = Join-Path $backendDir 'venv\Scripts\python.exe'

Write-Host '=========================================' -ForegroundColor Cyan
Write-Host '  Desktop Agent - Dev Source Start' -ForegroundColor Cyan
Write-Host '=========================================' -ForegroundColor Cyan

# ------------------------------------------------------------------
# Sanity checks
# ------------------------------------------------------------------
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue

function Stop-OnPort {
    param([int]$Port)
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}

# ------------------------------------------------------------------
# Local auth token — share the same token Electron uses.
# ------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $userDataDir | Out-Null
$authFile = Join-Path $userDataDir 'local-auth.json'
$authToken = ''
if (Test-Path $authFile) {
    try {
        $authData = Get-Content $authFile -Encoding UTF8 -Raw | ConvertFrom-Json
        if ($authData.token -and $authData.token.Length -ge 32) { $authToken = $authData.token }
    } catch {}
}
if (-not $authToken) {
    $bytes = [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    $authToken = -join ($bytes | ForEach-Object { '{0:x2}' -f $_ })
    try { @{ token = $authToken } | ConvertTo-Json | Set-Content $authFile -Encoding UTF8 } catch {}
}
$headers = @{ 'X-Desktop-Agent-Token' = $authToken }

function Wait-HttpReady {
    param([string]$Url, [int]$TimeoutSec = 30)
    for ($i = 1; $i -le $TimeoutSec; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -Headers $headers -ErrorAction Stop
            if ($r.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Seconds 1
        if ($i % 5 -eq 0) { Write-Host ('   ...still waiting ({0}s)' -f $i) -ForegroundColor DarkGray }
    }
    return $false
}

# ------------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------------
Write-Host "[Check] Environment..." -ForegroundColor Yellow
if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Virtual env missing: $venvPython" -ForegroundColor Red
    Write-Host "        Run install.bat first." -ForegroundColor Red
    Read-Host 'Press Enter to exit'; exit 1
}
if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
    Write-Host "[ERROR] Frontend deps missing: $frontendDir\node_modules" -ForegroundColor Red
    Write-Host "        Run install.bat first." -ForegroundColor Red
    Read-Host 'Press Enter to exit'; exit 1
}
foreach ($p in 8765, 5173) {
    if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "[WARN] Port $p in use — cleaning up..." -ForegroundColor Yellow
        Stop-OnPort -Port $p
        Start-Sleep -Milliseconds 500
    }
}

# ------------------------------------------------------------------
# 1) Backend (visible window so errors are readable)
# ------------------------------------------------------------------
Write-Host "[1/3] Starting backend..." -ForegroundColor Cyan
$shortBackendDir = $backendDir
$shortUserData   = $userDataDir
$shortVenvPython = $venvPython
$shortToken      = $authToken

$backendCmd = @"
`$env:DESKTOP_AGENT_AUTH_TOKEN = '$shortToken'
`$env:DESKTOP_AGENT_USER_DATA_DIR = '$shortUserData'
`$env:PYTHONIOENCODING = 'utf-8'
Set-Location '$shortBackendDir'
& '$shortVenvPython' start.py
Write-Host ''
Write-Host 'Backend process exited. Press any key to close this window.' -ForegroundColor Yellow
[void][System.Console]::ReadKey(`$true)
"@

$backendProc = Start-Process powershell.exe `
    -ArgumentList @('-NoExit', '-NoProfile', '-Command', $backendCmd) `
    -WindowStyle Normal -PassThru

Write-Host '   Waiting for http://127.0.0.1:8765/api/health ...' -ForegroundColor Gray
if (-not (Wait-HttpReady -Url 'http://127.0.0.1:8765/api/health' -TimeoutSec 30)) {
    Write-Host "[ERROR] Backend not ready after 30s." -ForegroundColor Red
    Write-Host "        Check the backend window (it should still be open)." -ForegroundColor Red
    Write-Host "        Common causes:" -ForegroundColor Yellow
    Write-Host "          - config/models.yaml misconfigured" -ForegroundColor Yellow
    Write-Host "          - Port 8765 held by another process" -ForegroundColor Yellow
    Write-Host "          - Python deps corrupt (re-run install.bat)" -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'; exit 1
}
Write-Host '   [OK] Backend ready' -ForegroundColor Green

# ------------------------------------------------------------------
# 2) Vite dev server
# ------------------------------------------------------------------
Write-Host "[2/3] Starting Vite..." -ForegroundColor Cyan
$shortFrontendDir = $frontendDir

$viteCmd = @"
Set-Location '$shortFrontendDir'
& npx vite --port 5173 --host 127.0.0.1
Write-Host ''
Write-Host 'Vite dev server exited. Press any key to close this window.' -ForegroundColor Yellow
[void][System.Console]::ReadKey(`$true)
"@

$viteProc = Start-Process powershell.exe `
    -ArgumentList @('-NoExit', '-NoProfile', '-Command', $viteCmd) `
    -WindowStyle Normal -PassThru

Write-Host '   Waiting for http://127.0.0.1:5173 ...' -ForegroundColor Gray
if (-not (Wait-HttpReady -Url 'http://127.0.0.1:5173' -TimeoutSec 30)) {
    Write-Host "[ERROR] Vite not ready after 30s.  Check the Vite window." -ForegroundColor Red
    Read-Host 'Press Enter to exit'; exit 1
}
Write-Host '   [OK] Vite ready' -ForegroundColor Green

# ------------------------------------------------------------------
# 3) Electron
# ------------------------------------------------------------------
Write-Host "[3/3] Launching Electron..." -ForegroundColor Cyan
Write-Host '   (Close the Electron window or press Ctrl+C to stop everything)' -ForegroundColor Gray

$env:DESKTOP_AGENT_AUTH_TOKEN = $authToken
$env:NODE_ENV = 'development'
Push-Location $frontendDir
try {
    & npx electron . --dev
} finally {
    Pop-Location
    Write-Host ''
    Write-Host '[Cleanup] Stopping backend & Vite...' -ForegroundColor Yellow
    foreach ($proc in @($backendProc, $viteProc)) {
        if ($proc -and -not $proc.HasExited) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
    Stop-OnPort -Port 8765
    Stop-OnPort -Port 5173
    Write-Host 'All stopped.' -ForegroundColor Gray
}
