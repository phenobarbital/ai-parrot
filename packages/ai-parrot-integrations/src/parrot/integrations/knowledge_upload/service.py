"""Platform-agnostic knowledge upload service (FEAT-647)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from parrot.auth.userinfo import EmployeeProfile, UserInfoService

from .models import KnowledgeUploadConfig, UploaderIdentity, UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind
from .policy import UploadPolicy, resolve_profile
from .staging import safe_filename, staged_file, sweep_staging
from .targets.base import IngestTarget

Notify = Callable[[UploadOutcome], Awaitable[None]]

audit_logger = logging.getLogger("parrot.integrations.knowledge_upload.audit")

# Process-wide: every service instance (one per bot wrapper) shares these locks (AC12).
_TARGET_LOCKS: dict[Path, asyncio.Lock] = {}


def _target_lock(key: Path) -> asyncio.Lock:
    """Return the process-wide lock for a resolved target root."""
    lock = _TARGET_LOCKS.get(key)
    if lock is None:
        lock = _TARGET_LOCKS[key] = asyncio.Lock()
    return lock


class KnowledgeUploadService:
    """Authorize, validate, stage, ingest, delete, audit and notify."""

    def __init__(
        self,
        config: KnowledgeUploadConfig,
        targets: dict[UploadTargetKind, IngestTarget],
        userinfo: UserInfoService | None = None,
    ) -> None:
        """Initialize the service with already-constructed usable targets."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._targets = dict(targets)
        self._userinfo = userinfo or UserInfoService()
        self._policy = UploadPolicy(config.allowed_usernames, config.allowed_groups)
        self._semaphore = asyncio.Semaphore(config.max_concurrent_jobs)
        self._jobs: set[asyncio.Task[None]] = set()

    @classmethod
    async def from_config(cls, config: KnowledgeUploadConfig) -> KnowledgeUploadService:
        """Build targets, retaining only available ones after sweeping their staging paths."""
        from .targets import build_targets

        logger = logging.getLogger(__name__)
        available_targets: dict[UploadTargetKind, IngestTarget] = {}
        for kind, target in build_targets(config).items():
            try:
                usable, reason = await target.available()
            except Exception:  # noqa: BLE001 - target availability must not block other targets
                logger.warning("Knowledge upload target %s is unavailable", kind.value, exc_info=True)
                continue
            if not usable:
                logger.warning("Knowledge upload target %s is unavailable: %s", kind.value, reason)
                continue
            await asyncio.to_thread(sweep_staging, target.staging_dir)
            available_targets[kind] = target
        return cls(config, available_targets)

    def available_targets(self) -> set[UploadTargetKind]:
        """Return targets that passed the startup availability check."""
        return set(self._targets)

    def max_bytes(self, platform_cap_mb: int | None = None) -> int:
        """Return the applicable maximum upload size in bytes."""
        mb = self.config.max_size_mb if platform_cap_mb is None else min(self.config.max_size_mb, platform_cap_mb)
        return mb * 1024 * 1024

    async def authorize(self, identity: UploaderIdentity) -> EmployeeProfile | None:
        """Return an allowed profile, or ``None`` after auditing a denial."""
        profile = await resolve_profile(identity, self._userinfo)
        if self._policy.is_allowed(profile):
            return profile
        self._audit(
            platform=identity.platform,
            username=profile.username if profile and profile.username else identity.platform_user_id,
            target="",
            filename="",
            sha256="",
            size=0,
            status=UploadStatus.DENIED,
            triage_action=None,
            duration=0.0,
        )
        return None

    async def submit(self, request: UploadRequest, notify: Notify) -> UploadOutcome:
        """Validate and schedule a job, or return an immediate rejected outcome."""
        job_id = uuid.uuid4().hex[:12]
        target = self._targets.get(request.target)
        if target is None:
            return self._invalid_outcome(job_id, request, "This upload target is unavailable.")
        try:
            suffix = Path(safe_filename(request.filename)).suffix.casefold()
        except ValueError:
            return self._invalid_outcome(job_id, request, "The filename is invalid.")
        if suffix not in {extension.casefold() for extension in self.config.allowed_extensions}:
            return self._invalid_outcome(job_id, request, "This file type is not supported.")
        if len(request.data) > self.max_bytes():
            return self._invalid_outcome(job_id, request, "This file is too large.")
        profile = await self.authorize(request.identity)
        if profile is None:
            return UploadOutcome(
                job_id=job_id,
                status=UploadStatus.DENIED,
                target=request.target,
                filename=request.filename,
                message="You are not allowed to upload knowledge.",
            )

        task = asyncio.create_task(self._run_job(job_id, request, profile, notify))
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)
        return UploadOutcome(
            job_id=job_id,
            status=UploadStatus.ACCEPTED,
            target=request.target,
            filename=request.filename,
            message=f"Received {request.filename} → {request.target.value}. Processing…",
        )

    async def _run_job(
        self, job_id: str, request: UploadRequest, profile: EmployeeProfile, notify: Notify
    ) -> None:
        """Run one staged upload and report its terminal outcome."""
        target = self._targets[request.target]
        started = time.monotonic()
        sha256 = hashlib.sha256(request.data).hexdigest()
        try:
            async with self._semaphore, _target_lock(target.lock_key.resolve()):
                async with staged_file(target.staging_dir, request.filename, request.data) as staged:
                    outcome = await target.ingest(staged, request, job_id)
        except asyncio.CancelledError:
            outcome = UploadOutcome(
                job_id=job_id,
                status=UploadStatus.FAILED,
                target=request.target,
                filename=request.filename,
                message=f"Upload cancelled (job {job_id}).",
            )
            self._audit_outcome(request, profile, outcome, sha256, time.monotonic() - started)
            await self._notify(notify, outcome)
            raise
        except Exception:  # noqa: BLE001 - any target failure becomes a failed user-facing outcome
            self.logger.exception("knowledge upload job %s failed", job_id)
            outcome = UploadOutcome(
                job_id=job_id,
                status=UploadStatus.FAILED,
                target=request.target,
                filename=request.filename,
                message=f"Upload failed (job {job_id}).",
            )
        self._audit_outcome(request, profile, outcome, sha256, time.monotonic() - started)
        await self._notify(notify, outcome)

    async def shutdown(self) -> None:
        """Cancel running jobs and await them."""
        for task in list(self._jobs):
            task.cancel()
        await asyncio.gather(*self._jobs, return_exceptions=True)

    def _invalid_outcome(self, job_id: str, request: UploadRequest, message: str) -> UploadOutcome:
        """Create and audit an invalid submission result."""
        outcome = UploadOutcome(
            job_id=job_id,
            status=UploadStatus.INVALID,
            target=request.target,
            filename=request.filename,
            message=message,
        )
        self._audit(
            platform=request.identity.platform,
            username=request.identity.platform_user_id,
            target=request.target.value,
            filename=request.filename,
            sha256="",
            size=len(request.data),
            status=outcome.status,
            triage_action=None,
            duration=0.0,
        )
        return outcome

    def _audit_outcome(
        self,
        request: UploadRequest,
        profile: EmployeeProfile,
        outcome: UploadOutcome,
        sha256: str,
        duration: float,
    ) -> None:
        """Emit the structured audit record for a completed attempt."""
        self._audit(
            platform=request.identity.platform,
            username=profile.username or request.identity.platform_user_id,
            target=request.target.value,
            filename=request.filename,
            sha256=sha256,
            size=len(request.data),
            status=outcome.status,
            triage_action=outcome.detail.get("triage_action"),
            duration=duration,
        )

    def _audit(
        self,
        *,
        platform: str,
        username: str,
        target: str,
        filename: str,
        sha256: str,
        size: int,
        status: UploadStatus,
        triage_action: object | None,
        duration: float,
    ) -> None:
        """Log one structured audit record without exposing it to the uploader."""
        audit_logger.info(
            "knowledge upload attempt",
            extra={
                "platform": platform,
                "username": username,
                "target": target,
                "filename": filename,
                "sha256": sha256,
                "size": size,
                "status": status.value,
                "triage_action": triage_action,
                "duration": duration,
            },
        )

    async def _notify(self, notify: Notify, outcome: UploadOutcome) -> None:
        """Notify the adapter while keeping notification failures out of the job lifecycle."""
        try:
            await notify(outcome)
        except Exception:  # noqa: BLE001 - notification delivery must not affect ingestion
            self.logger.exception("knowledge upload notification failed for job %s", outcome.job_id)
