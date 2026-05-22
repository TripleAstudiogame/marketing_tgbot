$NoBrowser = $false
if ($args -contains "-NoBrowser") {
    $NoBrowser = $true
}

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Read-EnvValue {
    param([Parameter(Mandatory=$true)][string]$Key, [string]$Default = "")
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) { return $Default }
    $line = Get-Content -Path $envFile -Encoding UTF8 | Where-Object { $_ -match "^\s*$([regex]::Escape($Key))\s*=" } | Select-Object -Last 1
    if (-not $line) { return $Default }
    return ($line -split "=", 2)[1].Trim()
}

function Wait-ForReady {
    param([string]$Url, [int]$TimeoutSeconds = 75)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 4
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

if (-not (Test-Path ".env")) {
    throw ".env not found. Run START_LOCAL.bat first and complete /admin/setup."
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    PowerShell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup_windows.ps1"
}

$token = Read-EnvValue -Key "TELEGRAM_BOT_TOKEN"
if (-not $token) {
    throw "TELEGRAM_BOT_TOKEN is missing. Open START_LOCAL.bat and configure Telegram first."
}

$port = Read-EnvValue -Key "APP_PORT" -Default "8000"
$readyUrl = "http://127.0.0.1:$port/health/ready"
$adminUrl = "http://127.0.0.1:$port/admin/system"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$outLog = Join-Path $logDir "production_start.log"
$launcher = Join-Path $logDir "run_production_launcher.ps1"
$command = @"
Set-Location '$ProjectRoot'
& '$python' -m app.cli all *>> '$outLog'
"@
$command | Set-Content -Path $launcher -Encoding UTF8

Write-Host "Starting production process..." -ForegroundColor Cyan
Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", $launcher) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Minimized | Out-Null

if (Wait-ForReady -Url $readyUrl -TimeoutSeconds 90) {
    Write-Host "Production server is ready: $readyUrl" -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $adminUrl
    }
    exit 0
}

Write-Host "Production server did not become ready. Open logs\\production_start.log" -ForegroundColor Red
exit 1
