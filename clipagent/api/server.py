"""API HTTP du projet (FastAPI) + interface web embarquée.

Endpoints
---------
``GET  /api/health``              état du service
``GET  /api/styles``              catalogue des styles / profils
``POST /api/jobs``                crée une tâche de clipping
``GET  /api/jobs``                liste des tâches
``GET  /api/jobs/{id}``           état détaillé d'une tâche
``DELETE /api/jobs/{id}``         annule / supprime une tâche
``GET  /api/jobs/{id}/events``    suivi en direct (SSE)
``GET  /api/jobs/{id}/clips/{n}`` télécharge un extrait
``GET  /api/jobs/{id}/best-of``   télécharge la vidéo best-of
``GET  /api/jobs/{id}/report``    rapport Markdown
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import Settings
from ..service import (
    ClipRequest,
    available_profiles,
    available_styles,
    disk_usage,
    free_space,
)
from .jobs import Job, JobManager
from .schemas import ClipJobRequest, HealthResponse, JobSummary

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
UPLOAD_DIR = Path("output/uploads")


def create_app(output_root: str | Path = "output") -> FastAPI:
    """Construit l'application FastAPI."""
    app = FastAPI(
        title="clipagent",
        version=__version__,
        description="Agent IA de clipping vidéo : analyse une VOD dans le navigateur, "
        "sélectionne les moments forts et rend des extraits verticaux.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    manager = JobManager(output_root)
    app.state.jobs = manager

    # --- API --------------------------------------------------------------
    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        settings = Settings.from_env()
        try:
            import importlib.util

            has_cv = importlib.util.find_spec("cv2") is not None
        except ImportError:
            has_cv = False
        try:
            has_whisper = importlib.util.find_spec("faster_whisper") is not None
        except ImportError:
            has_whisper = False
        return HealthResponse(
            status="ok",
            version=__version__,
            jobs=len(manager.list()),
            ffmpeg=bool(shutil.which("ffmpeg")) or _imageio_ffmpeg(),
            llm=bool(settings.api_key),
            whisper=has_whisper,
            opencv=has_cv,
            free_disk_mb=free_space(".") // (1024 * 1024),
        )

    @app.get("/api/styles")
    def styles() -> dict:
        return {"styles": available_styles(), "profiles": available_profiles()}

    @app.post("/api/jobs", response_model=JobSummary)
    def create_job(payload: ClipJobRequest) -> JobSummary:
        request = ClipRequest(
            url=payload.url,
            video_path=payload.video_path,
            transcript_path=payload.transcript_path,
            style=payload.style,
            profile=payload.profile,
            language=payload.language,
            num_clips=payload.num_clips,
            min_clip=payload.min_clip,
            max_clip=payload.max_clip,
            whisper_model=payload.whisper_model,
            instruction=payload.instruction,
            logo=payload.logo,
            subtitles=payload.subtitles,
            facecam=payload.facecam,
        )
        job = manager.submit(request, render=payload.render)
        return JobSummary(
            id=job.id,
            status=job.status,
            progress=job.progress,
            message=job.message,
            created_at=job.created_at,
        )

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)) -> dict:
        """Téléverse une vidéo ou une transcription."""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        target = UPLOAD_DIR / (file.filename or "upload.bin")
        with target.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        return {"path": str(target), "name": target.name, "size": target.stat().st_size}

    @app.get("/api/jobs")
    def list_jobs() -> list[JobSummary]:
        return [
            JobSummary(
                id=job.id,
                status=job.status,
                progress=job.progress,
                message=job.message,
                created_at=job.created_at,
            )
            for job in manager.list()
        ]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = _job_or_404(manager, job_id)
        return job.to_dict()

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str) -> dict:
        job = _job_or_404(manager, job_id)
        manager.cancel(job_id)
        if job.status not in {"running", "queued"}:
            manager.delete(job_id)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        """Suivi en direct (Server-Sent Events)."""
        job = _job_or_404(manager, job_id)

        async def stream():
            last = ""
            while True:
                payload = json.dumps(
                    {
                        "status": job.status,
                        "progress": round(job.progress, 3),
                        "message": job.message,
                        "logs": job.logs[-40:],
                        "error": job.error,
                        "result": job.result,
                    },
                    ensure_ascii=False,
                )
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                if job.status in {"done", "error", "cancelled"}:
                    break
                await asyncio.sleep(1.0)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/clips/{index}")
    def download_clip(job_id: str, index: int) -> FileResponse:
        job = _job_or_404(manager, job_id)
        clip = next((c for c in job.plan.clips if c.index == index), None)  # type: ignore[attr-defined]
        if clip is None or not clip.path:
            raise HTTPException(status_code=404, detail="Extrait introuvable")
        path = Path(clip.path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Fichier absent")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.get("/api/jobs/{job_id}/best-of")
    def download_best_of(job_id: str) -> FileResponse:
        job = _job_or_404(manager, job_id)
        path = _find(job.output_dir, "best_of.mp4")
        if path is None:
            raise HTTPException(status_code=404, detail="Vidéo best-of indisponible")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.get("/api/jobs/{job_id}/report")
    def download_report(job_id: str) -> PlainTextResponse:
        job = _job_or_404(manager, job_id)
        path = _find(job.output_dir, "clips_plan.md")
        if path is None:
            raise HTTPException(status_code=404, detail="Rapport indisponible")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/jobs/{job_id}/usage")
    def job_usage(job_id: str) -> dict:
        job = _job_or_404(manager, job_id)
        return {
            "output_dir": str(job.output_dir) if job.output_dir else None,
            "disk_mb": round(disk_usage(job.output_dir) / (1024 * 1024), 1) if job.output_dir else 0,
        }

    # --- Interface web ----------------------------------------------------
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/", response_class=HTMLResponse)
        def index() -> HTMLResponse:
            return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))

    return app


def _job_or_404(manager: JobManager, job_id: str) -> Job:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return job


def _find(folder: Path | None, name: str) -> Path | None:
    if not folder:
        return None
    direct = Path(folder) / name
    if direct.exists():
        return direct
    matches = sorted(Path(folder).rglob(name))
    return matches[0] if matches else None


def _imageio_ffmpeg() -> bool:
    try:
        import imageio_ffmpeg

        return bool(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return False


app = create_app()


def main() -> None:  # pragma: no cover - point d'entrée du serveur
    import uvicorn

    uvicorn.run(
        "clipagent.api.server:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
