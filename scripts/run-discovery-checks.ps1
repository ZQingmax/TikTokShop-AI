# Discovery agent verification. Touches ONLY the isolated *_test database; business data is read-only here.
# Usage (project root):  powershell -ExecutionPolicy Bypass -File scripts/run-discovery-checks.ps1 [-Probe]
param([switch]$Probe, [switch]$SkipFrontend)
$ErrorActionPreference = 'Continue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$pgCtl = Join-Path $projectRoot '.runtime/postgres/node_modules/@embedded-postgres/windows-x64/native/bin/pg_ctl.exe'
$pgData = Join-Path $projectRoot '.runtime/pgdata'
$logs = Join-Path $projectRoot '.runtime/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs 'discovery-checks.log'
Start-Transcript -Path $log -Force | Out-Null
$env:PYTHONUTF8 = '1'
$results = [ordered]@{}
function Step($name, [scriptblock]$block) {
    Write-Host "`n===== $name ====="
    & $block
    $results[$name] = if ($LASTEXITCODE -eq 0) { 'PASS' } else { "FAIL (exit $LASTEXITCODE)" }
}

& $pgCtl -D $pgData status *> $null
if ($LASTEXITCODE -ne 0) {
    & $pgCtl -D $pgData -l (Join-Path $logs 'postgres.log') -o '-h 127.0.0.1 -p 5433' -w start
}

$business = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_ops_local'
$test = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_sourcing_test'
Push-Location (Join-Path $projectRoot 'backend')
try {
    $env:DATABASE_URL = $business
    $env:TEST_DATABASE_URL = $test
    Step 'prepare isolated test database' { & $python -m scripts.prepare_test_database }
    $env:DATABASE_URL = $test
    Step 'alembic heads (expect single a1688c11e001)' { & $python -m alembic heads }
    Step 'alembic upgrade head on TEST db' { & $python -m alembic upgrade head }
    Step 'alembic check on TEST db' { & $python -m alembic check }
    $env:DATABASE_URL = $business
    $env:DEBUG = 'true'
    Step 'unit tests' { & $python -m pytest unit_tests -q -p no:cacheprovider }
    Step 'integration + regression tests (isolated PostgreSQL)' { & $python -m pytest tests -q -p no:cacheprovider }
    $env:DEBUG = 'false'
    Step 'business db status (read-only)' { & $python -m scripts.discovery_db_status }
    if ($Probe) { Step '1688 CLI status (read-only, no search)' { & $python -m scripts.check_1688_cli } }
} finally { Pop-Location }

if (!$SkipFrontend) {
    Push-Location (Join-Path $projectRoot 'frontend')
    try { Step 'frontend build (vue-tsc + vite)' { npm.cmd run build } } finally { Pop-Location }
}
Write-Host "`n===== SUMMARY ====="
$results.GetEnumerator() | ForEach-Object { Write-Host ("{0,-55} {1}" -f $_.Key, $_.Value) }
Stop-Transcript | Out-Null
Write-Host "Log: $log"
