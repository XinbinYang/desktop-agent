# Desktop Agent 一键安装脚本
# 首次运行前执行此脚本

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ErrorActionPreference = "Stop"

function Test-Command($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Desktop Agent 一键安装" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 检查环境
Write-Host "`n[检查环境]" -ForegroundColor Yellow
if (-not (Test-Command python)) {
    Write-Host "[错误] 未检测到 Python，请先安装 Python 3.11+" -ForegroundColor Red
    exit 1
}
if (-not (Test-Command node)) {
    Write-Host "[错误] 未检测到 Node.js，请先安装 Node.js 18+" -ForegroundColor Red
    exit 1
}

Write-Host "Python: $(python --version 2>&1)" -ForegroundColor Green
Write-Host "Node: $(node --version)" -ForegroundColor Green

# 安装后端
Write-Host "`n[1/4] 安装后端依赖..." -ForegroundColor Cyan
Set-Location (Join-Path $scriptDir "backend")
if (-not (Test-Path "venv")) {
    python -m venv venv
}
& .\venv\Scripts\python.exe -m pip install --upgrade pip
& .\venv\Scripts\pip.exe install -r requirements.txt

# 安装 Playwright
Write-Host "`n[2/4] 安装 Playwright 浏览器..." -ForegroundColor Cyan
& .\venv\Scripts\python.exe -m playwright install chromium

# 安装前端
Write-Host "`n[3/4] 安装前端依赖..." -ForegroundColor Cyan
Set-Location (Join-Path $scriptDir "frontend")
& npm install

# 配置检查
Write-Host "`n[4/4] 检查配置..." -ForegroundColor Cyan
$configPath = Join-Path $scriptDir "config\models.yaml"
$content = Get-Content $configPath -Raw
if ($content -match '\$\{([^}]+)\}') {
    Write-Host "[提示] 检测到配置使用了环境变量，请确保已设置:" -ForegroundColor Yellow
    Write-Host "  [Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'sk-xxx', 'User')" -ForegroundColor Gray
    Write-Host "  或在 config/models.yaml 中直接写入 API Key" -ForegroundColor Gray
}

Write-Host "`n=========================================" -ForegroundColor Green
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "  启动方式: 双击 start-all.bat" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Read-Host "按 Enter 退出"