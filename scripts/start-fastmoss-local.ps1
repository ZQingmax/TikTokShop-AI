$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$backendDirectory = Join-Path $projectRoot 'backend'
$logsPath = Join-Path $projectRoot '.runtime/logs'
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null
$env:DATABASE_URL = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_ops_local'
$env:DEBUG = 'false'
$env:PYTHONUTF8 = '1'
$env:BSK_AUTO_START = '0'
$bskPath = if ($env:FASTMOSS_BSK_BIN) { $env:FASTMOSS_BSK_BIN } else { Join-Path $projectRoot '.runtime/browserskill/bsk.exe' }
if (!(Test-Path -LiteralPath $bskPath)) { throw 'Run scripts/install-fastmoss.ps1 first or set FASTMOSS_BSK_BIN.' }
# Foreground daemon in a hidden background process works under Windows Job Object hosts.
& $bskPath status --json | Out-Null
if ($LASTEXITCODE -ne 0) {
    $daemon = Start-Process -FilePath $bskPath -ArgumentList 'daemon start --foreground' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsPath 'bsk-daemon.out.log') -RedirectStandardError (Join-Path $logsPath 'bsk-daemon.err.log')
    Set-Content -LiteralPath (Join-Path $logsPath 'bsk-daemon.pid') -Value $daemon.Id
    Start-Sleep -Seconds 2
    & $bskPath status --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'BrowserSkill daemon failed to start; see .runtime/logs/bsk-daemon.err.log' }
}
$pidPath = Join-Path $logsPath 'fastmoss-worker.pid'
if (Test-Path -LiteralPath $pidPath) {
    $savedProcessId = [int](Get-Content -LiteralPath $pidPath)
    $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$savedProcessId"
    if ($existingProcess) {
        if ($existingProcess.CommandLine -and $existingProcess.CommandLine.Contains($pythonPath) -and $existingProcess.CommandLine.Contains('app.services.fastmoss.worker')) {
            Write-Host "FastMoss Worker already running (PID $savedProcessId)."
            exit 0
        }
        throw 'Saved PID belongs to another process. Check .runtime/logs/fastmoss-worker.pid.'
    }
}
Push-Location $backendDirectory
try {
    & $pythonPath -m scripts.check_fastmoss
    if ($LASTEXITCODE -ne 0) { throw 'FastMoss prerequisites failed. See diagnostics above.' }
} finally { Pop-Location }
$process = Start-Process -FilePath $pythonPath -ArgumentList '-m app.services.fastmoss.worker' -WorkingDirectory $backendDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsPath 'fastmoss-worker.out.log') -RedirectStandardError (Join-Path $logsPath 'fastmoss-worker.err.log')
Set-Content -LiteralPath $pidPath -Value $process.Id
Write-Host "Started FastMoss Worker (PID $($process.Id))."
