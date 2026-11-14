"""Chat replay d'un live (Kick) : extraction, densité et contexte pour l'agent.

Le chat replay est un signal **sémantique** très fort : les moments forts
provoquent une vague de messages. Il est lu directement dans la page (aucun
téléchargement), avec l'horodatage vidéo de chaque message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 03:19:38 / 19:38 / 1:02:03
_TIMESTAMP_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")
_SHORT_TIME_RE = re.compile(r"^(\d{1,2})\s*(s|m|h)$", re.IGNORECASE)

# Libellés d'interface à ne pas confondre avec des messages de chat.
_NOISE_RE = re.compile(r"\b(\d[\d.,]*\s*k?\s*(vues?|views?)|watching|regards)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ChatMessage:
    """Un message du chat replay, avec sa position dans la vidéo."""

    timestamp: float      # position en secondes dans la VOD
    text: str
    author: str = ""

    def to_dict(self) -> dict:
        return {"timestamp": round(self.timestamp, 2), "author": self.author, "text": self.text}


def parse_video_timestamp(value: str) -> float | None:
    """Convertit « 03:19:38 » / « 19:38 » en secondes (None si invalide)."""
    match = _TIMESTAMP_RE.match(value.strip())
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    if minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


# JavaScript : remonte les messages de chat avec leur horodatage vidéo.
JS_EXTRACT_CHAT = """
() => {
  const timeRe = /^(\\d{1,2}:)?\\d{1,2}:\\d{2}$/;
  const noiseRe = /\\b(vues?|views?|watching|regards)\\b/i;
  const results = [];
  const seen = new Set();

  // On ne cherche que dans les zones de chat (le reste de la page contient
  // les autres VOD de la chaîne, avec leurs « X vues » — faux positifs).
  const roots = Array.from(document.querySelectorAll(
    '[class*="chat"],[id*="chat"],[data-testid*="chat"],[class*="Chat"]'
  ));
  const scope = roots.length ? roots : [document.body];

  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.children.length > 0) continue;
      const text = (el.textContent || '').trim();
      if (!timeRe.test(text)) continue;
      let node = el;
      let payload = null;
      for (let up = 0; up < 5 && node; up++) {
        const parent = node.parentElement;
        if (!parent) break;
        const full = (parent.innerText || '').trim();
        if (full.length > text.length + 1) { payload = full; break; }
        node = parent;
      }
      if (!payload) continue;
      if (noiseRe.test(payload)) continue;
      const key = text + '|' + payload;
      if (seen.has(key)) continue;
      seen.add(key);
      const lines = payload.split('\\n').map(s => s.trim()).filter(Boolean);
      const author = lines.length > 1 ? lines[0] : '';
      const message = lines.length > 1 ? lines.slice(1).join(' ') : payload;
      results.push({ time: text, author, text: message });
    }
  };

  for (const root of scope) { try { walk(root); } catch (e) {} }
  return results;
}
"""


def extract_chat(page) -> list[ChatMessage]:
    """Extrait les messages du chat replay présents dans la page."""
    try:
        raw = page.evaluate(JS_EXTRACT_CHAT)
    except Exception:  # noqa: BLE001 - le chat est optionnel
        return []

    messages: list[ChatMessage] = []
    for item in raw or []:
        timestamp = parse_video_timestamp(str(item.get("time", "")))
        if timestamp is None:
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        # On ignore les libellés d'interface (« 1,2 k vues ») et les répétitions.
        if _NOISE_RE.search(text):
            continue
        if text.lower() == str(item.get("author", "")).strip().lower():
            continue
        messages.append(
            ChatMessage(
                timestamp=timestamp,
                text=text[:300],
                author=str(item.get("author", "")).strip()[:60],
            )
        )
    messages.sort(key=lambda m: m.timestamp)
    return messages


def chat_heat(messages: list[ChatMessage], start: float, end: float) -> float:
    """Nombre de messages par minute dans l'intervalle [start, end]."""
    if end <= start:
        return 0.0
    inside = [m for m in messages if start <= m.timestamp < end]
    minutes = (end - start) / 60.0
    if minutes <= 0:
        return float(len(inside))
    return round(len(inside) / minutes, 2)


def chat_timeline(messages: list[ChatMessage], duration: float, buckets: int = 120) -> list[float]:
    """Densité du chat sur `buckets` intervalles réguliers de la VOD."""
    if duration <= 0 or buckets <= 0:
        return []
    size = duration / buckets
    counts = [0] * buckets
    for message in messages:
        index = int(message.timestamp / size)
        if 0 <= index < buckets:
            counts[index] += 1
    return [float(c) for c in counts]


def summarize_window(
    messages: list[ChatMessage],
    start: float,
    end: float,
    *,
    limit: int = 6,
) -> list[str]:
    """Messages les plus « marquants » d'une fenêtre (les plus longs, donc les plus explicites)."""
    inside = [m for m in messages if start <= m.timestamp < end]
    inside.sort(key=lambda m: len(m.text), reverse=True)
    return [f"[{int(m.timestamp // 60):02d}:{int(m.timestamp % 60):02d}] {m.text[:120]}" for m in inside[:limit]]


def build_chat_context(
    messages: list[ChatMessage],
    windows: list[tuple[float, float]],
    *,
    limit: int = 4,
) -> str:
    """Bloc de contexte « activité du chat » pour le prompt de l'agent."""
    if not messages or not windows:
        return ""
    lines = ["ACTIVITÉ DU CHAT (messages marquants par fenêtre) :"]
    for start, end in windows:
        entries = summarize_window(messages, start, end, limit=limit)
        if not entries:
            continue
        lines.append(f"- {int(start // 60):02d}:{int(start % 60):02d} → {int(end // 60):02d}:{int(end % 60):02d}")
        lines.extend(f"    {entry}" for entry in entries)
    return "\n".join(lines) if len(lines) > 1 else ""
