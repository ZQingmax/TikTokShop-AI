$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$env:DATABASE_URL = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_ops_local'
$env:DEBUG = 'false'
$env:PYTHONUTF8 = '1'

# Stop only services whose PID and command line both identify this checkout.
foreach ($name in @('sourcing-worker', 'backend')) {
    $pidPath = Join-Path $projectRoot ".runtime/logs/$name.pid"
    if (Test-Path -LiteralPath $pidPath) {
        $serviceProcessId = [int](Get-Content -LiteralPath $pidPath)
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$serviceProcessId"
        if ($process) {
            $moduleName = if ($name -eq 'backend') { 'uvicorn app.main:app' } else { 'app.services.sourcing_worker' }
            if (!$process.CommandLine.Contains($pythonPath) -or !$process.CommandLine.Contains($moduleName)) {
                throw "Refusing to stop unrelated PID $serviceProcessId"
            }
            Stop-Process -Id $serviceProcessId
            Wait-Process -Id $serviceProcessId -Timeout 10 -ErrorAction SilentlyContinue
        }
    }
}
Push-Location (Join-Path $projectRoot 'backend')
try {
    & $pythonPath -m scripts.snapshot_sourcing_local
    if ($LASTEXITCODE -ne 0) { throw 'Snapshot failed; migration was not applied' }
    & $pythonPath -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed; inspect the database before restarting services' }
} finally { Pop-Location }
& (Join-Path $PSScriptRoot 'start-sourcing-local.ps1')
