<#
    Fabrique une vidéo de démonstration AVEC de la parole française (voix Windows
    Hortense) : permet de valider toute la chaîne (transcription -> agent ->
    rendu) sans film réel.

    Usage :
        powershell -ExecutionPolicy Bypass -File scripts\make_speech_demo.ps1
#>

param(
    [string]$Script = "examples\tts_script.txt",
    [string]$Audio = "examples\speech.wav",
    [string]$Video = "examples\demo_speech.mp4",
    [int]$TotalSeconds = 260
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "==> Synthèse vocale (Microsoft Hortense, fr-FR)"
Add-Type -AssemblyName System.Speech
$voice = (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Culture.Name -eq "fr-FR" } |
    Select-Object -First 1
if (-not $voice) { throw "Aucune voix française installée sur ce poste." }

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice($voice.VoiceInfo.Name)
$synth.Rate = -1
$text = (Get-Content $Script -Raw -Encoding UTF8) -replace "\|", "'"
$synth.SetOutputToWaveFile((Join-Path $ProjectRoot $Audio))
$synth.Speak($text)
$synth.Dispose()
Write-Host "    audio : $Audio"

Write-Host "==> Génération de l'image de fond"
$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $ffmpeg) {
    $ffmpeg = & (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
}

& $ffmpeg -y -hide_banner -loglevel error `
    -f lavfi -i "testsrc=size=1280x720:rate=25:duration=$TotalSeconds" `
    -i $Audio `
    -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest `
    $Video

Write-Host "Terminé : $Video"
