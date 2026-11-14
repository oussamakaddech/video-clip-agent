"""Test live : extraction du chat replay + score composite."""

from __future__ import annotations

from clipagent.browser import BrowserAnalyzer
from clipagent.chat import build_chat_context, chat_timeline, extract_chat

URL = "https://kick.com/randomguy42/videos/01a1d56e-ecb8-7c1f-820f-a4d35c23b719"

with BrowserAnalyzer(URL, out_dir="output/browser", headless=True, channel="msedge") as browser:
    browser.open()
    messages = extract_chat(browser.page)
    print(f"messages extraits : {len(messages)}")
    for message in messages[:10]:
        print(f"  [{int(message.timestamp // 60):02d}:{int(message.timestamp % 60):02d}] "
              f"{message.author[:18]:<18} | {message.text[:70]}")

    duration = browser.info.get("duration", 0)
    timeline = chat_timeline(messages, duration, buckets=24)
    print("densité du chat par 1/24 de la VOD :", [int(v) for v in timeline])

    windows = [(m.timestamp - 40, m.timestamp + 40) for m in messages[:3]]
    context = build_chat_context(messages, windows)
    print("--- contexte IA ---")
    print(context[:600])
