"""Test du layout « streamer » (contenu en haut, caméra plein cadre en bas)."""

from __future__ import annotations

from pathlib import Path

from clipagent.config import Settings
from clipagent.facecam import detect_face_in_video
from clipagent.ffmpeg import render_clip
from clipagent.styles import STYLES

FRAGMENT = Path("output_kick3/work/cand_02.webm")
OUT = Path(r"C:\Users\oussama\AppData\Local\Temp\opencode\streamer_test.mp4")

style = STYLES["streamer"]
settings = Settings.from_env(width=1080, height=1920, style="streamer")

box = detect_face_in_video(FRAGMENT, samples=8, duration=80.0)
print("visage :", box.to_dict() if box else None)
if box is None:
    raise SystemExit("pas de visage")

region = box.camera_region(style.facecam_region).clamped(box.frame_width, box.frame_height)
print("région caméra :", region.to_dict())

render_clip(
    FRAGMENT,
    OUT,
    start=10.0,
    end=30.0,
    settings=settings,
    style=style,
    face_box=region,
)
print("rendu :", OUT, OUT.stat().st_size, "octets")
