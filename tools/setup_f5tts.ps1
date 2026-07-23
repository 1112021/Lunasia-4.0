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

if ($Rebuild -and (Test-Path $EnvDir)) {
    Write-Host "Removing existing F5-TTS environment..."
    Remove-Item -Recurse -Force $EnvDir
}

Write-Host "Creating/updating F5-TTS environment at $EnvDir"
if ($PythonLauncher -eq "py") {
    if (-not (Test-PyVersion $PythonVersion)) {
        Write-Host "Python $PythonVersion is unavailable; trying Python 3.13."
        $PythonVersion = "3.13"
        if (-not (Test-PyVersion $PythonVersion)) {
            throw "Python 3.11 or 3.13 is required for the F5-TTS sidecar."
        }
    }
    & py "-$PythonVersion" -m venv $EnvDir
} else {
    & $PythonLauncher -m venv $EnvDir
}

$Python = Join-Path $EnvDir "Scripts\python.exe"
& $Python -m pip install --upgrade pip "setuptools<82" wheel
& $Python -m pip install `
    "torch==2.11.0+cu126" `
    "torchaudio==2.11.0+cu126" `
    --index-url $TorchIndexUrl
& $Python -m pip install -r $Requirements

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
Write-Host "Open the app settings and click '检测 F5-TTS 环境'."
