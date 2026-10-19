# End-to-end browser tests. Run from anywhere:   powershell -File e2e\run.ps1 [-SkipBuild] [-Only phase5]
#
# What it does:
#   1. creates a THROWAWAY SQLite database (e2e\.data\e2e.db), applies the migrations and seeds test users
#   2. (re)builds the frontend, starts the backend and the frontend on it
#   3. runs every file in e2e\tests\ in a headless browser
#   4. stops the servers
# Your real database (Supabase) is never touched. The tests read data from your real PostHog project.

param([switch]$SkipBuild, [string]$Only = "")

# Native programs (alembic, node...) write progress to stderr: that is not an error. We check exit codes instead.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
# The dashboard normally runs on port 3000. If something else already uses it, run the tests on another port:
#   $env:E2E_FRONTEND_PORT = "3100"; powershell -File e2e\run.ps1
$fePort = if ($env:E2E_FRONTEND_PORT) { $env:E2E_FRONTEND_PORT } else { "3000" }
$env:FRONTEND_URL = "http://localhost:$fePort"        # the backend allows exactly this address (CORS, links in emails)
$env:E2E_FRONTEND_URL = "http://localhost:$fePort"    # where the browser tests go
$data = Join-Path $PSScriptRoot ".data"
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force $data | Out-Null

function Stop-Servers {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn app.main:app|next.*start|next-server' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

Stop-Servers
Start-Sleep -Seconds 1

# 1. throwaway database
$db = Join-Path $data "e2e.db"
Remove-Item $db -ErrorAction SilentlyContinue
$env:DATABASE_URL = "sqlite:///" + ($db -replace '\\', '/')
$env:SCHEDULER_ENABLED = "false"
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"   # the browser tests call the backend directly (no proxy)
# Safety: the browser tests must never use your real keys, whatever is in backend\.env (an env variable wins over .env).
$env:ANTHROPIC_API_KEY = ""
$env:SMTP_HOST = ""
$env:WHATSAPP_ACCESS_TOKEN = "e2e-not-a-real-token"      # fake values, only so the WhatsApp fields appear in Settings
$env:WHATSAPP_PHONE_NUMBER_ID = "0000000000"
Push-Location (Join-Path $root "backend")
$migrationLog = & $py -m alembic upgrade head 2>&1
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "migrations failed: $migrationLog" }
$seedOutput = & $py (Join-Path $PSScriptRoot "seed.py") 2>&1
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "seeding failed: $seedOutput" }
$env:E2E_IDS = ($seedOutput | Where-Object { "$_" -like "{*" } | Select-Object -Last 1)
Pop-Location

# 2. servers
if (-not $SkipBuild) {
    Push-Location (Join-Path $root "frontend")
    npx next build 2>&1 | Select-String -Pattern "Compiled successfully|Failed|rror" | Select-Object -First 3
    Pop-Location
}
$backendLog = Join-Path $data "backend.log"
Remove-Item $backendLog, (Join-Path $data "backend.out.log") -ErrorAction SilentlyContinue
Start-Process -FilePath $py -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8000' -WorkingDirectory (Join-Path $root "backend") `
    -RedirectStandardOutput (Join-Path $data "backend.out.log") -RedirectStandardError $backendLog -WindowStyle Hidden
Start-Process -FilePath "npx.cmd" -ArgumentList 'next', 'start', '-p', $fePort -WorkingDirectory (Join-Path $root "frontend") `
    -RedirectStandardOutput (Join-Path $data "frontend.out.log") -RedirectStandardError (Join-Path $data "frontend.err.log") -WindowStyle Hidden
$ready = $false
for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $backendUp = (Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200
        $frontendUp = (Invoke-WebRequest http://127.0.0.1:$fePort/login -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
        $ready = $backendUp -and $frontendUp
    } catch { $lastError = $_.Exception.Message }
}
if (-not $ready) { Stop-Servers; throw "servers did not start: $lastError (see e2e\.data\*.log)" }

# 3. tests
$env:E2E_BACKEND_LOG = $backendLog
$failed = @()
foreach ($test in Get-ChildItem (Join-Path $PSScriptRoot "tests\*.mjs") | Sort-Object Name) {
    if ($Only -and $test.Name -notlike "*$Only*") { continue }
    $env:E2E_OUT = Join-Path $data ("shots-" + $test.BaseName)
    node $test.FullName
    if ($LASTEXITCODE -ne 0) { $failed += $test.Name }
}

# 4. done
Stop-Servers
if ($failed.Count -gt 0) { Write-Host "`nFAILED: $($failed -join ', ')  (screenshots and logs in e2e\.data)" -ForegroundColor Red; exit 1 }
Write-Host "`nAll browser tests passed." -ForegroundColor Green
