# 启动钉钉文档同步中心（后台运行，不占用命令行窗口）






$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$logDir = Join-Path $root 'data'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$apiLog = Join-Path $logDir 'api.log'
$webLog = Join-Path $logDir 'web.log'

$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "找不到 Python 环境：$python" -ForegroundColor Red
    Write-Host "先按 README 建一次虚拟环境。" -ForegroundColor Yellow
    exit 1
}

function Test-Port($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $conn
}
function Assert-ProjectPort($port) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
        $line = [string]$processInfo.CommandLine
        $isApi = $processInfo.ExecutablePath -eq $python -and $line -match 'uvicorn\s+app\.main:app'
        $isWeb = $line.Replace('\', '/').Contains((Join-Path $root 'frontend\node_modules\vite').Replace('\', '/'))
        if (-not ($isApi -or $isWeb)) { throw "端口 $port 已被其他程序占用，请先调整配置。" }
    }
}
Assert-ProjectPort 8000
Assert-ProjectPort 5273
if (-not (Test-Path (Join-Path $root 'frontend\node_modules\vite'))) {
    throw '前端依赖尚未安装，请先在 frontend 目录执行 npm ci。'
}
Push-Location (Join-Path $root 'backend')
try {
    & $python -m app.cli check
    if ($LASTEXITCODE -ne 0) { throw '初始化检查未通过，请先按 README 执行配置生成和 setup。' }
} finally {
    Pop-Location
}

if (Test-Port 8000) {
    Write-Host '本项目后端已经在运行，跳过启动。' -ForegroundColor Yellow
} else {
    Write-Host '正在启动后端...'
    Start-Process -FilePath $python -ArgumentList '-u', '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000' -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden -RedirectStandardOutput $apiLog -RedirectStandardError (Join-Path $logDir 'api.err.log')
}

if (Test-Port 5273) {
    Write-Host '本项目前端已经在运行，跳过启动。' -ForegroundColor Yellow
} else {
    Write-Host '正在启动前端...'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm', 'run', 'dev', '--', '--host', '0.0.0.0', '--port', '5273' -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -RedirectStandardOutput $webLog -RedirectStandardError (Join-Path $logDir 'web.err.log')
}

Write-Host '等待服务就绪...'
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    if ((Test-Port 8000) -and (Test-Port 5273)) {
        $ok = $true
        break
    }
}
Start-Sleep -Seconds 2

$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $ip) { $ip = '127.0.0.1' }

Write-Host ''
if ($ok) {
    Write-Host '启动完成。' -ForegroundColor Green
} else {
    Write-Host '端口还没就绪，可能启动慢或者失败了。看日志：' -ForegroundColor Yellow
    Write-Host "  $apiLog"
    Write-Host "  $webLog"
}

Write-Host "  本机访问：http://127.0.0.1:5273"
Write-Host "  内网访问：http://${ip}:5273"
Write-Host "  接口文档：http://${ip}:8000/api/docs"
Write-Host ''
Write-Host '服务在后台跑，关掉这个窗口不影响。要停就双击 stop.bat。' -ForegroundColor Cyan

Start-Process 'http://127.0.0.1:5273'
