$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$pgCtlPath = Join-Path $projectRoot '.runtime/postgres/node_modules/@embedded-postgres/windows-x64/native/bin/pg_ctl.exe'
$pgDataPath = Join-Path $projectRoot '.runtime/pgdata'
$logsPath = Join-Path $projectRoot '.runtime/logs'

if (!(Test-Path $pythonPath) -or !(Test-Path $pgCtlPath) -or !(Test-Path $pgDataPath)) {
    throw 'Local dependencies are missing. See docs/LOCAL_STARTUP.md.'
}
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null

& $pgCtlPath -D $pgDataPath status *> $null
if ($LASTEXITCODE -ne 0) {
    & $pgCtlPath -D $pgDataPath -l (Join-Path $logsPath 'postgres.log') -o '-h 127.0.0.1 -p 5433' -w start
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL failed to start.' }
}

$env:DATABASE_URL = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_ops_local'
$env:DEBUG = 'false'
$env:APP_ENV = 'development'
$env:LLM_MOCK_MODE = 'true'
$env:AI_ENABLE_MOCK_AI = 'true'
$env:TIKTOK_SHOP_MOCK_MODE = 'true'
$env:ALIBABA_1688_MOCK_MODE = 'true'
$env:VITE_BACKEND_PROXY_TARGET = 'http://127.0.0.1:8000'
$env:PYTHONUTF8 = '1'

Push-Location (Join-Path $projectRoot 'backend')
try {
    & $pythonPath -m scripts.bootstrap_local
    if ($LASTEXITCODE -ne 0) { throw 'Local database initialization failed.' }
} finally { Pop-Location }

function Start-LocalService {
    param($Name, $Executable, $Arguments, $Directory, $Port)
    $portOpen = $false
    $probe = [System.Net.Sockets.TcpClient]::new()
    try { $probe.Connect('127.0.0.1', $Port); $portOpen = $true } catch {} finally { $probe.Dispose() }
    if ($portOpen) { Write-Host "$Name port $Port is already in use; no duplicate process started."; return }
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsPath "$Name.out.log") -RedirectStandardError (Join-Path $logsPath "$Name.err.log")
    Set-Content -LiteralPath (Join-Path $logsPath "$Name.pid") -Value $process.Id
    Write-Host "Started $Name (PID $($process.Id))."
}

Start-LocalService 'backend' $pythonPath '-m uvicorn app.main:app --host 127.0.0.1 --port 8000' (Join-Path $projectRoot 'backend') 8000
$nodePath = (Get-Command node.exe).Source
Start-LocalService 'frontend' $nodePath 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000 --strictPort' (Join-Path $projectRoot 'frontend') 3000
Write-Host 'Frontend: http://127.0.0.1:3000'
Write-Host 'Backend: http://127.0.0.1:8000/v1/health'
Write-Host 'AI Agent is not started. Customer service uses local mock responses.'
