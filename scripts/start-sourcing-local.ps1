$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$backendDirectory = Join-Path $projectRoot 'backend'
$logsPath = Join-Path $projectRoot '.runtime/logs'
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null
$env:DATABASE_URL = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_ops_local'
$env:DEBUG = 'false'
$env:PYTHONUTF8 = '1'
# Preserve the existing local business mock modes; sourcing uses independent providers.
$env:LLM_MOCK_MODE = 'true'
$env:AI_ENABLE_MOCK_AI = 'true'
$env:TIKTOK_SHOP_MOCK_MODE = 'true'
$env:ALIBABA_1688_MOCK_MODE = 'true'

Push-Location $backendDirectory
try {
    & $pythonPath -m scripts.check_sourcing_schema
    if ($LASTEXITCODE -ne 0) { throw 'Sourcing database migration is not ready. No automatic migration performed.' }
} finally { Pop-Location }

function Restart-OwnedService {
    param($Name, $Arguments)
    $pidPath = Join-Path $logsPath "$Name.pid"
    if (Test-Path $pidPath) {
        $savedProcessId = [int](Get-Content -LiteralPath $pidPath)
        $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$savedProcessId"
        if ($existingProcess) {
            $matchesProject = $existingProcess.CommandLine -and $existingProcess.CommandLine.Contains($pythonPath)
            $matchesModule = ($Name -eq 'backend' -and $existingProcess.CommandLine.Contains('uvicorn app.main:app')) -or ($Name -eq 'sourcing-worker' -and $existingProcess.CommandLine.Contains('app.services.sourcing_worker'))
            if (!$matchesProject -or !$matchesModule) { throw "Refusing to stop unrelated PID $savedProcessId" }
            Stop-Process -Id $savedProcessId
            Wait-Process -Id $savedProcessId -Timeout 10 -ErrorAction SilentlyContinue
        }
    }
    $process = Start-Process -FilePath $pythonPath -ArgumentList $Arguments -WorkingDirectory $backendDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsPath "$Name.out.log") -RedirectStandardError (Join-Path $logsPath "$Name.err.log")
    Set-Content -LiteralPath $pidPath -Value $process.Id
    Write-Host "Started $Name (PID $($process.Id))."
}

Restart-OwnedService 'backend' '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'
Restart-OwnedService 'sourcing-worker' '-m app.services.sourcing_worker'
Write-Host 'Sourcing: http://127.0.0.1:3000/sourcing (start-local.ps1 supplies PostgreSQL and Vite)'
