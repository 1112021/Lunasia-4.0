param(
    [string]$PythonLauncher = "py",
    [string]$PythonVersion = "3.11",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu126",
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvDir = Join-Path $PSScriptRoot "f5tts_env"
$Requirements = Join-Path $PSScriptRoot "f5tts-requirements.txt"

function Test-PyVersion([string]$Version) {
    if (-not (Get-Command "py.exe" -ErrorAction SilentlyContinue)) {
        return $false
    }
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $PreviousNativePreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    & py "-$Version" --version *> $null
    $Available = $LASTEXITCODE -eq 0
    if (Get-Variable PreviousNativePreference -ErrorAction SilentlyContinue) {
        $PSNativeCommandUseErrorActionPreference = $PreviousNativePreference
    }
    $ErrorActionPreference = $PreviousPreference
    return $Available
}

function Test-DirectPython([string]$Command) {
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $Command -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 11), (3, 13)) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
}

function Assert-NativeSuccess([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

if ($Rebuild -and (Test-Path $EnvDir)) {
    Write-Host "Removing existing F5-TTS environment..."
    Remove-Item -Recurse -Force $EnvDir
}

Write-Host "Creating/updating F5-TTS environment at $EnvDir"
if ($PythonLauncher -eq "py") {
    if (Test-PyVersion $PythonVersion) {
        & py "-$PythonVersion" -m venv $EnvDir
    } elseif (Test-PyVersion "3.13") {
        Write-Host "Python $PythonVersion is unavailable; trying Python 3.13."
        $PythonVersion = "3.13"
        & py "-$PythonVersion" -m venv $EnvDir
    } else {
        $DirectPython = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if (-not $DirectPython -or -not (Test-DirectPython $DirectPython.Source)) {
            throw "F5-TTS requires Python 3.11 or 3.13. Install one from python.org and try again."
        }
        Write-Host "Python Launcher is unavailable; using $($DirectPython.Source)."
        & $DirectPython.Source -m venv $EnvDir
    }
} else {
    & $PythonLauncher -m venv $EnvDir
}
Assert-NativeSuccess "Creating the F5-TTS environment"

$Python = Join-Path $EnvDir "Scripts\python.exe"
& $Python -m pip install --upgrade pip "setuptools<82" wheel
Assert-NativeSuccess "Preparing pip"
& $Python -m pip install `
    "torch==2.11.0+cu126" `
    "torchaudio==2.11.0+cu126" `
    --index-url $TorchIndexUrl
Assert-NativeSuccess "Installing PyTorch"
& $Python -m pip install -r $Requirements
Assert-NativeSuccess "Installing F5-TTS dependencies"

# Verify the exact runtime used by blank-transcript auto recognition.
$VerifyScript = @'
import soundfile, scipy, torch, torchaudio, transformers, f5_tts
assert torch.__version__.startswith("2.11.0+cu126"), torch.__version__
assert torchaudio.__version__.startswith("2.11.0+cu126"), torchaudio.__version__
print("F5-TTS imports OK; CUDA:", torch.cuda.is_available())
'@
$VerifyScript | & $Python -
if ($LASTEXITCODE -ne 0) {
    throw "F5-TTS environment verification failed."
}

Write-Host ""
Write-Host "F5-TTS environment is ready."
Write-Host "Python: $Python"
Write-Host "Open the app settings and run the F5-TTS environment test."
