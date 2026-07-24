param(
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$FfmpegDir = Join-Path $PSScriptRoot "ffmpeg\bin"
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$SetupScript = Join-Path $PSScriptRoot "setup_f5tts.ps1"

function Find-ExistingFfmpeg {
    if (Test-Path $FfmpegExe) {
        return $FfmpegExe
    }

    $command = Get-Command "ffmpeg.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $wingetRoot) {
        $wingetFfmpeg = Get-ChildItem $wingetRoot -Filter "ffmpeg.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*Gyan.FFmpeg*" } |
            Select-Object -First 1
        if ($wingetFfmpeg) {
            return $wingetFfmpeg.FullName
        }
    }

    return $null
}

function Install-PortableFfmpeg {
    $downloadUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("lunasia-ffmpeg-" + [Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tempRoot "ffmpeg.zip"
    $extractDir = Join-Path $tempRoot "extract"

    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    try {
        Write-Host "Downloading portable FFmpeg..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $downloadUrl -OutFile $zipPath
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

        $downloadedExe = Get-ChildItem $extractDir -Filter "ffmpeg.exe" -File -Recurse |
            Select-Object -First 1
        if (-not $downloadedExe) {
            throw "The FFmpeg archive did not contain ffmpeg.exe."
        }

        New-Item -ItemType Directory -Path $FfmpegDir -Force | Out-Null
        Copy-Item -Path (Join-Path $downloadedExe.Directory.FullName "*") -Destination $FfmpegDir -Recurse -Force
    } finally {
        Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path $FfmpegExe)) {
        throw "Portable FFmpeg installation failed."
    }
}

Write-Host ""
Write-Host "========================================"
Write-Host "       Lunasia F5-TTS Installer"
Write-Host "========================================"
Write-Host ""
Write-Host "F5-TTS is optional and uses a separate environment."
Write-Host "The first installation is large and can take a long time."
Write-Host ""

$ffmpeg = Find-ExistingFfmpeg
if ($ffmpeg) {
    Write-Host "FFmpeg found: $ffmpeg"
} else {
    Install-PortableFfmpeg
    Write-Host "Portable FFmpeg is ready: $FfmpegExe"
}

Write-Host ""
Write-Host "Installing F5-TTS..."
if ($Rebuild) {
    & $SetupScript -Rebuild
} else {
    & $SetupScript
}

if (-not (Test-Path (Join-Path $PSScriptRoot "f5tts_env\Scripts\python.exe"))) {
    throw "F5-TTS environment was not created."
}

Write-Host ""
Write-Host "F5-TTS installation completed."
Write-Host "You can now select F5-TTS in Lunasia settings."
