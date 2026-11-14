"""Diagnostic v2 : énumère les éléments <video> et leur état."""

from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://kick.com/randomguy42/videos/01a1d56e-ecb8-7c1f-820f-a4d35c23b719"

JS = """
() => Array.from(document.querySelectorAll('video')).map((v, i) => ({
  i,
  duration: v.duration,
  w: v.videoWidth, h: v.videoHeight,
  ready: v.readyState,
  paused: v.paused,
  src: (v.currentSrc || '').slice(0, 120),
  cls: (v.className || '').toString().slice(0, 60),
  parent: (v.parentElement && v.parentElement.className || '').toString().slice(0, 60),
}))
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
    page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=90_000)

    for attempt in range(6):
        page.wait_for_timeout(4000)
        # on tente de démarrer la lecture (le lecteur Kick peut exiger un clic)
        page.evaluate(
            """() => {
              const vids = Array.from(document.querySelectorAll('video'));
              for (const v of vids) { try { v.muted = false; v.play().catch(()=>{}); } catch(e){} }
              const btn = document.querySelector('button[data-testid="play-button"], .video-player__play, video-control-bar button');
              if (btn) { try { btn.click(); } catch(e){} }
            }"""
        )
        page.wait_for_timeout(2500)
        print(f"--- essai {attempt} ---")
        for v in page.evaluate(JS):
            print("  ", v)
    browser.close()
