"""Expert contribution models and JSON I/O (FEAT-890 M8)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """One expert finding about a document."""

    id: str
    severity: Literal["info", "minor", "major", "critical"]
    section: str
    statement: str
    evidence: list[str] = Field(default_factory=list)
    status: Literal["pending", "confirm", "reject", "escalate"] = "pending"
    reason: str = ""


class Contribution(BaseModel):
    """The findings one expert produced for one document."""

    expert: str
    tier: str
    doc_path: str
    doc_digest: str
    feature_id: str | None = None
    created_at: str
    knowledge_degraded: bool = False
    stale: bool = False
    findings: list[Finding] = Field(default_factory=list)


def contribution_dir(repo_root: Path, *, feature_id: str | None, doc_slug: str) -> Path:
    """Return the directory holding contributions for a feature or, lacking one, a document.

    Args:
        repo_root: Repository root.
        feature_id: Feature id (``FEAT-NNN``) or ``None``.
        doc_slug: Slug of the document, used when there is no feature id.

    Returns:
        ``sdd/state/<FEAT>/contributions`` or ``sdd/state/.contributions/<doc-slug>``.
    """
    state = Path(repo_root) / "sdd" / "state"
    if feature_id:
        return state / feature_id / "contributions"
    return state / ".contributions" / doc_slug


def load_contribution(path: Path) -> Contribution:
    """Load a contribution from a JSON file."""
    return Contribution.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_contribution(path: Path, c: Contribution) -> None:
    """Write a contribution as JSON, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(c.model_dump_json(indent=2) + "\n", encoding="utf-8")
