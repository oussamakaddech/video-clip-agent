<#
    Démarre le serveur clipagent de façon DÉTACHÉE : le processus est créé via
    WMI, donc il survit à la fermeture du terminal (contrairement à un
    Start-Process, qui reste enfant du shell et se tue avec lui).

    Usage :
        powershell -ExecutionPolicy Bypass -File scripts\start-server.ps1
        powershell -ExecutionPolicy Bypass -File scripts\start-server.ps1 -Stop
#>

param(
    [int]$Port = 8765,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Environnement absent : $python (executez scripts\setup.ps1)"
}

# 1. Arret d'une instance precedente
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn" -and $_.CommandLine -match "clipagent" } |
    ForEach-Object {
        Write-Host "Arret de l'instance precedente (PID $($_.ProcessId))"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1

if ($Stop) { Write-Host "Serveur arrete."; exit 0 }

# 2. Demarrage detache (WMI : processus independant du shell)
$logDir = Join-Path $env:LOCALAPPDATA "clipagent"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "server.log"

$command = "cmd /c cd /d `"$ProjectRoot`" && `"$python`" -m uvicorn clipagent.api.server:app --host 127.0.0.1 --port $Port --log-level info > `"$log`" 2>&1"
$created = ([wmiclass]"Win32_Process").Create($command, $ProjectRoot)
if ($created.ReturnValue -ne 0) {
    throw "Demarrage impossible (code $($created.ReturnValue))"
}
Write-Host "Processus detache cree (PID $($created.ProcessId))"

# 3. Attente de la reponse HTTP
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        $ok = $true
        break
    } catch { }
}

if (-not $ok) {
    Write-Host "ECHEC du demarrage - journal :"
    if (Test-Path $log) { Get-Content $log -Tail 20 }
    exit 1
}

Write-Host ""
Write-Host "  clipagent est demarre"
Write-Host "    Interface : http://127.0.0.1:$Port"
Write-Host "    API       : http://127.0.0.1:$Port/api/health"
Write-Host "    Journal   : $log"
Write-Host "    Arret     : powershell -File scripts\start-server.ps1 -Stop"
