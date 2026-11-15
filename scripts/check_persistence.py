"""Test complet : creation -> redemarrage du serveur -> telechargements."""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8765"
ROOT = r"C:\Users\oussama\Desktop\video-clip-agent"


def call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = response.read()
            return response.status, body, dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def restart_server() -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -match 'uvicorn' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
        capture_output=True,
    )
    time.sleep(2)
    subprocess.Popen(
        [rf"{ROOT}\.venv\Scripts\python.exe", "-m", "uvicorn", "clipagent.api.server:app",
         "--host", "127.0.0.1", "--port", "8765", "--log-level", "warning"],
        cwd=ROOT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    time.sleep(8)


# 1. Création
video = [f for f in glob.glob(f"{ROOT}\\output\\uploads\\*.mp4") if os.path.getsize(f) > 10_000_000][0]
status, body, _ = call("POST", "/api/jobs", {
    "video_path": video, "num_clips": 2, "min_clip": 15, "max_clip": 35,
    "style": "tiktok", "render": True, "whisper_model": "tiny",
})
job_id = json.loads(body)["id"]
print("1. tâche créée :", job_id, "->", status)

for _ in range(120):
    time.sleep(5)
    status, body, _ = call("GET", f"/api/jobs/{job_id}")
    state = json.loads(body)
    if state["status"] in {"done", "error", "cancelled"}:
        break
print("   statut :", state["status"], "|", state["message"])

# 2. Redémarrage du serveur
print("2. redémarrage du serveur…")
restart_server()
status, body, _ = call("GET", f"/api/jobs/{job_id}")
print("   tâche retrouvée après redémarrage :", status, json.loads(body)["status"] if status == 200 else body[:120])

# 3. Téléchargements
print("3. téléchargements :")
for path in (
    f"/api/jobs/{job_id}/clips/1",
    f"/api/jobs/{job_id}/files",
    f"/api/jobs/{job_id}/zip",
    f"/api/jobs/{job_id}/report",
):
    status, body, headers = call("GET", path)
    size = headers.get("Content-Length") or len(body)
    print(f"   {path:<42} -> {status}  {size} octets")
