"""A2UI delivery bridge (Module 7, first half).

Maps a baked :class:`~parrot.outputs.a2ui.artifacts.RenderedArtifact` onto the EXISTING
``NotificationMixin.send_notification`` machinery (spec G5) — never a new delivery stack.
Attachments flow through the mixin's ``report.files`` PRIORITY-1 extraction path.

Per-provider policy:
* **EMAIL / TELEGRAM** — full attachment via ``report.files`` (works today, no mixin change).
* **SLACK** — no file upload (spec Non-Goal); a public artifact URL line is appended in
  ``_send_slack`` (the bridge computes it via ``ArtifactStore.get_public_url`` and passes
  it as a kwarg). Degraded delivery is logged, never silent.
* **TEAMS** — unchanged filenames-in-text today; real Graph upload is TASK-1734.

One-way import rule (G8): this module never imports agents/DatasetManager/LLM clients,
nor the notifications subsystem — the provider is passed as a string (matching the
``NotificationProvider`` enum *values*) and the mixin-bearing owner is passed in.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from parrot.outputs.a2ui.artifacts import RenderedArtifact

__all__ = ["deliver_artifact"]

logger = logging.getLogger(__name__)

# NotificationProvider enum *values* (kept as plain strings — no import of the
# notifications subsystem from a2ui core, per G8).
_EMAIL = "email"
_SLACK = "slack"
_TELEGRAM = "telegram"
_TEAMS = "teams"


def _provider_name(provider: Any) -> str:
    """Normalize a provider (enum or str) to its lowercase string value."""
    value = provider.value if hasattr(provider, "value") else str(provider)
    return value.lower()


class _DeliveryReport:
    """Minimal report exposing ``.files`` for ``_extract_message_content`` PRIORITY 1."""

    def __init__(self, files: list[Path]) -> None:
        self.files = files
        self.documents = None


def _write_inline_to_temp(artifact: RenderedArtifact) -> Path:
    """Materialize inline content to a temp file that PRESERVES the delivery filename.

    The bytes are written into a per-request temp *directory* using the artifact's own
    ``filename`` as the basename, so email attachments / Telegram documents / Teams Graph
    uploads display the intended name (not a random ``mkstemp`` name). The caller cleans
    up the whole directory after send. (Blocking file I/O — call via ``asyncio.to_thread``.)
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="a2ui-"))
    # Basename only — never honour path separators from the artifact filename.
    filename = Path(artifact.filename).name or "artifact"
    dest = tmp_dir / filename
    dest.write_bytes(artifact.content or b"")
    return dest


async def _ensure_path(artifact: RenderedArtifact) -> tuple[Path, bool]:
    """Return a filesystem path for the artifact, materializing inline content.

    Returns:
        ``(path, is_temp)`` — ``is_temp`` is ``True`` when a temp file was created (its
        parent directory must be removed by the caller after send).
    """
    if artifact.path is not None:
        return artifact.path, False
    # Off the event loop — blocking file write.
    path = await asyncio.to_thread(_write_inline_to_temp, artifact)
    return path, True


async def deliver_artifact(
    owner: Any,
    artifact: RenderedArtifact,
    *,
    recipients: Any,
    provider: Any = _EMAIL,
    message: str = "",
    subject: Optional[str] = None,
    artifact_store: Any = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Deliver a ``RenderedArtifact`` via ``owner.send_notification`` (per-provider policy).

    Args:
        owner: A ``NotificationMixin``-bearing object (e.g. ``BasicAgent``).
        artifact: The baked artifact to deliver.
        recipients: Recipient(s) in the provider's expected shape.
        provider: Delivery provider.
        message: Message text.
        subject: Optional subject (email).
        artifact_store: ``ArtifactStore`` for computing a Slack public URL.
        user_id / agent_id / session_id: Delivery context for ``get_public_url``.

    Returns:
        The ``send_notification`` result dict.
    """
    provider_name = _provider_name(provider)
    log = getattr(owner, "logger", logger)

    if provider_name == _SLACK:
        public_url = None
        if artifact.source_envelope_ref and artifact_store and user_id and agent_id and session_id:
            public_url = await artifact_store.get_public_url(
                user_id, agent_id, session_id, artifact.source_envelope_ref
            )
        if public_url:
            log.warning(
                "A2UI degraded delivery: Slack cannot attach files; sending public URL "
                "for artifact %s.",
                artifact.artifact_id,
            )
            return await owner.send_notification(
                message,
                recipients,
                provider=provider,
                subject=subject,
                a2ui_artifact_url=public_url,
            )
        log.warning(
            "A2UI degraded delivery: Slack text-only for artifact %s (no persisted "
            "artifact URL available).",
            artifact.artifact_id,
        )
        return await owner.send_notification(
            message, recipients, provider=provider, subject=subject
        )

    # EMAIL / TELEGRAM / TEAMS → attachment via report.files precedence. (Teams'
    # own Graph-upload-vs-downgrade decision + logging lives in _send_teams.)
    path, is_temp = await _ensure_path(artifact)
    try:
        report = _DeliveryReport(files=[path])
        return await owner.send_notification(
            message, recipients, provider=provider, subject=subject, report=report
        )
    finally:
        if is_temp:
            # Remove the per-request temp directory (contains the named file).
            await asyncio.to_thread(shutil.rmtree, path.parent, True)
