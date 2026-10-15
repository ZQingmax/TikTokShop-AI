# Apply the discovery (7c3e9a1d2f40) and 1688 CLI (a1688c11e001) migrations to the local business DB.
# Both are additive (new tables / nullable or defaulted columns). Verified first on the isolated *_test DB
# by scripts/run-discovery-checks.ps1. Refuses unknown versions; never stamps, never drops; checks row counts.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$logs = Join-Path $projectRoot '.runtime/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
Start-Transcript -Path (Join-Path $logs '1688-migrate.log') -Force | Out-Null
$env:PYTHONUTF8 = '1'
$env:DEBUG = 'false'  # SQL echo would corrupt the JSON status output
$env:DATABASE_URL = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_ops_local'
Push-Location (Join-Path $projectRoot 'backend')
try {
    $before = & $python -m scripts.discovery_db_status | ConvertFrom-Json
    Write-Host "BEFORE: $($before | ConvertTo-Json -Compress)"
    $version = @($before.alembic_version)
    if ($version.Count -ne 1 -or @('554b31562dd4', '7c3e9a1d2f40', 'a1688c11e001') -notcontains $version[0]) { throw "Unexpected version $version; no migration performed." }
    if ($version[0] -ne 'a1688c11e001') {
        & $python -m alembic upgrade a1688c11e001
        if ($LASTEXITCODE -ne 0) { throw 'Migration failed (transaction rolled back by PostgreSQL).' }
    }
    $after = & $python -m scripts.discovery_db_status | ConvertFrom-Json
    Write-Host "AFTER:  $($after | ConvertTo-Json -Compress)"
    foreach ($t in 'users','products','orders','sourcing_candidates','sourcing_analysis_tasks','sourcing_ai_evaluations','sourcing_reviews','sourcing_miaoshou_tasks') {
        if ($before.$t -ne $after.$t) { throw "Row count changed for $t" }
    }
    Write-Host 'Business row counts unchanged. Restart API/Worker: powershell -File scripts/start-sourcing-local.ps1'
} finally { Pop-Location; Stop-Transcript | Out-Null }
