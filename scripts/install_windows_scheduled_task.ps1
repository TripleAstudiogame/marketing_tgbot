param(
    [string]$TaskName = "MarketingTelegramBot",
    [string]$Mode = "production"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($Mode -eq "production") {
    $ScriptPath = Join-Path $ProjectRoot "scripts\start_production.ps1"
    $ScriptArgs = "-NoBrowser"
} elseif ($Mode -eq "web") {
    $ScriptPath = Join-Path $ProjectRoot "scripts\run_web.ps1"
    $ScriptArgs = ""
} elseif ($Mode -eq "polling") {
    $ScriptPath = Join-Path $ProjectRoot "scripts\run_polling_worker.ps1"
    $ScriptArgs = ""
} else {
    $ScriptPath = Join-Path $ProjectRoot "scripts\run_local_all.ps1"
    $ScriptArgs = ""
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$ScriptPath`" $ScriptArgs" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force

Write-Host "Scheduled task installed: $TaskName" -ForegroundColor Green
Write-Host "Start it now with: Start-ScheduledTask -TaskName $TaskName"
