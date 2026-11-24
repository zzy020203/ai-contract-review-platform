# 停止由 start-all.ps1 启动的本地服务（Redis 保持运行，避免影响其他项目）
# 用法：powershell -ExecutionPolicy Bypass -File deploy\scripts\stop-all.ps1
$ErrorActionPreference = 'SilentlyContinue'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$LogDir = Join-Path $Root 'storage\logs'
$PidFile = Join-Path $LogDir 'pids.json'

function Stop-Tree([int]$ProcessId) {
    if (-not $ProcessId) { return }
    $child = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcessId }
    foreach ($c in $child) { Stop-Tree $c.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-Port([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Tree ([int]$conn.OwningProcess)
        Write-Host "[OK] 已停止端口 $Port (pid=$($conn.OwningProcess))"
    }
}

if (Test-Path $PidFile) {
    $pids = Get-Content $PidFile -Raw | ConvertFrom-Json
    foreach ($name in @('backend', 'celery', 'frontend')) {
        $id = $pids.$name
        if ($id) {
            Stop-Tree ([int]$id)
            Write-Host "[OK] 已停止 $name (pid=$id)"
        }
    }
    Remove-Item $PidFile -Force
}

# 兜底：按端口清理残留进程
Stop-Port 8000
Stop-Port 5173

Write-Host '[INFO] Redis 保持运行（如需停止：Stop-Process -Name redis-server）'
Write-Host '本地服务已停止'
