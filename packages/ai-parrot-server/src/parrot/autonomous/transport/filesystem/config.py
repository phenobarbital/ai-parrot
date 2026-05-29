"""Configuration model for FilesystemTransport."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class FilesystemTransportConfig(BaseModel):
    """Pydantic v2 configuration for the FilesystemTransport.

    All transport settings with sensible defaults. The ``root_dir`` is
    automatically resolved to an absolute path via a field validator.
    """

    root_dir: Path = Field(
        default=Path(".parrot"),
        description="Root directory for transport data (registry, inbox, feed, channels, reservations).",
    )
    presence_interval: float = Field(
        default=10.0,
        description="Heartbeat interval in seconds.",
    )
    stale_threshold: float = Field(
        default=60.0,
        description="Seconds before an agent is considered dead.",
    )
    scope_to_cwd: bool = Field(
        default=False,
        description="Only see agents with the same working directory.",
    )
    poll_interval: float = Field(
        default=0.5,
        description="Polling fallback interval in seconds.",
    )
    use_inotify: bool = Field(
        default=True,
        description="Use watchdog/inotify if available for sub-50ms latency.",
    )
    message_ttl: float = Field(
        default=3600.0,
        description="Message time-to-live in seconds (0 = no expiration).",
    )
    keep_processed: bool = Field(
        default=True,
        description="Move processed messages to .processed/ instead of deleting.",
    )
    feed_retention: int = Field(
        default=500,
        description="Maximum events in the activity feed before rotation.",
    )
    default_channels: List[str] = Field(
        default_factory=lambda: ["general"],
        description="Channels created automatically on transport start.",
    )
    reservation_timeout: float = Field(
        default=300.0,
        description="Reservation expiry in seconds.",
    )
    routes: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Optional routing rules for message dispatch.",
    )

    @model_validator(mode="after")
    def resolve_root_dir(self) -> "FilesystemTransportConfig":
        """Resolve root_dir to an absolute path."""
        object.__setattr__(self, "root_dir", Path(self.root_dir).resolve())
        return self
