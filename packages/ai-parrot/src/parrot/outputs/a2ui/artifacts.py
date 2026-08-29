"""Rendered-artifact and deep-link models (Module 6); structured artifacts[] helper (FEAT-473).

Research confirmed no reusable rendered-file model exists anywhere in the monorepo,
so :class:`RenderedArtifact` is created here. A ``RenderedArtifact`` is the
self-contained, fully-baked output of a static renderer (PDF, email HTML, baked
document): it carries either inline ``content`` bytes XOR a ``path`` to a temp file
for attachment delivery, never both.

Core-side, dependency-free (spec G8): pydantic v2 + stdlib only.

FEAT-473 (G5/G6) additionally appends :func:`attach_structured_artifact` — a
core helper that mints a ``response.artifacts[]`` entry for the deterministic
STRUCTURED_CHART/STRUCTURED_TABLE/STRUCTURED_MAP output modes. It supersedes
the FEAT-224 inline minting block in ``bots/data.py`` with a reusable
function so ``bots/database/agent.py`` can mint artifacts too.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.models.outputs import OutputMode
from parrot.outputs.a2ui.adapters.structured import SCHEMA_VERSION, root_component

__all__ = ["DeepLink", "RenderedArtifact", "attach_structured_artifact"]

logger = logging.getLogger(__name__)


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
    content: bytes | None = None
    path: Path | None = None
    filename: str
    title: str
    surface: str
    source_envelope_ref: str | None = None
    deep_links: list[DeepLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_content_xor_path(self) -> RenderedArtifact:
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


#: STRUCTURED_* output mode -> ``artifacts[].type`` (mirrors the FEAT-224
#: inline block previously in ``bots/data.py``).
_STRUCTURED_ARTIFACT_TYPE: dict[Any, str] = {
    OutputMode.STRUCTURED_CHART: "chart",
    OutputMode.STRUCTURED_MAP: "map",
    OutputMode.STRUCTURED_TABLE: "table",
}


def attach_structured_artifact(response: Any, output_mode: Any) -> str | None:
    """Mint a ``response.artifacts[]`` entry for a structured output mode (FEAT-473 G5/G6).

    With ``response.a2ui_envelope`` present (FEAT-473 dual-emit,
    ``StructuredOutputBase._route_envelope``), mints a v2 entry: ``definition``
    is the envelope's root component node (:func:`~parrot.outputs.a2ui.adapters.structured.root_component`),
    ``surfaceId == artifactId`` (the envelope's own surface id), and
    ``schemaVersion: 2``. Without an envelope, falls back to the FEAT-224 v1
    shape: ``definition`` is ``response.output`` with ``data``/``datasets``
    stripped, and a freshly minted ``f"{mode_str}-{uuid4().hex[:8]}"`` id — the
    exact behaviour the inline ``bots/data.py`` block previously produced.

    Never raises to the caller (mirrors the FEAT-224 block's defensive
    style): any failure is logged at ``warning`` and the function returns
    ``None`` without mutating ``response``.

    Args:
        response: An ``AIMessage``-shaped response (``.output``,
            ``.artifacts`` (list), ``.artifact_id``, ``.a2ui_envelope``).
        output_mode: The response's ``OutputMode`` (or its ``str`` value).
            Non-structured modes are a no-op.

    Returns:
        The minted artifact id (``== surfaceId`` when an envelope was used),
        or ``None`` for a non-structured ``output_mode`` or when
        ``response.output`` is empty/malformed in the no-envelope fallback.
    """
    art_type = _STRUCTURED_ARTIFACT_TYPE.get(output_mode)
    if art_type is None:
        return None

    mode_str = output_mode.value if hasattr(output_mode, "value") else output_mode
    try:
        envelope = getattr(response, "a2ui_envelope", None)
        if envelope is not None:
            surface_id = envelope["createSurface"]["surfaceId"]
            entry: dict[str, Any] = {
                "type": art_type,
                "artifactId": surface_id,
                "surfaceId": surface_id,
                "schemaVersion": SCHEMA_VERSION,
                "definition": root_component(envelope),
            }
            art_id = surface_id
        else:
            content = getattr(response, "output", None)
            if not isinstance(content, dict) or not content:
                return None
            art_id = f"{mode_str}-{uuid.uuid4().hex[:8]}"
            entry = {
                "type": art_type,
                "artifactId": art_id,
                "definition": {key: value for key, value in content.items() if key not in ("data", "datasets")},
            }

        response.artifacts.append(entry)
        response.artifact_id = art_id
        return art_id
    except Exception:
        logger.warning("attach_structured_artifact: failed to mint artifact for mode=%s", mode_str, exc_info=True)
        return None
