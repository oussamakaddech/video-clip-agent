"""Diagnostic v4 : lecture de la VOD Kick dans un navigateur avec codecs H.264."""

from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://kick.com/randomguy42/videos/01a1d56e-ecb8-7c1f-820f-a4d35c23b719"

CODECS = """() => { const v = document.createElement('video');
  return { h264: v.canPlayType('video/mp4; codecs="avc1.42E01E"'),
           aac: v.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
           mseH264: window.MediaSource ? MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E"') : false }; }"""

VIDEOS = """() => Array.from(document.querySelectorAll('video')).map(v => ({
  d: v.duration, ready: v.readyState, t: v.currentTime,
  w: v.videoWidth, h: v.videoHeight, paused: v.paused,
  src: (v.currentSrc || '').slice(0, 90) }))"""

for channel in ("msedge", "chrome"):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel=channel, headless=True,
                args=["--autoplay-policy=no-user-gesture-required"],
            )
            page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
            page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(8000)
            print(f"--- {channel} ---")
            print("  codecs:", page.evaluate(CODECS))
            page.evaluate(
                """() => { document.querySelectorAll('video').forEach(v => {
                     try { v.muted = false; v.play().catch(()=>{}); } catch (e) {} }); }"""
            )
            page.wait_for_timeout(6000)
            for item in page.evaluate(VIDEOS):
                print("   ", item)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"--- {channel} --- ERREUR: {str(exc)[:200]}")
