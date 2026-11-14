<#
    Prépare l'environnement de développement du projet clipagent.

    Usage :
        powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$SystemPython = "C:\Users\oussama\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $SystemPython)) {
    $SystemPython = (Get-Command python -ErrorAction Stop).Source
}

Write-Host "==> Environnement virtuel"
if (-not (Test-Path ".venv")) {
    & $SystemPython -m venv .venv
}
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Write-Host "==> Dépendances"
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev]"

Write-Host "==> Copie du fichier .env (si absent)"
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "    .env créé — renseignez OPENAI_API_KEY."
}

Write-Host "==> ffmpeg"
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    Write-Host "    détecté : $($ffmpeg.Source)"
} else {
    Write-Host "    absent — installez-le avec : winget install Gyan.FFmpeg"
    Write-Host "    (ou : pip install imageio-ffmpeg)"
}

Write-Host "==> Tests"
& $Python -m pytest
