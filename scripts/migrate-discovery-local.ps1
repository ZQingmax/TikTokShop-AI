# Apply ONLY the discovery migration (two new tables) to the local business DB after run-discovery-checks.ps1 passed.
# Refuses unless the DB is exactly at 554b31562dd4 (or already at 7c3e9a1d2f40). Never stamps, never drops.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$logs = Join-Path $projectRoot '.runtime/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
Start-Transcript -Path (Join-Path $logs 'discovery-migrate.log') -Force | Out-Null
$env:PYTHONUTF8 = '1'
$env:DATABASE_URL = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_ops_local'
Push-Location (Join-Path $projectRoot 'backend')
try {
    $before = & $python -m scripts.discovery_db_status | ConvertFrom-Json
    Write-Host "BEFORE: $($before | ConvertTo-Json -Compress)"
    $version = @($before.alembic_version)
    if ($version.Count -ne 1 -or ($version[0] -ne '554b31562dd4' -and $version[0] -ne '7c3e9a1d2f40')) { throw "Unexpected version $version; no migration performed." }
    if ($version[0] -eq '554b31562dd4') {
        & $python -m alembic upgrade 7c3e9a1d2f40
        if ($LASTEXITCODE -ne 0) { throw 'Migration failed (transaction rolled back by PostgreSQL).' }
    }
    $after = & $python -m scripts.discovery_db_status | ConvertFrom-Json
    Write-Host "AFTER:  $($after | ConvertTo-Json -Compress)"
    foreach ($t in 'users','products','orders','sourcing_candidates','sourcing_analysis_tasks','sourcing_ai_evaluations','sourcing_reviews') {
        if ($before.$t -ne $after.$t) { throw "Row count changed for $t" }
    }
    Write-Host 'Business row counts unchanged. Restart API/Worker: powershell -File scripts/start-sourcing-local.ps1'
} finally { Pop-Location; Stop-Transcript | Out-Null }
