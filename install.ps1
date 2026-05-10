# Desktop Agent 一键安装脚本
# 双击 install.bat 即可安装；也可在 PowerShell 中直接运行 .\install.ps1。

$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }

$backendDir  = Join-Path $scriptDir 'backend'
$frontendDir = Join-Path $scriptDir 'frontend'
$venvDir     = Join-Path $backendDir 'venv'
$venvPython  = Join-Path $venvDir 'Scripts\python.exe'
$venvPip     = Join-Path $venvDir 'Scripts\pip.exe'

$failures = @()

function Test-Command($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Run-Step {
    param([string]$Label, [scriptblock]$Block)
    Write-Host "`n>>> $Label" -ForegroundColor Cyan
    try {
        & $Block
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
            throw "命令返回非零退出码: $LASTEXITCODE"
        }
        Write-Host "    [OK]" -ForegroundColor Green
    } catch {
        Write-Host "    [失败] $($_.Exception.Message)" -ForegroundColor Red
        $script:failures += $Label
    }
}

Write-Host '=========================================' -ForegroundColor Cyan
Write-Host '  Desktop Agent 一键安装' -ForegroundColor Cyan
Write-Host '=========================================' -ForegroundColor Cyan

# ===== 前置检查 =====
Write-Host "`n[检查] 必需工具..." -ForegroundColor Yellow

if (-not (Test-Command python)) {
    Write-Host "[错误] 未检测到 python.exe，请先安装 Python 3.11+ 并加入 PATH" -ForegroundColor Red
    Write-Host "       下载: https://www.python.org/downloads/" -ForegroundColor Red
    Read-Host '按 Enter 退出'; exit 1
}
if (-not (Test-Command node)) {
    Write-Host "[错误] 未检测到 node.exe，请先安装 Node.js 18+ 并加入 PATH" -ForegroundColor Red
    Write-Host "       下载: https://nodejs.org/" -ForegroundColor Red
    Read-Host '按 Enter 退出'; exit 1
}
if (-not (Test-Command npm)) {
    Write-Host "[错误] 未检测到 npm（通常随 Node.js 一同安装）" -ForegroundColor Red
    Read-Host '按 Enter 退出'; exit 1
}

Write-Host "  Python: $(python --version 2>&1)" -ForegroundColor Green
Write-Host "  Node:   $(node --version)" -ForegroundColor Green
Write-Host "  npm:    $(npm --version 2>&1)" -ForegroundColor Green

# ===== 1) 创建/复用后端 venv =====
Run-Step '创建后端虚拟环境' {
    if (-not (Test-Path $venvPython)) {
        Push-Location $backendDir
        try { & python -m venv venv } finally { Pop-Location }
    } else {
        Write-Host "    venv 已存在，跳过创建" -ForegroundColor DarkGray
    }
    if (-not (Test-Path $venvPython)) {
        throw "venv 创建失败：$venvPython 不存在"
    }
}

# ===== 2) 安装后端依赖 =====
Run-Step '升级 pip' {
    & $venvPython -m pip install --upgrade pip
}

Run-Step '安装 Python 依赖 (requirements.txt, ~3-8 分钟)' {
    & $venvPip install -r (Join-Path $backendDir 'requirements.txt')
}

# ===== 3) 安装 Playwright Chromium =====
Run-Step '安装 Playwright Chromium (~150MB)' {
    & $venvPython -m playwright install chromium
}

# ===== 4) 安装前端依赖 =====
Run-Step '安装前端依赖 (npm install)' {
    Push-Location $frontendDir
    try { & npm install } finally { Pop-Location }
}

# ===== 5) 配置提示 =====
$configPath = Join-Path $scriptDir 'config\models.yaml'
if (Test-Path $configPath) {
    $content = Get-Content $configPath -Raw
    if ($content -match '\$\{([^}]+)\}') {
        Write-Host "`n[提示] config\models.yaml 使用了环境变量。" -ForegroundColor Yellow
        Write-Host "       启动后请在【设置】面板填写各 Provider 的 API Key，" -ForegroundColor Yellow
        Write-Host "       或用环境变量预设 (PowerShell):" -ForegroundColor Yellow
        Write-Host "         [Environment]::SetEnvironmentVariable('OPENAI_API_KEY','sk-...','User')" -ForegroundColor Gray
    }
}

# ===== 总结 =====
Write-Host "`n=========================================" -ForegroundColor Cyan
if ($failures.Count -eq 0) {
    Write-Host '  ✅ 安装完成！' -ForegroundColor Green
    Write-Host '  双击 start-all.bat 启动应用' -ForegroundColor Green
} else {
    Write-Host '  ⚠ 部分步骤失败:' -ForegroundColor Yellow
    foreach ($f in $failures) { Write-Host "    - $f" -ForegroundColor Yellow }
    Write-Host '  请根据上面的错误信息排查后重试。' -ForegroundColor Yellow
}
Write-Host '=========================================' -ForegroundColor Cyan
Read-Host '按 Enter 退出'
