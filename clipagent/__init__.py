"""clipagent — Agent IA de clipping vidéo.

Sélectionne automatiquement les moments forts d'une vidéo longue à partir de
sa transcription, puis rend des extraits verticaux (9:16) sous-titrés.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import Settings
from .models import Clip, ClipProposal, Segment
from .pipeline import Plan, plan_clips, render_plan, run_pipeline, save_report
from .selection import heuristic_proposals, validate_proposals
from .transcript import Transcript, load_transcript, parse_srt, parse_vtt

__all__ = [
    "Clip",
    "ClipProposal",
    "Plan",
    "Segment",
    "Settings",
    "Transcript",
    "heuristic_proposals",
    "load_transcript",
    "parse_srt",
    "parse_vtt",
    "plan_clips",
    "render_plan",
    "run_pipeline",
    "save_report",
    "validate_proposals",
    "__version__",
]
