"""Test reel : comparateur de styles + edition inline via l'API."""

from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8765"
ROOT = r"C:\Users\oussama\Desktop\video-clip-agent"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as response:
        return json.loads(response.read())


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.loads(response.read())


def patch(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


# 1. Tâche sur une vidéo locale dont le transcript correspond
job = post(
    "/api/jobs",
    {
        "video_path": rf"{ROOT}\examples\demo_speech.mp4",
        "transcript_path": rf"{ROOT}\examples\speech.srt",
        "num_clips": 2,
        "min_clip": 20,
        "max_clip": 40,
        "style": "streamer",
        "language": "en",
        "render": False,
        "whisper_model": "tiny",
    },
)
job_id = job["id"]
print("tache :", job_id)

for _ in range(120):
    time.sleep(5)
    state = get(f"/api/jobs/{job_id}")
    if state["status"] in {"done", "error", "cancelled"}:
        break
print("statut :", state["status"], "|", state["message"])
clips = (state.get("result") or {}).get("clips", [])
for clip in clips:
    print(f"  #{clip['index']} {clip['start']:.0f}-{clip['end']:.0f}s  {clip['title']}")

if not clips:
    raise SystemExit("pas d'extrait")

# 2. Edition inline du titre et de l'accroche
edited = patch(f"/api/jobs/{job_id}/clips/{clips[0]['index']}", {
    "title": "Titre edite a la main",
    "hook": "Accroche testee en direct",
})
print("edition :", edited["clip"]["title"], "|", edited["clip"]["hook"])

# 3. Comparateur de styles (3 styles sur le meme extrait)
comparison = post(f"/api/jobs/{job_id}/compare", {
    "clip_index": clips[0]["index"],
    "styles": ["streamer", "tiktok", "hype"],
    "language": "en",
    "whisper_model": "tiny",
})
print("comparaison :")
for item in comparison["results"]:
    print(f"  {item['style']:<10} {item['label']:<28} {item['path']}")

# 4. Retenir un style
chosen = patch(f"/api/jobs/{job_id}/style", {"style": "tiktok"})
print("style retenu :", chosen["style"])
