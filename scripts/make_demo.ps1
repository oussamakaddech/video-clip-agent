<#
    Génère une vidéo de démonstration (banc de couleurs + tonalité) pour
    tester le rendu sans film réel.

    Usage :
        powershell -ExecutionPolicy Bypass -File scripts\make_demo.ps1
#>

param(
    [string]$Output = "examples\demo.mp4",
    [int]$Duration = 420
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $ffmpeg) {
    $env:PYTHONPATH = $ProjectRoot
    $ffmpeg = & (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
}
if (-not $ffmpeg) { throw "ffmpeg introuvable : installez-le (winget install Gyan.FFmpeg) ou pip install imageio-ffmpeg" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null

Write-Host "==> Génération de $Output ($Duration s)"
& $ffmpeg -y -hide_banner -loglevel error `
    -f lavfi -i "testsrc=size=1280x720:rate=25:duration=$Duration" `
    -f lavfi -i "sine=frequency=440:duration=$Duration" `
    -c:v libx264 -preset veryfast -pix_fmt yuv420p `
    -c:a aac -shortest `
    $Output

Write-Host "Terminé : $Output"
