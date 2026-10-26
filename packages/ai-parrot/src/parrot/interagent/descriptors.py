"""Media types and bounded descriptors shown to an LLM instead of payload bytes."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SUMMARY_CHARS = 1500


class MediaType(str, Enum):
    """Registered artifact media types."""

    ARROW = "arrow"
    PARQUET = "parquet"
    MERMAID = "mermaid"
    STRUCTURIZR = "structurizr"
    SVG = "svg"
    PNG = "png"
    PDF = "pdf"
    GENERIC = "generic"


class HandleDescriptor(BaseModel):
    """Bounded artifact metadata suitable for inclusion in an LLM context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    media_type: MediaType
    byte_size: int = Field(ge=0)
    summary: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bound_summary(self) -> "HandleDescriptor":
        """Reject summaries whose JSON representation exceeds the descriptor cap.

        Returns:
            The validated descriptor.

        Raises:
            ValueError: If the serialized summary exceeds 1,500 characters.
        """
        serialized = json.dumps(self.summary, sort_keys=True)
        if len(serialized) > MAX_SUMMARY_CHARS:
            raise ValueError(f"summary JSON exceeds {MAX_SUMMARY_CHARS} characters")
        return self
