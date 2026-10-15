$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$revision = 'dcd45e7f2b088867551fb10772e32b21f4219193'
$destination = Join-Path $projectRoot '.runtime/fastmoss-upstream'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
# Only the fixed-version, standard-library-only section registry/parser is loaded.
$scriptPath = Join-Path $destination 'sections.py'
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/liangdabiao/fastmoss-rpa-skills/$revision/scripts/sections.py" -OutFile $scriptPath
$digest = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($digest -ne '87db03925fb83d914f7a92ad9b45569a3bc022902b6d297bd0a6cb3ee9025ffd') { throw 'Upstream checksum mismatch' }
@{ revision = $revision; sections_sha256 = $digest; source = 'https://github.com/liangdabiao/fastmoss-rpa-skills' } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destination 'manifest.json') -Encoding utf8
$browserDirectory = Join-Path $projectRoot '.runtime/browserskill'
New-Item -ItemType Directory -Force -Path $browserDirectory | Out-Null
$binary = Join-Path $browserDirectory 'bsk.exe'
if (!(Test-Path -LiteralPath $binary)) {
    $release = 'https://github.com/Tencent/BrowserSkill/releases/download/cli-v0.3.2'
    $manifest = Invoke-RestMethod "$release/version.json"
    $archive = Join-Path $browserDirectory 'bsk-v0.3.2.zip'
    Invoke-WebRequest "$release/bsk-v0.3.2-x86_64-pc-windows-msvc.zip" -OutFile $archive
    $expected = $manifest.assets.'windows-x64'.sha256
    if (!$expected -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $expected) { throw 'BrowserSkill checksum mismatch' }
    Expand-Archive -LiteralPath $archive -DestinationPath $browserDirectory -Force
}
& $binary --version
Write-Host 'FastMoss fixed-version parser and BrowserSkill installed in .runtime. Connect the browser extension and log in to FastMoss.'
