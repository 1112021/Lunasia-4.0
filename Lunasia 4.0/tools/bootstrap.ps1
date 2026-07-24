param(
    [switch]$Fast
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvDir = Join-Path $PSScriptRoot "app_env"
$EnvPython = Join-Path $EnvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$DependencyStamp = Join-Path $EnvDir ".requirements.sha256"

function Stop-WithMessage([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host "Python download: https://www.python.org/downloads/"
    exit 1
}

function Test-NativeCommand([scriptblock]$Command) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $Command *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $oldPreference
    }
}

function Get-SystemPython {
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($py -and (Test-NativeCommand { & $py.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" })) {
        return @{
            Command = $py.Source
            Args = @("-3")
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python -and (Test-NativeCommand { & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" })) {
        return @{
            Command = $python.Source
            Args = @()
        }
    }

    return $null
}

Set-Location $ProjectRoot
Write-Host ""
Write-Host "========================================"
Write-Host "          Lunasia AI Assistant"
Write-Host "========================================"
Write-Host ""

if (-not (Test-Path (Join-Path $ProjectRoot "main.py"))) {
    Stop-WithMessage "main.py was not found. Extract the complete project before starting."
}
if (-not (Test-Path $Requirements)) {
    Stop-WithMessage "requirements.txt was not found. Extract the complete project before starting."
}

if ($Fast) {
    if (-not (Test-Path $EnvPython)) {
        Stop-WithMessage "The app environment is missing. Run Start Lunasia first."
    }
} else {
    if (-not (Test-Path $EnvPython)) {
        $systemPython = Get-SystemPython
        if (-not $systemPython) {
            Stop-WithMessage "Python 3.8 or newer was not found. Install Python and enable Add Python to PATH."
        }

        Write-Host "[1/3] Creating the private app environment..."
        $pythonCommand = $systemPython.Command
        $pythonArgs = $systemPython.Args
        & $pythonCommand @pythonArgs -m venv $EnvDir
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $EnvPython)) {
            Stop-WithMessage "Could not create the private app environment."
        }

        & $EnvPython -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
        if ($LASTEXITCODE -ne 0) {
            Stop-WithMessage "Could not prepare pip. Check the network connection and try again."
        }
    } else {
        Write-Host "[1/3] Private app environment found."
    }

    $requirementsHash = (Get-FileHash -Algorithm SHA256 $Requirements).Hash
    $installedHash = ""
    if (Test-Path $DependencyStamp) {
        $installedHash = (Get-Content $DependencyStamp -Raw).Trim()
    }

    if ($requirementsHash -ne $installedHash) {
        Write-Host "[2/3] Installing or updating app dependencies..."
        Write-Host "This can take several minutes on the first run."
        & $EnvPython -m pip install --disable-pip-version-check -r $Requirements
        if ($LASTEXITCODE -ne 0) {
            Stop-WithMessage "Dependency installation failed. Check the network output above and try again."
        }
        Set-Content -Path $DependencyStamp -Value $requirementsHash -Encoding ASCII
    } else {
        Write-Host "[2/3] App dependencies are up to date."
    }
}

if (-not (Test-NativeCommand { & $EnvPython -c "import PyQt5, requests, openai" })) {
    if ($Fast) {
        Stop-WithMessage "The app environment is incomplete. Run Start Lunasia to repair it."
    }
    Stop-WithMessage "The app environment did not pass verification."
}

Write-Host "[3/3] Starting Lunasia..."
Write-Host ""
& $EnvPython (Join-Path $ProjectRoot "main.py")
$appExitCode = $LASTEXITCODE

if ($appExitCode -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Lunasia exited with code $appExitCode." -ForegroundColor Red
    Write-Host "Run Start Lunasia again to check and repair dependencies."
}

exit $appExitCode
