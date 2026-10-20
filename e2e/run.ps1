# End-to-end browser tests. Run from anywhere:   powershell -File e2e\run.ps1 [-SkipBuild] [-Only phase5]
#
# What it does:
#   1. creates a THROWAWAY SQLite database (e2e\.data\e2e.db), applies the migrations and seeds test users
#   2. (re)builds the frontend, starts the backend and the frontend on it
#   3. runs every file in e2e\tests\ in a headless browser
#   4. stops the servers IT started (and only those: your own dev servers are never touched)
# Your real database (Supabase) is never touched. The tests read data from your real PostHog project.
#
# Ports: the tests use their OWN ports, 3100 (dashboard) and 8100 (API), so they never meet the servers you run yourself
# on 3000 / 8000. To use other ports:   $env:E2E_FRONTEND_PORT = "3200"; $env:E2E_BACKEND_PORT = "8200"

param([switch]$SkipBuild, [string]$Only = "")

# Native programs (alembic, node...) write progress to stderr: that is not an error. We check exit codes instead.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$fePort = if ($env:E2E_FRONTEND_PORT) { $env:E2E_FRONTEND_PORT } else { "3100" }
$bePort = if ($env:E2E_BACKEND_PORT) { $env:E2E_BACKEND_PORT } else { "8100" }
$env:E2E_API_URL = "http://localhost:$bePort"           # where the browser tests find the API
$env:FRONTEND_URL = "http://localhost:$fePort"          # the backend allows exactly this address (CORS, links in emails)
$env:E2E_FRONTEND_URL = "http://localhost:$fePort"      # where the browser tests go
$data = Join-Path $PSScriptRoot ".data"
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force $data | Out-Null

# The servers THIS script starts are written down (process id | what its command line must contain), and only those are
# ever stopped. (An earlier version stopped everything that looked like a Next.js or uvicorn server, which also stopped a
# developer's own `npm run dev`.) The command-line check protects against a recycled process id after a crashed run.
$pidFile = Join-Path $data "pids.txt"

function Stop-Servers {
    if (-not (Test-Path $pidFile)) { return }
    foreach ($line in Get-Content $pidFile) {
        $id, $expected = $line -split '\|', 2
        if ($id -notmatch '^\d+$') { continue }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if ($process -and $process.CommandLine -match $expected) {
            cmd /c "taskkill /PID $id /T /F >nul 2>&1"   # /T = the whole tree (npx starts node, which starts the server)
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

function Assert-PortFree($port, $what) {
    $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($busy) {
        $who = (Get-CimInstance Win32_Process -Filter "ProcessId=$($busy.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine
        throw "Port $port ($what) is already in use by: $who`nStop that program, or run the tests on other ports: `$env:E2E_FRONTEND_PORT / `$env:E2E_BACKEND_PORT"
    }
}

Stop-Servers   # leftovers of an earlier run of THIS script (a crash)
Assert-PortFree $bePort "the API for the tests"
Assert-PortFree $fePort "the dashboard for the tests"

# 1. throwaway database
$db = Join-Path $data "e2e.db"
Remove-Item $db -ErrorAction SilentlyContinue
$env:DATABASE_URL = "sqlite:///" + ($db -replace '\\', '/')
$env:SCHEDULER_ENABLED = "false"
$env:NEXT_PUBLIC_API_URL = "http://localhost:$bePort"   # the browser tests call the backend directly (no proxy)
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
$backend = Start-Process -FilePath $py -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', $bePort -WorkingDirectory (Join-Path $root "backend") `
    -RedirectStandardOutput (Join-Path $data "backend.out.log") -RedirectStandardError $backendLog -WindowStyle Hidden -PassThru
$frontend = Start-Process -FilePath "npx.cmd" -ArgumentList 'next', 'start', '-p', $fePort -WorkingDirectory (Join-Path $root "frontend") `
    -RedirectStandardOutput (Join-Path $data "frontend.out.log") -RedirectStandardError (Join-Path $data "frontend.err.log") -WindowStyle Hidden -PassThru
@("$($backend.Id)|uvicorn app.main:app", "$($frontend.Id)|next start") | Set-Content $pidFile
$ready = $false
for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $backendUp = (Invoke-WebRequest http://127.0.0.1:$bePort/health -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200
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
