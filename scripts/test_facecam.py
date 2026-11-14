"""Test réel : rendu d'un fragment avec face cam (visage du streamer en bas)."""

from __future__ import annotations

from pathlib import Path

from clipagent.config import Settings
from clipagent.facecam import detect_face_in_video
from clipagent.ffmpeg import render_clip
from clipagent.styles import STYLES

FRAGMENT = Path("output_kick/work/cand_01.webm")
OUT = Path(r"C:\Users\oussama\AppData\Local\Temp\opencode\facecam_test.mp4")

box = detect_face_in_video(FRAGMENT, samples=10, duration=80.0)
print("visage détecté :", box.to_dict() if box else "AUCUN")
if box is None:
    raise SystemExit("pas de visage détecté")

style = STYLES["tiktok"]
settings = Settings.from_env(width=1080, height=1920, style="tiktok")
render_clip(
    FRAGMENT,
    OUT,
    start=10.0,
    end=30.0,
    settings=settings,
    style=style,
    face_box=box.padded(0.6).square(),
)
print("rendu :", OUT, OUT.stat().st_size, "octets")
