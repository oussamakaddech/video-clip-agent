"""Test réel : storyboard + capture audio sur la VOD Kick (sans télécharger la vidéo)."""

from __future__ import annotations

import time

from clipagent.browser import BrowserAnalyzer

URL = "https://kick.com/randomguy42/videos/01a1d56e-ecb8-7c1f-820f-a4d35c23b719"

with BrowserAnalyzer(URL, out_dir="output/browser", headless=True, channel="msedge") as browser:
    info = browser.open()
    print("INFO:", info)

    started = time.time()
    samples = browser.storyboard(step=120.0, max_frames=100)
    print(f"storyboard en {time.time()-started:.1f} s — {len(samples)} échantillons")
    top = sorted(samples, key=lambda s: -s.motion)[:8]
    for sample in top:
        print(f"   t={sample.timestamp:8.0f}s  mouvement={sample.motion:.4f}  {sample.path.name if sample.path else ''}")

    # capture audio seule d'une fenêtre de 40 s
    window_start = top[0].timestamp - 20
    path = browser.capture(window_start, window_start + 40, "output/browser/test_audio.webm", audio_only=True)
    print("AUDIO:", path, path.stat().st_size, "octets")
