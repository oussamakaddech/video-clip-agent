"""Schémas de l'API (validation des requêtes)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ClipJobRequest(BaseModel):
    """Demande de clipping envoyée par l'interface web."""

    url: str | None = Field(default=None, description="URL de la VOD (Kick, YouTube…)")
    video_path: str | None = Field(default=None, description="Chemin d'une vidéo locale")
    transcript_path: str | None = Field(default=None, description="Transcription SRT/VTT existante")
    upload_name: str | None = Field(default=None, description="Nom du fichier téléversé")

    style: str = Field(default="default")
    profile: str = Field(default="default")
    language: str | None = None
    num_clips: int = Field(default=6, ge=1, le=30)
    min_clip: float = Field(default=45, ge=5, le=600)
    max_clip: float = Field(default=75, ge=10, le=900)
    whisper_model: str = Field(default="base")
    instruction: str = ""
    logo: str | None = None
    subtitles: bool = True
    facecam: bool | None = None
    render: bool = True

    @field_validator("max_clip")
    @classmethod
    def _max_greater_than_min(cls, value: float, info):
        minimum = info.data.get("min_clip")
        if minimum is not None and value < minimum:
            raise ValueError("max_clip doit être supérieur à min_clip")
        return value

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("L'URL doit commencer par http:// ou https://")
        return value


class JobSummary(BaseModel):
    """Résumé d'une tâche (liste)."""

    id: str
    status: str
    progress: float
    message: str
    created_at: str


class HealthResponse(BaseModel):
    """État du service."""

    status: str
    version: str
    jobs: int
    ffmpeg: bool
    llm: bool
    whisper: bool
    opencv: bool
    free_disk_mb: int
