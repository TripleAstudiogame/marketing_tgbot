$ErrorActionPreference = "SilentlyContinue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$patterns = @(
    "*$ProjectRoot*app.cli web*",
    "*$ProjectRoot*app.cli all*",
    "*$ProjectRoot*app.cli polling*",
    "*$ProjectRoot*run_local_launcher.ps1*",
    "*$ProjectRoot*run_production_launcher.ps1*"
)

$targets = Get-CimInstance Win32_Process | Where-Object {
    $cmd = $_.CommandLine
    if (-not $cmd) { return $false }
    foreach ($pattern in $patterns) {
        if ($cmd -like $pattern) { return $true }
    }
    return $false
}

if (-not $targets) {
    Write-Host "No Marketing Telegram Bot processes found." -ForegroundColor Yellow
    exit 0
}

foreach ($target in $targets) {
    Write-Host "Stopping PID $($target.ProcessId): $($target.Name)" -ForegroundColor Cyan
    Stop-Process -Id $target.ProcessId -Force
}

Write-Host "Stopped $($targets.Count) process(es)." -ForegroundColor Green
