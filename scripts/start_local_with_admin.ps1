$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Read-EnvValue {
    param(
        [Parameter(Mandatory=$true)][string]$Key,
        [string]$Default = ""
    )
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) {
        return $Default
    }
    $line = Get-Content -Path $envFile -Encoding UTF8 | Where-Object { $_ -match "^\s*$([regex]::Escape($Key))\s*=" } | Select-Object -Last 1
    if (-not $line) {
        return $Default
    }
    return ($line -split "=", 2)[1].Trim()
}

function Wait-ForHealth {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$TimeoutSeconds = 45
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Runtime is missing. Running first-time bootstrap..." -ForegroundColor Yellow
    PowerShell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\bootstrap_windows.ps1"
    if ($LASTEXITCODE -ne 0) {
        throw "Bootstrap failed."
    }
}

$port = Read-EnvValue -Key "APP_PORT" -Default "8000"
if (-not $port) {
    $port = "8000"
}
$telegramToken = Read-EnvValue -Key "TELEGRAM_BOT_TOKEN" -Default ""

$healthUrl = "http://127.0.0.1:$port/health"
$adminUrl = "http://127.0.0.1:$port/admin/setup"

try {
    $existing = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
    if ($existing.StatusCode -eq 200) {
        Write-Host "Bot server is already running on port $port." -ForegroundColor Green
        Start-Process $adminUrl
        exit 0
    }
} catch {
}

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$outLog = Join-Path $logDir "local_start_out.log"
$errLog = Join-Path $logDir "local_start_err.log"
$launcher = Join-Path $logDir "run_local_launcher.ps1"
$mode = "all"
if (-not $telegramToken) {
    $mode = "web"
    Write-Host "Telegram token is not configured yet. Starting setup-only web mode." -ForegroundColor Yellow
}
$command = @"
Set-Location '$ProjectRoot'
& '$python' -m app.cli $mode *>> '$outLog'
"@
$command | Set-Content -Path $launcher -Encoding UTF8

Write-Host "Starting server..." -ForegroundColor Cyan
Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", $launcher) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Normal | Out-Null

if (Wait-ForHealth -Url $healthUrl -TimeoutSeconds 60) {
    Write-Host "Server is ready: $healthUrl" -ForegroundColor Green
    Write-Host "Opening admin panel: $adminUrl" -ForegroundColor Green
    Start-Process $adminUrl
    exit 0
}

Write-Host "Server did not become ready in time." -ForegroundColor Red
Write-Host "Check logs:" -ForegroundColor Yellow
Write-Host "  $outLog"
Write-Host "  $errLog"
exit 1
