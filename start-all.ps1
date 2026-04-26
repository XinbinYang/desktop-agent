# Desktop Agent 一键启动脚本
# 双击此文件即可启动前后端

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $scriptDir "backend"
$frontendDir = Join-Path $scriptDir "frontend"

# 检查后端虚拟环境
$venvPython = Join-Path $backendDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[错误] 后端虚拟环境不存在，请先运行 install.bat 完成安装！" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 检查前端 node_modules
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "[错误] 前端依赖未安装，请先运行 install.bat 完成安装！" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 启动后端（隐藏窗口）
Write-Host "[1/3] 正在启动后端服务..." -ForegroundColor Cyan
$backendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    & .\venv\Scripts\python.exe start.py
} -ArgumentList $backendDir

# 等待后端就绪
$maxWait = 15
$waited = 0
$ready = $false
while ($waited -lt $maxWait) {
    Start-Sleep -Seconds 1
    $waited++
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/models" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
    Write-Host "  等待后端就绪... ($waited/$maxWait)" -ForegroundColor Gray
}

if (-not $ready) {
    Write-Host "[错误] 后端启动超时，查看日志:" -ForegroundColor Red
    Receive-Job $backendJob
    Remove-Job $backendJob
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host "[2/3] 后端已就绪 (http://127.0.0.1:8765)" -ForegroundColor Green

# 启动前端 Vite 开发服务器（后台）
Write-Host "[3/3] 正在启动前端开发服务器和 Electron..." -ForegroundColor Cyan
$viteJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    & npx vite --port 5173 --host
} -ArgumentList $frontendDir

# 等待 Vite 就绪
$viteReady = $false
$viteWait = 0
while ($viteWait -lt 10) {
    Start-Sleep -Seconds 1
    $viteWait++
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $viteReady = $true
            break
        }
    } catch {}
}

if (-not $viteReady) {
    Write-Host "[错误] 前端开发服务器启动超时" -ForegroundColor Red
    Stop-Job $backendJob; Remove-Job $backendJob
    Stop-Job $viteJob; Remove-Job $viteJob
    Read-Host "按 Enter 退出"
    exit 1
}

# 启动 Electron
$env:NODE_ENV = "development"
Start-Process -FilePath "npx" -ArgumentList "electron", ".", "--dev" -WorkingDirectory $frontendDir -NoNewWindow:$false

Write-Host "`n✅ Desktop Agent 已启动！Electron 窗口应该已经打开。" -ForegroundColor Green
Write-Host "   按 Enter 键关闭所有服务并退出..." -ForegroundColor Gray
Read-Host

# 清理
Write-Host "正在关闭所有服务..." -ForegroundColor Yellow
Stop-Job $viteJob -ErrorAction SilentlyContinue
Remove-Job $viteJob -ErrorAction SilentlyContinue
Stop-Job $backendJob -ErrorAction SilentlyContinue
Remove-Job $backendJob -ErrorAction SilentlyContinue
Write-Host "已退出" -ForegroundColor Gray