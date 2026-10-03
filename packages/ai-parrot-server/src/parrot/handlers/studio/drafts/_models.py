"""Request models of the draft pipeline."""

from __future__ import annotations


from pydantic import BaseModel, model_validator

from ..storage.models import (
    StudioAgentBundle,
)


DRAFTS_SUBDIR = "_drafts"

class SaveDraftRequest(BaseModel):
    """``POST /astudio/drafts`` payload."""

    name: str
    source: str | None = None
    bundle: StudioAgentBundle | None = None
    visibility: str = "private"
    allowed_groups: list[str] = []
    expected_version: int | None = None

    @model_validator(mode="after")
    def _exactly_one_body(self) -> "SaveDraftRequest":
        """A draft is either Python ``source`` or a declarative ``bundle`` — never both, never neither."""
        if (self.source is None) == (self.bundle is None):
            raise ValueError("exactly one of 'source' and 'bundle' is required")
        return self


class ActivateDraftRequest(BaseModel):
    """``POST /astudio/drafts/{name}/activate`` payload."""

    replace: bool = False
    expected_version: int | None = None
    target_expected_version: int | None = None
