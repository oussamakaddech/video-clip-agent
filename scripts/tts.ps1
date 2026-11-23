param(
    [Parameter(Mandatory = $true)][string]$Text,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Voice = "Microsoft David Desktop",
    [int]$Rate = 0
)

# Synthèse vocale hors ligne (System.Speech). Aucun réseau, aucun service.
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice($Voice)
} catch {
    # Voix absente : on garde la voix par défaut plutôt que d'échouer.
    Write-Warning "voix '$Voice' indisponible, voix par défaut utilisée"
}
$synth.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
$synth.SetOutputToWaveFile($Out)
$synth.Speak($Text)
$synth.Dispose()
