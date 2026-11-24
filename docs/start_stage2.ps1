# 阶段 2 一键启动：Redis + Backend + Celery
# 用法：cd E:\software\project\DocuMind\DocuMind_API
#      powershell -ExecutionPolicy Bypass -File ..\..\Contract_project\docs\start_stage2.ps1

$ErrorActionPreference = "Continue"
$REDIS = "E:\software\redis-windows-7.2.1\redis-server.exe"
$BACKEND_DIR = "E:\software\project\DocuMind\DocuMind_API"
$PY = "$BACKEND_DIR\.venv\Scripts\python.exe"

Write-Host "=== 1/3 起 Redis ===" -ForegroundColor Cyan
$redisCheck = netstat -ano | findstr ":6379" | findstr "LISTENING"
if (-not $redisCheck) {
    Start-Process -FilePath $REDIS -ArgumentList "--port","6379","--protected-mode","no","--daemonize","yes" -WindowStyle Hidden
    Start-Sleep 3
}
& "$BACKEND_DIR\..\..\redis-windows-7.2.1\redis-cli.exe" ping 2>&1

Write-Host "=== 2/3 起 Backend ===" -ForegroundColor Cyan
$beCheck = netstat -ano | findstr ":8000" | findstr "LISTENING"
if (-not $beCheck) {
    Start-Process -FilePath $PY -WorkingDirectory $BACKEND_DIR `
        -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","8000","--log-level","warning" `
        -WindowStyle Hidden
    Start-Sleep 6
}
curl.exe -s -o NUL -w "backend healthz=%{http_code}`n" http://127.0.0.1:8000/api/monitor/healthz

Write-Host "=== 3/3 起 Celery Worker ===" -ForegroundColor Cyan
# 只杀 celery worker 进程（python.exe 命令行带 celery worker）
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $p = $_
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
        if ($cmdLine -match "celery") {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Write-Host "  killed old celery pid=$($p.Id)"
        }
    } catch {}
}

Start-Sleep 1
Start-Process -FilePath $PY -WorkingDirectory $BACKEND_DIR `
    -ArgumentList "-m","celery","-A","worker.celery_app","worker","--pool=solo","--loglevel=info" `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$env:TEMP\celery_stage2.log" `
    -RedirectStandardError "$env:TEMP\celery_stage2_err.log"
Start-Sleep 8
Get-Content "$env:TEMP\celery_stage2.log" -Tail 5

Write-Host "`n=== 全部启动完成 ===" -ForegroundColor Green
Write-Host "  Backend:  http://127.0.0.1:8000"
Write-Host "  Frontend: http://localhost:5173/"
