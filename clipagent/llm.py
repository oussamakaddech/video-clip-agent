"""Agent IA (OpenAI Agents SDK) chargé de sélectionner les extraits.

Le LLM ne fait que *proposer* : la validation (bornes, durées, doublons) est
assurée par ``clipagent.selection``, qui reste une logique pure et testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .models import ClipProposal, Segment
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


LIVESTREAM_GUIDANCE = """
CONTEXTE LIVESTREAM (VOD longue)
- Une VOD de plusieurs heures contient des phases très différentes : lancement,
  discussion,jeu, réaction au chat, annonce, démonstration, débat, fin de stream.
- Cherche les pics : reaction vive du streamer, moment drôle, annonce importante,
  chiffre marquant, émotion forte, réponse à une question du chat, palmares.
- Ignore les phases vides : attente, discussion administrative, générique de fin,
  pauses longues sans contenu.
- Chaque extrait doit rester compréhensible sans avoir vu le reste du live :
  commence par une phrase qui pose le sujet.
- Ne propose jamais deux extraits qui parlent de la même chose.
""".strip()


HOOK_GUIDANCE = """
HOOK (accroche des 3 premières secondes — format TikTok / Reels / Shorts)
Pour chaque extrait, renseigne `hook` : une accroche courte
- 4 à 9 mots, 45 caractères maximum ;
- qui donne envie de rester (question, chiffre, promesse, contradiction) ;
- compréhensible seule, sans le contexte de la vidéo ;
- dans la langue du contenu de la vidéo ;
- pas de ponctuation finale, pas d'introduction, pas de nom de l'auteur.

Exemples (français) : « Et si l'IA faisait tout le montage ? », « On a doublé l'engagement en un mois ».
Exemples (arabe) : « هل يمكن للذكاء الاصطناعي أن يقص الفيديو؟ », « ضاعفنا التفاعل في شهر واحد ».
""".strip()


ARABIC_GUIDANCE = """
LANGUE : le contenu est en ARABE.
- Rédige `title`, `reason` et `hook` en arabe.
- Respecte la ponctuation arabe (، ؟) et n'utilise pas de latin pour les mots arabes.
- Les timestamps restent en secondes ; le hook doit être en arabe, lisible de droite à gauche.
""".strip()


def instructions_for(settings: Settings) -> str:
    """Construit les instructions de l'agent selon la langue et le profil."""
    parts = [AGENT_INSTRUCTIONS]
    if settings.profile == "livestream":
        parts.append(LIVESTREAM_GUIDANCE)
    if settings.hook_enabled:
        parts.append(HOOK_GUIDANCE)
    code = (settings.language or "").lower().split("-")[0]
    if code in {"ar", "fa", "he", "ur"}:
        parts.append(ARABIC_GUIDANCE)
    return "\n\n".join(parts)


@dataclass
class AgentContext:
    """Mémoire partagée entre l'agent et ses outils."""

    transcript: Transcript
    duration: float = 0.0
    min_clip: float = 20.0
    max_clip: float = 90.0
    max_clips: int = 5
    chunk_start: float = 0.0
    chunk_end: float = 0.0
    proposals: list[ClipProposal] = field(default_factory=list)
    finished: bool = False
    notes: list[str] = field(default_factory=list)

    def add(self, proposal: ClipProposal) -> int:
        self.proposals.append(proposal)
        return len(self.proposals)


def _build_tools(context: AgentContext, *, strict: bool = True):
    """Crée les outils exposés à l'agent (import différé pour ne pas dépendre du SDK)."""
    from agents import function_tool

    @function_tool(strict_mode=strict)
    def read_transcript(start: float, end: float) -> str:
        """Lit la transcription entre deux bornes (secondes) et la retourne horodatée."""
        if end <= start:
            return "Intervalle invalide : end doit être > start."
        if context.duration and end > context.duration:
            end = context.duration
        window = context.transcript.window(start, end)
        if window:
            return context.transcript.window_text(start, end)
        # Plage vide : on indique la prochaine contenu disponible pour éviter
        # que l'agent boucle sur des trous.
        following = [s for s in context.transcript.segments if s.start >= end]
        if following:
            nxt = following[0]
            return (
                f"Aucun contenu entre {start:.0f} s et {end:.0f} s. "
                f"Le contenu suivant commence à {nxt.start:.0f} s."
            )
        previous = [s for s in context.transcript.segments if s.end <= start]
        if previous:
            prev = previous[-1]
            return (
                f"Aucun contenu entre {start:.0f} s et {end:.0f} s. "
                f"Le dernier contenu disponible se termine à {prev.end:.0f} s."
            )
        return f"Aucun contenu entre {start:.0f} s et {end:.0f} s."

    @function_tool(strict_mode=strict)
    def read_transcript_head(limit: int = 40) -> str:
        """Lit les N premiers segments de la transcription (vue d'ensemble)."""
        limit = max(1, min(int(limit), 400))
        segments = context.transcript.segments[:limit]
        return "\n".join(
            f"[{s.start:.2f} - {s.end:.2f}] {s.text}" for s in segments
        )

    @function_tool(strict_mode=strict)
    def propose_clip(
        start: float,
        end: float,
        title: str,
        reason: str = "",
        score: float = 0.5,
        tags: list[str] | None = None,
        hook: str = "",
    ) -> str:
        """Enregistre une proposition d'extrait (bornes en secondes)."""
        proposal = ClipProposal(
            start=float(start),
            end=float(end),
            title=str(title),
            reason=str(reason),
            score=float(score),
            tags=[str(t) for t in (tags or [])],
            hook=str(hook),
        )
        count = context.add(proposal)
        return f"Proposition #{count} enregistrée : {proposal.start:.1f}s → {proposal.end:.1f}s « {proposal.title} »."

    @function_tool(strict_mode=strict)
    def finish_selection() -> str:
        """Signale la fin de la sélection des extraits."""
        context.finished = True
        return f"Sélection terminée : {len(context.proposals)} proposition(s)."

    return [read_transcript, read_transcript_head, propose_clip, finish_selection]


def resolve_model(settings: Settings):
    """Retourne le modèle à utiliser.

    - endpoint OpenAI standard → modèle par défaut du SDK (API Responses) ;
    - endpoint compatible OpenAI tiers (NVIDIA, Together, vLLM…) → client
      Chat Completions dédié, car l'API ``/responses`` n'y existe pas.
    """
    if not settings.base_url and not settings.chat_completions:
        return settings.model

    from openai import AsyncOpenAI

    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

    client = AsyncOpenAI(
        api_key=settings.api_key or "EMPTY",
        base_url=settings.base_url or None,
    )
    return OpenAIChatCompletionsModel(model=settings.model, openai_client=client)


def build_agent(settings: Settings, context: AgentContext):
    """Construit l'agent OpenAI Agents SDK."""
    from agents import Agent, ModelSettings

    return Agent(
        name="Highlight Analyst",
        instructions=instructions_for(settings),
        model=resolve_model(settings),
        tools=_build_tools(context, strict=settings.strict_tools),
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
        f"- Plage couverte par CETTE portion de transcription : "
        f"{context.chunk_start:.1f} s → {context.chunk_end:.1f} s\n"
        f"- Nombre d'extraits souhaité : {context.max_clips}\n"
        f"- Durée d'un extrait : entre {context.min_clip:.0f} s et {context.max_clip:.0f} s\n"
        f"- Langue de rédaction de `title`, `reason` et `hook` : "
        f"{settings.language or 'la langue de la transcription'} (si la transcription "
        "est en anglais, écris en anglais ; si elle est en arabe, écris en arabe)\n"
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


def _run_agent_sync(agent, request: str, *, max_turns: int, run_config):
    """Exécute l'agent hors de toute boucle d'événements active.

    Playwright (mode synchrone) fait tourner une boucle asyncio dans le thread
    courant : ``Runner.run_sync`` y refuse de s'exécuter. On déporte donc
    l'appel dans un thread de travail, où aucune boucle n'est active.
    """
    import asyncio
    import threading

    from agents import Runner

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return Runner.run_sync(agent, request, max_turns=max_turns, run_config=run_config)

    outcome: dict[str, object] = {}

    def worker() -> None:
        try:
            outcome["value"] = Runner.run_sync(
                agent, request, max_turns=max_turns, run_config=run_config
            )
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc

    thread = threading.Thread(target=worker, name="clipagent-agent")
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome.get("value")


def run_agent(
    transcript: Transcript,
    settings: Settings,
    *,
    duration: float | None = None,
    extra_instruction: str = "",
    max_turns: int = 40,
) -> tuple[list[ClipProposal], AgentContext]:
    """Exécute l'agent et renvoie les propositions brutes + le contexte."""
    import os

    from agents import RunConfig

    if settings.api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.api_key)
    if settings.base_url:
        os.environ.setdefault("OPENAI_BASE_URL", settings.base_url)
    if not settings.tracing:
        # Le tracing du SDK appelle l'API OpenAI : inutile (et 401) avec un endpoint tiers.
        os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")

    context = AgentContext(
        transcript=transcript,
        duration=duration or transcript.duration,
        min_clip=settings.min_clip_seconds,
        max_clip=settings.max_clip_seconds,
        max_clips=settings.num_clips,
    )
    agent = build_agent(settings, context)
    request = build_user_request(settings, context, extra_instruction)
    from agents import RunConfig

    run_config = RunConfig(tracing_disabled=not settings.tracing)
    _run_agent_sync(agent, request, max_turns=max_turns, run_config=run_config)
    return context.proposals, context


def split_transcript(
    transcript: Transcript,
    *,
    chunk_chars: int = 12_000,
    overlap_chars: int = 800,
) -> list[list[Segment]]:
    """Découpe la transcription en portions analysables par l'agent.

    Une VOD de plusieurs heures ne tient pas dans un seul prompt : on analyse
    donc la transcription portion par portion, avec un léger recouvrement pour
    ne pas couper un extrait au milieu d'une phrase.
    """
    if not transcript.segments:
        return []

    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0

    for segment in transcript.segments:
        current.append(segment)
        size += len(segment.text)

        if size >= chunk_chars:
            chunks.append(current)
            # recouvrement : les derniers segments sont rejoués au début de la portion suivante
            overlap = current[-2:] if len(current) >= 2 else current[-1:]
            current = list(overlap)
            size = sum(len(s.text) for s in overlap)

    if current:
        chunks.append(current)
    return chunks


def run_agent_chunked(
    transcript: Transcript,
    settings: Settings,
    *,
    duration: float | None = None,
    extra_instruction: str = "",
    max_chunks: int | None = None,
    max_turns: int = 40,
) -> tuple[list[ClipProposal], int]:
    """Analyse la transcription portion par portion et fusionne les propositions.

    Retourne les propositions et le nombre de portions analysées.
    """
    chunks = split_transcript(transcript, chunk_chars=settings.chunk_chars)
    if max_chunks:
        chunks = chunks[:max_chunks]
    if not chunks:
        return [], 0

    all_proposals: list[ClipProposal] = []
    for chunk in chunks:
        sub = Transcript(segments=chunk, source=transcript.source)
        context = AgentContext(
            transcript=sub,
            duration=duration or transcript.duration,
            min_clip=settings.min_clip_seconds,
            max_clip=settings.max_clip_seconds,
            max_clips=settings.num_clips,
            chunk_start=chunk[0].start,
            chunk_end=chunk[-1].end,
        )
        agent = build_agent(settings, context)
        request = build_user_request(settings, context, extra_instruction)
        from agents import RunConfig

        if not settings.tracing:
            import os

            os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
        run_config = RunConfig(tracing_disabled=not settings.tracing)
        _run_agent_sync(agent, request, max_turns=max_turns, run_config=run_config)
        all_proposals.extend(context.proposals)

    return all_proposals, len(chunks)


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
