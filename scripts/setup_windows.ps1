param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Invoke-Native {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $Arguments"
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Edit it before production use." -ForegroundColor Yellow
}

if (-not (Test-Path ".venv")) {
    Invoke-Native $PythonCommand -m venv .venv
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
Invoke-Native $Python -m pip install --upgrade pip
Invoke-Native $Python -m pip install -r requirements.txt
Invoke-Native $Python -m playwright install chromium

New-Item -ItemType Directory -Force -Path "data","logs","reports" | Out-Null
Invoke-Native $Python -m app.cli init-db

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Edit .env, then run scripts\run_local_all.ps1"
