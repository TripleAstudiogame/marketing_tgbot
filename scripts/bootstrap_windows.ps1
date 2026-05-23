param(
    [string]$PythonVersion = "3.11.9",
    [string]$PythonInstallerUrl = ""
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

function Test-PythonCommand {
    param([Parameter(Mandatory=$true)][string]$Command)
    try {
        & $Command -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "python"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -like "*\python.exe" -and -not (Test-Path $candidate)) {
            continue
        }
        if (Test-PythonCommand -Command $candidate) {
            return $candidate
        }
    }

    try {
        & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return "py -3.11"
        }
    } catch {
    }

    try {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return "py -3"
        }
    } catch {
    }

    return ""
}

function Install-UserPython {
    if (-not $PythonInstallerUrl) {
        $PythonInstallerUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
    }

    $installerDir = Join-Path $ProjectRoot "data\installers"
    New-Item -ItemType Directory -Force -Path $installerDir | Out-Null
    $installerPath = Join-Path $installerDir "python-$PythonVersion-amd64.exe"

    if (-not (Test-Path $installerPath)) {
        Write-Host "Python 3.11+ was not found. Downloading Python $PythonVersion..." -ForegroundColor Yellow
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $PythonInstallerUrl -OutFile $installerPath
    }

    Write-Host "Installing Python $PythonVersion for current user..." -ForegroundColor Cyan
    $process = Start-Process -FilePath $installerPath `
        -ArgumentList @(
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=1",
            "Include_launcher=1",
            "Include_pip=1",
            "Include_test=0",
            "Shortcuts=0"
        ) `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Python installer failed with exit code $($process.ExitCode)."
    }

    $installed = "$env:LocalAppData\Programs\Python\Python311\python.exe"
    if (Test-Path $installed) {
        return $installed
    }

    $found = Find-Python
    if ($found) {
        return $found
    }
    throw "Python was installed, but python.exe was not found. Restart PowerShell and run START_LOCAL.bat again."
}

function Invoke-PythonSetup {
    param([Parameter(Mandatory=$true)][string]$PythonCommand)
    if ($PythonCommand -like "py -*") {
        $parts = $PythonCommand.Split(" ", 2)
        PowerShell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup_windows.ps1" -PythonCommand $parts[0] -PythonCommandArgs $parts[1]
    } else {
        PowerShell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup_windows.ps1" -PythonCommand $PythonCommand
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Setup failed."
    }
}

function Repair-LegacyAdminPassword {
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) {
        return
    }
    $content = Get-Content -Path $envFile -Encoding UTF8
    $changed = $false
    $content = $content | ForEach-Object {
        if ($_ -match "^\s*ADMIN_PASSWORD\s*=\s*change-me-now\s*$") {
            $changed = $true
            "ADMIN_PASSWORD=admin"
        } else {
            $_
        }
    }
    if ($changed) {
        $content | Set-Content -Path $envFile -Encoding UTF8
        Write-Host "Updated default admin password in .env to admin." -ForegroundColor Yellow
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}
Repair-LegacyAdminPassword

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Write-Host "Virtual environment already exists." -ForegroundColor Green
    exit 0
}

$python = Find-Python
if (-not $python) {
    $python = Install-UserPython
}

Write-Host "Using Python: $python" -ForegroundColor Green
Invoke-PythonSetup -PythonCommand $python

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment was not created: $venvPython"
}

Write-Host "Bootstrap complete." -ForegroundColor Green
