"""Sélection automatique du modèle d'IA le plus adapté au clipping.

Plutôt que de demander à l'utilisateur un nom de modèle, on :
1. on interroge le catalogue du fournisseur (endpoint compatible OpenAI) ;
2. on écarte les modèles qui ne savent pas utiliser des outils (embeddings,
   garde-fous, retrieveurs) ou qui ne sont pas des modèles de chat ;
3. on **sonde** les meilleurs candidats avec une vraie micro-tâche de clipping
   (appel d'outil `propose_clip`) et on note : succès, qualité, latence ;
4. on retient le meilleur, et on met en cache le classement (24 h).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings

CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "clipagent"
CACHE_FILE = CACHE_DIR / "model_bench.json"
CACHE_TTL = 24 * 3600

# Modèles écartés : ils ne savent pas utiliser d'outils ou ne sont pas des chat.
_EXCLUDE = re.compile(
    r"(embed|rerank|guard|nemoguard|nemoretriever|nv-embed|visionqa|whisper|tts|"
    r"moderation|parse|code|math|ocr|nano|retranslate|phi-3|stable-diffusion|"
    r"nemotron-parse|vision|nv-vision|-vl-|reward|cosmos|shield)",
    re.IGNORECASE,
)

# Modèles que l'agent sait utiliser (tool calling) : on les privilégie.
_PREFER = re.compile(
    r"(nemotron|instruct|chat|ultra|pro|plus|flash|medium)", re.IGNORECASE
)

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


def _param_size(model: str) -> float:
    """Taille approximative du modèle en milliards de paramètres."""
    sizes = [float(m) for m in _SIZE_RE.findall(model)]
    return max(sizes) if sizes else 0.0

PROBE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "propose_clip",
            "description": "Propose un extrait vidéo à mettre en avant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "début en secondes"},
                    "end": {"type": "number", "description": "fin en secondes"},
                    "title": {"type": "string", "description": "titre court"},
                    "hook": {"type": "string", "description": "accroche de 4 à 9 mots"},
                },
                "required": ["start", "end", "title"],
            },
        },
    }
]

PROBE_PROMPT = """Voici un extrait de transcription d'un livestream :

[00:00:10.000 --> 00:00:20.000] On a doublé l'engagement en un mois, c'est fou.
[00:00:20.000 --> 00:00:35.000] La clé c'est de segmenter, sinon on coupe les phrases.
[00:00:35.000 --> 00:00:48.000] Donc il faut un modele qui sait donner des bornes precises.

Propose UN seul extrait de 20 a 40 secondes (bornes en secondes), avec un titre
court et une accroche de 4 a 9 mots. Utilise l'outil propose_clip."""

PROBE_SYSTEM = (
    "Tu es un monteur vidéo spécialisé dans le clipping de lives. "
    "Tu analyses une transcription et tu proposes des extraits. "
    "Tu dois imperativement appeler l'outil propose_clip pour chaque proposition, "
    "avec des bornes en secondes, un titre court et une accroche de 4 à 9 mots."
)


def _extract_json(text: str) -> dict | None:
    """Extrait le premier objet JSON d'une réponse en texte libre."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


@dataclass
class ProbeResult:
    """Résultat de la sonde d'un modèle."""

    model: str
    ok: bool = False
    latency: float = 0.0
    quality: float = 0.0
    score: float = 0.0
    error: str | None = None
    sample: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "ok": self.ok,
            "latency": round(self.latency, 2),
            "quality": round(self.quality, 3),
            "score": round(self.score, 3),
            "error": self.error,
            "sample": self.sample,
        }


def _cache_path() -> Path:
    return CACHE_FILE


def read_cache(provider: str) -> list[dict] | None:
    """Relit le classement en cache s'il est encore frais."""
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("provider") != provider:
        return None
    if time.time() - float(data.get("timestamp", 0)) > CACHE_TTL:
        return None
    return list(data.get("results", []))


def write_cache(provider: str, results: list[dict]) -> None:
    """Sauvegarde le classement (évite de re-sonder à chaque tâche)."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(
            json.dumps({"provider": provider, "timestamp": time.time(), "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def candidate_models(settings: Settings, limit: int = 12) -> list[str]:
    """Modèles candidats pour le clipping (chat + outils), triés par pertinence.

    Le modèle actuellement configuré est toujours sondé en premier : s'il
    fonctionne, c'est déjà un candidat crédible.
    """
    from .service import list_models

    models = [m["id"] for m in list_models(settings)]
    kept = [m for m in models if not _EXCLUDE.search(m)]
    if not kept:
        kept = models

    def rank(model: str) -> tuple:
        kind = 0 if _PREFER.search(model) else 1
        size = _param_size(model)
        current = 0 if model == settings.model else 1
        return (current, kind, -size, model)

    kept.sort(key=rank)
    if settings.model in kept:
        kept.remove(settings.model)
    kept.insert(0, settings.model)
    return kept[:limit]


def probe_model(model: str, settings: Settings, timeout: float = 30.0) -> ProbeResult:
    """Sonde un modèle sur une micro-tâche de clipping et le note."""
    result = ProbeResult(model=model)
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.provider_base_url or settings.base_url or None,
            timeout=timeout,
        )
        started = time.time()
        request = dict(
            model=model,
            messages=[
                {"role": "system", "content": PROBE_SYSTEM},
                {"role": "user", "content": PROBE_PROMPT},
            ],
            tools=PROBE_TOOLS,
            tool_choice="auto",
            # Les modèles « raisonneurs » consomment beaucoup de tokens avant
            # d'appeler un outil : un budget trop petit les fait échouer.
            max_tokens=1024,
            temperature=0.2,
        )
        base_url = (settings.provider_base_url or settings.base_url or "").lower()
        if "nvidia" in base_url:
            request["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        try:
            response = client.chat.completions.create(**request)
        except Exception:  # noqa: BLE001 - certains endpoints refusent extra_body
            request.pop("extra_body", None)
            response = client.chat.completions.create(**request)
        result.latency = time.time() - started

        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None) or []
        payload: dict | None = None
        if calls:
            arguments = calls[0].function.arguments
            try:
                payload = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            except (json.JSONDecodeError, TypeError):
                payload = None
                result.error = "arguments JSON invalides"
                return result
        else:
            # Certains modèles écrivent le JSON en texte : on l'accepte aussi.
            payload = _extract_json(getattr(message, "content", "") or "")
            if payload is None:
                result.error = "aucun appel d'outil"
                return result

        start = float(payload.get("start", 0) or 0)
        end = float(payload.get("end", 0) or 0)
        title = str(payload.get("title", "") or "")
        hook = str(payload.get("hook", "") or "")

        quality = 0.0
        if 0 <= start < end:
            quality += 0.35
        duration = end - start
        if 15 <= duration <= 90:
            quality += 0.25
        if 3 <= len(title.split()) <= 14:
            quality += 0.2
        if 3 <= len(hook.split()) <= 12:
            quality += 0.2
        result.ok = True
        result.quality = round(quality, 3)
        result.sample = {"start": start, "end": end, "title": title, "hook": hook}
    except Exception as exc:  # noqa: BLE001 - un modèle qui échoue est simply écarté
        result.error = f"{exc.__class__.__name__}: {exc}"[:160]
    return result


def score_probe(result: ProbeResult) -> float:
    """Score global : succès + qualité, pondéré par la latence."""
    if not result.ok:
        return 0.0
    latency_bonus = max(0.0, 1.0 - result.latency / 60.0) * 0.15
    return round(result.quality + latency_bonus, 3)


def select_best_model(
    settings: Settings,
    *,
    limit: int = 6,
    use_cache: bool = True,
    on_progress=None,
) -> dict:
    """Cherche, sonde et classe les modèles ; renvoie le meilleur."""
    provider = settings.provider or "openai"
    if use_cache:
        cached = read_cache(provider)
        if cached:
            return {
                "provider": provider,
                "results": cached,
                "best": cached[0]["model"] if cached else None,
                "cached": True,
            }

    candidates = candidate_models(settings, limit=limit)
    if not candidates:
        return {"provider": provider, "results": [], "best": None, "cached": False}

    results: list[ProbeResult] = []
    for index, model in enumerate(candidates):
        if on_progress:
            on_progress(f"Sonde de {model}…", (index + 1) / len(candidates))
        probe = probe_model(model, settings)
        probe.score = score_probe(probe)
        results.append(probe)

    ranked = sorted(results, key=lambda r: -r.score)
    payload = [r.to_dict() for r in ranked]
    write_cache(provider, payload)
    return {
        "provider": provider,
        "results": payload,
        "best": ranked[0].model if ranked and ranked[0].ok else None,
        "cached": False,
    }
