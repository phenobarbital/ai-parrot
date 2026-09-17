"""Generated clip record shared by the Veo and Omni adapters (FEAT-564, spec module M2)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GeneratedReelClip(BaseModel):
    """One backend-generated video clip for a reel scene, before assembly.

    Args:
        local_path: Local filesystem path to the downloaded/decoded clip.
        model: The exact model id that generated this clip.
        backend: Which adapter produced this clip.
        submitted_duration_seconds: The covering duration actually submitted
            to the provider, or ``None`` for a backend with no user-selectable
            duration (Omni: provider default).
        measured_duration_seconds: Duration measured from the generated media
            itself (never trusted from the request alone).
        has_audio: Whether the clip file itself carries an audio track.
        provider_operation_id: The provider's long-running operation id, kept
            for reconciliation after an ambiguous timeout.
    """

    local_path: Path = Field(..., description="Local filesystem path to the downloaded/decoded clip.")
    model: str = Field(..., description="Exact model id that generated this clip.")
    backend: Literal["veo", "omni"] = Field(..., description="Adapter that produced this clip.")
    submitted_duration_seconds: Optional[float] = Field(
        None, description="Covering duration submitted to the provider; None for provider-default backends."
    )
    measured_duration_seconds: float = Field(..., description="Duration measured from the generated media itself.")
    has_audio: bool = Field(..., description="Whether the clip file itself carries an audio track.")
    provider_operation_id: Optional[str] = Field(
        None, description="Provider long-running operation id, kept for reconciliation after an ambiguous timeout."
    )
