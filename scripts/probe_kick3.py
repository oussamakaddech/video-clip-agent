"""Diagnostic v3 : codecs H.264 supportés ? clic sur le lecteur ? requêtes m3u8 ?"""

from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://kick.com/randomguy42/videos/01a1d56e-ecb8-7c1f-820f-a4d35c23b719"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
    page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()

    manifests: list[str] = []
    page.on(
        "response",
        lambda r: manifests.append(r.url) if any(k in r.url for k in (".m3u8", ".mp4", "manifest")) else None,
    )

    page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(6000)

    print("CODECS :", page.evaluate(
        """() => { const v=document.createElement('video');
             return {
               h264: v.canPlayType('video/mp4; codecs="avc1.42E01E"'),
               aac: v.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
               hls: v.canPlayType('application/vnd.apple.mpegurl'),
               mseH264: window.MediaSource ? MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E"') : 'no MSE',
               mseAac: window.MediaSource ? MediaSource.isTypeSupported('audio/mp4; codecs="mp4a.40.2"') : 'no MSE',
               mseAv1: window.MediaSource ? MediaSource.isTypeSupported('video/mp4; codecs="av01.0.05M.08"') : 'no MSE',
             }; }"""
    ))

    # clic sur la zone du lecteur
    try:
        page.click("video", timeout=5000)
        print("clic sur <video> OK")
    except Exception as exc:
        print("clic sur <video> :", str(exc)[:80])
    page.wait_for_timeout(6000)

    print("APRES CLIC :", page.evaluate(
        """() => { const v=document.querySelector('video'); return {d:v.duration, ready:v.readyState, t:v.currentTime, paused:v.paused, w:v.videoWidth}; }"""
    ))

    print("TITRE/ETAT :", page.evaluate("() => document.body.innerText.slice(0,300)"))
    print("MANIFESTS :", manifests[:8])
    browser.close()
