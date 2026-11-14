"""Test comparateur + edition sur une tache existante (usage : smoke_compare2.py <job_id>)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
JOB_ID = sys.argv[1] if len(sys.argv) > 1 else ""


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code, exc.read()[:400])
        raise


state = call("GET", f"/api/jobs/{JOB_ID}")
for _ in range(180):
    if state["status"] in {"done", "error", "cancelled"}:
        break
    time.sleep(5)
    state = call("GET", f"/api/jobs/{JOB_ID}")

print("statut :", state["status"], "|", state["message"])
clips = (state.get("result") or {}).get("clips", [])
for clip in clips:
    print(f"  #{clip['index']} {clip['start']:.0f}-{clip['end']:.0f}s  {clip['title']}")

if not clips:
    raise SystemExit("pas d'extrait")

index = clips[0]["index"]
edited = call("PATCH", f"/api/jobs/{JOB_ID}/clips/{index}", {
    "title": "Titre edite a la main",
    "hook": "Accroche testee en direct",
})
print("edition   :", edited["clip"]["title"], "|", edited["clip"]["hook"])

comparison = call("POST", f"/api/jobs/{JOB_ID}/compare", {
    "clip_index": index,
    "styles": ["streamer", "tiktok", "hype"],
    "language": "en",
    "whisper_model": "tiny",
})
print("comparaison :")
for item in comparison["results"]:
    print(f"  {item['style']:<10} {item['label']:<26} {item['path']}")

chosen = call("PATCH", f"/api/jobs/{JOB_ID}/style", {"style": "tiktok"})
print("style retenu :", chosen["style"])
