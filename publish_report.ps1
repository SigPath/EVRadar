# Publikuje out/index.html na gałąź gh-pages (GitHub Pages). Użycie: .\publish_report.ps1 [-Scan]
param([switch]$Scan)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Scan) {
    & ".venv\Scripts\evradar.exe" run --no-open
    if ($LASTEXITCODE -ne 0) { throw "Skan zakonczyl sie bledem." }
}

$report = Join-Path $PSScriptRoot "out\index.html"
if (-not (Test-Path $report)) { throw "Brak out\index.html - uruchom skan (-Scan)." }

$remote = git remote get-url origin
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("evradar-pages-" + [guid]::NewGuid())
try {
    git ls-remote --exit-code --heads origin gh-pages *> $null
    if ($LASTEXITCODE -eq 0) {
        git clone --quiet --branch gh-pages --single-branch --depth 1 $remote $tmp
    } else {
        git init --quiet $tmp
        git -C $tmp checkout --quiet -b gh-pages
        git -C $tmp remote add origin $remote
    }
    Copy-Item $report (Join-Path $tmp "index.html") -Force
    New-Item -ItemType File -Path (Join-Path $tmp ".nojekyll") -Force | Out-Null
    git -C $tmp add -A
    git -C $tmp diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Write-Host "Raport bez zmian - nic do publikacji."; return }
    git -C $tmp commit --quiet -m ("Raport " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
    git -C $tmp push origin gh-pages
    Write-Host "Opublikowano na gałąź gh-pages."
} finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
}
