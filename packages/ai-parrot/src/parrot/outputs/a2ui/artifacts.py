"""Rendered-artifact and deep-link models (Module 6).

Research confirmed no reusable rendered-file model exists anywhere in the monorepo,
so :class:`RenderedArtifact` is created here. A ``RenderedArtifact`` is the
self-contained, fully-baked output of a static renderer (PDF, email HTML, baked
document): it carries either inline ``content`` bytes XOR a ``path`` to a temp file
for attachment delivery, never both.

Core-side, dependency-free (spec G8): pydantic v2 + stdlib only.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["DeepLink", "RenderedArtifact"]


class DeepLink(BaseModel):
    """A single-use, TTL-bound deep link that resumes the originating channel.

    Minted by the Module 8 :class:`DeepLinkService`; the model itself ships here.

    Attributes:
        action_label: Human-readable label for the action the link resumes.
        url: Channel resume URL embedding the opaque token.
        token_id: Token identifier for audit / consume tracking.
        expires_at: Expiry timestamp (UTC).
    """

    action_label: str
    url: str
    token_id: str
    expires_at: datetime


class RenderedArtifact(BaseModel):
    """A baked, self-contained rendered output ready for delivery (spec §2, G5).

    Exactly one of ``content`` (inline bytes) or ``path`` (temp file) is set.

    Attributes:
        artifact_id: Unique id for this rendered artifact.
        mime_type: MIME type of the rendered content (e.g. ``application/pdf``).
        content: Inline bytes (XOR ``path``).
        path: Temp-file path for attachment delivery (XOR ``content``).
        filename: Suggested delivery filename.
        title: Human-readable title.
        surface: The renderer name that produced this artifact.
        source_envelope_ref: ``ArtifactStore`` id / S3 URI of the source envelope.
        deep_links: Deep links for actions degraded on this static surface.
        metadata: Free-form renderer metadata.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    artifact_id: str
    mime_type: str
    content: Optional[bytes] = None
    path: Optional[Path] = None
    filename: str
    title: str
    surface: str
    source_envelope_ref: Optional[str] = None
    deep_links: list[DeepLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_content_xor_path(self) -> "RenderedArtifact":
        """Enforce that exactly one of ``content`` / ``path`` is provided."""
        has_content = self.content is not None
        has_path = self.path is not None
        if has_content == has_path:
            raise ValueError(
                "RenderedArtifact requires exactly one of 'content' (inline bytes) "
                "or 'path' (temp file) — got "
                f"{'both' if has_content else 'neither'}."
            )
        return self
