"""Gestion des tâches de clipping (exécution en arrière-plan + suivi)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..service import ClipRequest, unique_output_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    """Une tâche de clipping et son état."""

    id: str
    request: ClipRequest
    status: str = "queued"          # queued | running | done | error | cancelled
    progress: float = 0.0
    message: str = "En attente…"
    logs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    output_dir: Path | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cancelled: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "message": self.message,
            "logs": self.logs[-60:],
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    """File de tâches : chaque job tourne dans son propre thread.

    Un contrôle de concurrence évite de lancer plusieurs navigateurs (très
    gourmand en mémoire) en même temps ; les tâches excédentaires attendent.
    """

    def __init__(self, output_root: str | Path = "output", *, max_concurrent: int = 2) -> None:
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max(1, int(max_concurrent))
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(self.max_concurrent)

    # --- Accès -------------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    @property
    def running(self) -> int:
        return sum(1 for job in self.list() if job.status in {"queued", "running"})

    # --- Cycle de vie -----------------------------------------------------
    def submit(self, request: ClipRequest, *, render: bool = True) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], request=request)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job, render), daemon=True)
        thread.start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job and job.status in {"queued", "running"}:
            job.cancelled = True
            job.message = "Annulation demandée…"
            return True
        return False

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def purge(self, keep: int = 20) -> int:
        """Supprime les tâches terminées les plus anciennes (libère la mémoire)."""
        with self._lock:
            finished = [j for j in self._jobs.values() if j.status in {"done", "error", "cancelled"}]
            finished.sort(key=lambda j: j.created_at)
            removed = 0
            for job in finished[:-keep] if len(finished) > keep else []:
                self._jobs.pop(job.id, None)
                removed += 1
            return removed

    # --- Exécution --------------------------------------------------------
    def _log(self, job: Job, message: str, ratio: float | None = None) -> None:
        stamp = time.strftime("%H:%M:%S")
        job.logs.append(f"[{stamp}] {message}")
        job.message = message
        if ratio is not None:
            job.progress = max(0.0, min(1.0, ratio))

    def _run(self, job: Job, render: bool) -> None:
        from ..service import analyze, render as render_clips

        job.status = "running"
        job.started_at = _now()
        out_dir = unique_output_dir(self.output_root, prefix="job")
        job.output_dir = out_dir
        self._log(job, "Tâche démarrée")

        def progress(message: str, ratio: float = 0.0) -> None:
            if job.cancelled:
                raise JobCancelled()
            self._log(job, message, ratio)

        try:
            with self._slots:            # concurrence bornée
                if job.cancelled:
                    raise JobCancelled()
                result = analyze(job.request, output_dir=out_dir, on_progress=progress)
                job.plan = result.plan  # type: ignore[attr-defined]
                if render:
                    result = render_clips(job.request, result.plan, output_dir=out_dir, on_progress=progress)
            job.result = result.to_dict()
            job.status = "done"
            job.progress = 1.0
            job.message = f"Terminé — {len(result.plan.clips)} extrait(s)"
            self._log(job, job.message, 1.0)
        except JobCancelled:
            job.status = "cancelled"
            job.message = "Annulé"
            self._log(job, "Tâche annulée")
        except Exception as exc:  # noqa: BLE001 - le job doit toujours se terminer
            job.status = "error"
            job.error = f"{exc.__class__.__name__}: {exc}"
            job.message = "Erreur"
            self._log(job, job.error)
        finally:
            job.finished_at = _now()


class JobCancelled(Exception):
    """Levée pour interrompre proprement une tâche."""
