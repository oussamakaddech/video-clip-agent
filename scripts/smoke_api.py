"""Test de fumee de l'API (lance le serveur, verifie les endpoints)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as response:
        return json.loads(response.read())


def post(path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


health = get("/api/health")
print("health      :", health["status"], "| llm:", health["llm"], "| disque:", health["free_disk_mb"], "Mo")

provider = get("/api/provider")
print("provider    :", provider["model"], "| joignable:", provider["reachable"])

status, detail = post("/api/jobs", {"num_clips": 3})
print("validation  :", status, "->", detail.get("detail", "")[:70])

status, job = post(
    "/api/jobs",
    {
        "transcript_path": r"C:\Users\oussama\Desktop\video-clip-agent\output_kick3\candidates.srt",
        "num_clips": 2,
        "min_clip": 20,
        "max_clip": 40,
        "style": "streamer",
        "language": "en",
        "render": False,
        "whisper_model": "tiny",
    },
)
print("job cree    :", job.get("id"), "| statut:", job.get("status"))

job_id = job.get("id")
for _ in range(60):
    time.sleep(5)
    state = get(f"/api/jobs/{job_id}")
    if state["status"] in {"done", "error", "cancelled"}:
        break
print("statut final:", state["status"], "|", state["message"])
for clip in (state.get("result") or {}).get("clips", []):
    print(f"  #{clip['index']} {clip['start']:.0f}-{clip['end']:.0f}s  {clip['title']}")
