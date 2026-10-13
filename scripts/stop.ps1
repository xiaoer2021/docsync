# 停掉钉钉文档同步中心
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$vitePath = (Join-Path $root 'frontend\node_modules\vite').Replace('\', '/')

foreach ($port in 8000, 5273) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "端口 $port 上没有服务，跳过。"
        continue
    }
    foreach ($owner in ($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
        $commandLine = [string]$processInfo.CommandLine
        $isApi = $processInfo.ExecutablePath -eq $python -and $commandLine -match 'uvicorn\s+app\.main:app'
        $isWeb = $commandLine.Replace('\', '/').Contains($vitePath)
        if (-not ($isApi -or $isWeb)) {
            Write-Host "端口 $port 由其他程序使用，保留该进程。" -ForegroundColor Yellow
            continue
        }
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
        Write-Host "已停止本项目服务（端口 $port，PID $owner）"
    }
}

Write-Host '完成。' -ForegroundColor Green
