# 本地一键启动（Windows，无需 Docker）：Redis → 数据库初始化 → 后端 → Celery → 前端
# 用法：powershell -ExecutionPolicy Bypass -File deploy\scripts\start-all.ps1
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$LogDir = Join-Path $Root 'storage\logs'
$PidFile = Join-Path $LogDir 'pids.json'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-ListenerPid([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess } else { return 0 }
}

function Start-Hidden([string]$File, [string[]]$CommandArgs, [string]$WorkDir, [string]$Name) {
    $out = Join-Path $LogDir "$Name.log"
    $err = Join-Path $LogDir "$Name.err.log"
    return Start-Process -FilePath $File -ArgumentList $CommandArgs -WorkingDirectory $WorkDir `
        -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
}

$pids = @{}

# 0) PostgreSQL（conda 安装在项目内 .pg，数据目录 .pgdata）
if ((Get-ListenerPid 5432) -eq 0) {
    $pgCtl = Join-Path $Root '.pg\Library\bin\pg_ctl.exe'
    $pgData = Join-Path $Root '.pgdata'
    if ((Test-Path $pgCtl) -and (Test-Path $pgData)) {
        & $pgCtl -D $pgData -l (Join-Path $LogDir 'postgres.log') start
        Start-Sleep -Seconds 3
        Write-Host '[OK] PostgreSQL 已启动 (127.0.0.1:5432)'
    } else {
        Write-Warning '未找到本地 PostgreSQL（.pg\Library\bin\pg_ctl.exe），请先执行 conda create -p .pg -c conda-forge postgresql=16'
    }
} else {
    Write-Host '[SKIP] PostgreSQL 已在运行 (127.0.0.1:5432)'
}

# 1) Redis（必须关闭 protected-mode，否则 Celery 连接被拒）
if ((Get-ListenerPid 6379) -eq 0) {
    $redisExe = if ($env:REDIS_SERVER) { $env:REDIS_SERVER }
        elseif (Test-Path 'D:\redis\redis-windows-7.2.1\redis-server.exe') { 'D:\redis\redis-windows-7.2.1\redis-server.exe' }
        else { 'E:\software\redis-windows-7.2.1\redis-server.exe' }
    if (Test-Path $redisExe) {
        $p = Start-Hidden $redisExe @('--protected-mode', 'no') (Split-Path $redisExe) 'redis'
        $pids['redis'] = $p.Id
        Write-Host "[OK] Redis 已启动 (pid=$($p.Id))"
        Start-Sleep -Seconds 2
    } else {
        Write-Warning "未找到 redis-server，请设置环境变量 REDIS_SERVER 指向 redis-server.exe"
    }
} else {
    Write-Host '[SKIP] Redis 已在运行 (127.0.0.1:6379)'
}

# 2) 数据库初始化（幂等：建表 + 预置账号/规则 + 权限码同步）
Push-Location (Join-Path $Root 'backend')
try {
    & $Python -m app.db_init
} finally {
    Pop-Location
}

# 3) 后端 FastAPI
if ((Get-ListenerPid 8000) -eq 0) {
    $p = Start-Hidden $Python @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        (Join-Path $Root 'backend') 'backend'
    $pids['backend'] = $p.Id
    Write-Host "[OK] 后端启动中 (pid=$($p.Id)) → http://127.0.0.1:8000"
} else {
    Write-Host '[SKIP] 后端已在运行 (127.0.0.1:8000)'
}

# 4) Celery Worker（Windows 必须 solo 池）
$celeryRunning = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'celery.*app\.worker\.celery_app' }
if (-not $celeryRunning) {
    $p = Start-Hidden $Python @('-m', 'celery', '-A', 'app.worker.celery_app', 'worker', '--pool=solo', '-l', 'info') `
        (Join-Path $Root 'backend') 'celery'
    $pids['celery'] = $p.Id
    Write-Host "[OK] Celery Worker 启动中 (pid=$($p.Id))"
} else {
    Write-Host '[SKIP] Celery Worker 已在运行'
}

# 5) 前端 Vite（只监听 ::1，浏览器必须用 localhost）
if ((Get-ListenerPid 5173) -eq 0) {
    $p = Start-Hidden 'cmd.exe' @('/c', 'npm run dev') (Join-Path $Root 'frontend') 'frontend'
    $pids['frontend'] = $p.Id
    Write-Host "[OK] 前端启动中 (pid=$($p.Id)) → http://localhost:5173/"
} else {
    Write-Host '[SKIP] 前端已在运行 (localhost:5173)'
}

if ($pids.Count -gt 0) {
    $pids | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8
}

# 6) 等待后端健康检查通过
Write-Host '等待后端健康检查...'
$health = $null
for ($i = 0; $i -lt 40; $i++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/healthz' -TimeoutSec 2
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if ($health) {
    Write-Host "[OK] 后端健康检查通过：status=$($health.data.status)"
} else {
    Write-Warning '后端健康检查未通过，请查看 storage\logs\backend.err.log'
}

Write-Host ''
Write-Host '启动完成：'
Write-Host '  前端        http://localhost:5173/'
Write-Host '  后端接口    http://127.0.0.1:8000/api/healthz'
Write-Host '  Prometheus  http://127.0.0.1:8000/api/monitor/prometheus'
Write-Host '  预置账号    admin/admin123、lead/123456、staff/123456'
