"""Agent IA (OpenAI Agents SDK) chargé de sélectionner les extraits.

Le LLM ne fait que *proposer* : la validation (bornes, durées, doublons) est
assurée par ``clipagent.selection``, qui reste une logique pure et testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .models import ClipProposal
from .transcript import Transcript

AGENT_INSTRUCTIONS = """
Tu es un monteur vidéo spécialisé dans le « clipping » de contenu long
(podcasts, webinaires, conférences, cours) en extraits courts et verticals.

OBJECTIF
Sélectionner les extraits les plus « partageables » : autonomes, comprhensibles
hors contexte, accrocheurs dès la première seconde.

MÉTHODE
1. Commence par lire la transcription (outil `read_transcript`) : d'abord un
   survol (tête + chronologie), puis les zones qui t'intéressent.
2. Repère les moments forts : annonces de résultats, chiffres marquants,
   counterintuitive, demonstrations pratiques, questions rhétoriques, phrases
   à forte charge émotionnelle, résolutions de problème.
3. Pour chaque candidat, appelle `propose_clip` avec :
   - start / end : bornes en secondes, issues de la transcription ;
   - title : accroche courte (< 70 caractères) ;
   - reason : pourquoi c'est un bon extrait (une phrase) ;
   - score : confiance entre 0 et 1 ;
   - tags : 0 à 4 mots-clés.
4. Appelle `finish_selection` une fois tes propositions enregistrées.

CONTRAINTES
- Respecte strictement min_clip et max_clip secondes indiqués dans la demande.
- Un extrait doit commencer sur un début de phrase et finir sur une fin de
  phrase : jamais au milieu d'une phrase.
- Deux extraits ne doivent pas se recouvrir fortement : privilégie des zones
  distinctes de la vidéo.
- Ne propose jamais d'extrait hors de la durée de la vidéo.
- Vise des extraits qui fonctionnent coupés verticalement (9:16) : évite les
  moments nécessitant de lire un tableau ou un texte large à l'écran.

Si la transcription est pauvre, propose malgré tout les meilleurs segments
disponibles plutôt que de ne rien retourner.
""".strip()


@dataclass
class AgentContext:
    """Mémoire partagée entre l'agent et ses outils."""

    transcript: Transcript
    duration: float = 0.0
    min_clip: float = 20.0
    max_clip: float = 90.0
    max_clips: int = 5
    proposals: list[ClipProposal] = field(default_factory=list)
    finished: bool = False
    notes: list[str] = field(default_factory=list)

    def add(self, proposal: ClipProposal) -> int:
        self.proposals.append(proposal)
        return len(self.proposals)


def _build_tools(context: AgentContext):
    """Crée les outils exposés à l'agent (import différé pour ne pas dépendre du SDK)."""
    from agents import function_tool

    @function_tool
    def read_transcript(start: float, end: float) -> str:
        """Lit la transcription entre deux bornes (secondes) et la retourne horodatée."""
        if end <= start:
            return "Intervalle invalide : end doit être > start."
        if context.duration and end > context.duration:
            end = context.duration
        return context.transcript.window_text(start, end)

    @function_tool
    def read_transcript_head(limit: int = 40) -> str:
        """Lit les N premiers segments de la transcription (vue d'ensemble)."""
        limit = max(1, min(int(limit), 400))
        segments = context.transcript.segments[:limit]
        return "\n".join(
            f"[{s.start:.2f} - {s.end:.2f}] {s.text}" for s in segments
        )

    @function_tool
    def propose_clip(
        start: float,
        end: float,
        title: str,
        reason: str = "",
        score: float = 0.5,
        tags: list[str] | None = None,
    ) -> str:
        """Enregistre une proposition d'extrait (bornes en secondes)."""
        proposal = ClipProposal(
            start=float(start),
            end=float(end),
            title=str(title),
            reason=str(reason),
            score=float(score),
            tags=[str(t) for t in (tags or [])],
        )
        count = context.add(proposal)
        return f"Proposition #{count} enregistrée : {proposal.start:.1f}s → {proposal.end:.1f}s « {proposal.title} »."

    @function_tool
    def finish_selection() -> str:
        """Signale la fin de la sélection des extraits."""
        context.finished = True
        return f"Sélection terminée : {len(context.proposals)} proposition(s)."

    return [read_transcript, read_transcript_head, propose_clip, finish_selection]


def build_agent(settings: Settings, context: AgentContext):
    """Construit l'agent OpenAI Agents SDK."""
    from agents import Agent, ModelSettings

    return Agent(
        name="Highlight Analyst",
        instructions=AGENT_INSTRUCTIONS,
        model=settings.model,
        tools=_build_tools(context),
        model_settings=ModelSettings(
            temperature=0.2,
            tool_choice="auto",
        ),
    )


def build_user_request(settings: Settings, context: AgentContext, extra_instruction: str = "") -> str:
    """Message utilisateur décrivant la mission courante."""
    duration = context.duration or context.transcript.duration
    request = (
        "Analyse la transcription ci-dessous et sélectionne les meilleurs extraits.\n\n"
        f"- Durée de la vidéo : {duration:.1f} s\n"
        f"- Nombre d'extraits souhaité : {context.max_clips}\n"
        f"- Durée d'un extrait : entre {context.min_clip:.0f} s et {context.max_clip:.0f} s\n"
        f"- Format cible : {settings.aspect_ratio} ({settings.width}x{settings.height})\n"
        f"- Langue : {settings.language}\n\n"
        "TRANSCRIPTION (début) :\n"
        f"{context.transcript.to_markdown(max_chars=12000)}\n"
    )
    if extra_instruction:
        request += f"\nConsignes complémentaires de l'utilisateur :\n{extra_instruction}\n"
    request += (
        "\nRappel : utilise `read_transcript` pour explorer la suite, `propose_clip` pour "
        "chaque extrait, puis `finish_selection`."
    )
    return request


def run_agent(
    transcript: Transcript,
    settings: Settings,
    *,
    duration: float | None = None,
    extra_instruction: str = "",
    max_turns: int = 25,
) -> tuple[list[ClipProposal], AgentContext]:
    """Exécute l'agent et renvoie les propositions brutes + le contexte."""
    import os

    from agents import Runner

    if settings.api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.api_key)

    context = AgentContext(
        transcript=transcript,
        duration=duration or transcript.duration,
        min_clip=settings.min_clip_seconds,
        max_clip=settings.max_clip_seconds,
        max_clips=settings.num_clips,
    )
    agent = build_agent(settings, context)
    request = build_user_request(settings, context, extra_instruction)
    Runner.run_sync(agent, request, max_turns=max_turns)
    return context.proposals, context


def parse_llm_json(payload: Any) -> list[ClipProposal]:
    """Extrait des propositions d'une réponse JSON éventuelle (mode structuré)."""
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("clips") or payload.get("proposals") or []
    elif isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return []
        return parse_llm_json(parsed)
    else:
        return []

    proposals: list[ClipProposal] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        proposals.append(
            ClipProposal(
                start=start,
                end=end,
                title=str(item.get("title", "Extrait")),
                reason=str(item.get("reason", "")),
                score=float(item.get("score", 0.5) or 0.5),
                tags=[str(t) for t in (item.get("tags") or [])],
            )
        )
    return proposals
