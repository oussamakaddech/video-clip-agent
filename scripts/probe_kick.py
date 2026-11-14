"""Diagnostic : que contient la page Kick (iframe, <video>, durée, titre) ?"""

from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://kick.com/randomguy42/videos/01a1d56e-ecb8-7c1f-820f-a4d35c23b719"

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--autoplay-policy=no-user-gesture-required", "--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(6000)

    print("TITLE :", page.title())
    print("URL   :", page.url)
    print("IFRAMES:", [f.url for f in page.frames])

    for frame in page.frames:
        try:
            count = frame.evaluate("() => document.querySelectorAll('video').length")
        except Exception as exc:
            count = f"erreur {exc}"
        print(f"  frame {frame.url[:80]} -> video: {count}")
        if count == 0:
            continue
        info = frame.evaluate(
            """() => { const v=document.querySelector('video');
                 return {duration:v.duration, w:v.videoWidth, h:v.videoHeight,
                         ready:v.readyState, paused:v.paused, src:(v.currentSrc||'').slice(0,90),
                         err:v.error && v.error.message}; }"""
        )
        print("   INFO:", info)
        frame.evaluate("() => { const v=document.querySelector('video'); v.play().catch(e=>console.log('play err', e.message)); }")
        page.wait_for_timeout(3000)
        print("   APRES PLAY:", frame.evaluate("() => { const v=document.querySelector('video'); return {d:v.duration, t:v.currentTime, paused:v.paused}; }"))

    print("BODY (500 premiers caractères) :")
    print(page.evaluate("() => document.body.innerText.slice(0,500)"))
    browser.close()
