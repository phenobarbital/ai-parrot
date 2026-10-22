"""Validated classification, link and run-report contracts."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

RELATIONS = ("references", "relates_to", "mentions", "follows_up", "supersedes")


class InboxClassification(BaseModel):
    """Structured classification response from the model."""

    kind: str
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    event_date: str | None = None


class ResolvedClassification(BaseModel):
    """Taxonomy-validated classification used by writers."""

    kind: str
    category: str
    title: str
    summary: str
    tags: list[str]
    entities: list[str]
    event_date: str | None
    classification_source: Literal["model", "fallback"]


class LinkCandidate(BaseModel):
    """Verified candidate with its retrieval origin."""

    page_id: str
    title: str
    category: str
    summary: str
    origin: Literal["search", "tag_fts", "verbatim"]


class LinkChoice(BaseModel):
    """One relation proposed by the model."""

    page_id: str
    rel: Literal["references", "relates_to", "mentions", "follows_up", "supersedes"]
    why: str


class LinkSelection(BaseModel):
    """Structured model selection from the candidate set."""

    links: list[LinkChoice] = Field(default_factory=list)


class VerifiedLink(BaseModel):
    """A store-verified outgoing relation."""

    page_id: str
    rel: str
    why: str
    title: str


class ArchiveResult(BaseModel):
    """Result of moving an original and optionally staging its deletion."""

    source: Path
    destination: Path
    rejected: bool
    staged_git: bool


class InboxDocResult(BaseModel):
    """Outcome of processing one original."""

    source_uri: str
    status: Literal["admitted", "archived_category", "rejected", "skipped", "failed", "dry_run"]
    decision: str | None = None
    composite: float | None = None
    decision_source: str | None = None
    kind: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[VerifiedLink] = Field(default_factory=list)
    doc_page_id: str | None = None
    markdown_path: str | None = None
    archived_to: str | None = None
    adr_candidate_id: str | None = None
    adr_candidate_reused: bool = False
    fireflies_match: str | None = None
    verified: bool = False
    error: str | None = None


class InboxRunReport(BaseModel):
    """Deterministic command result with per-document outcomes."""

    inbox_dir: str
    charter_version: str
    charter_fingerprint: str
    models: dict[str, str]
    dry_run: bool
    counts: dict[str, int]
    documents: list[InboxDocResult]

    @property
    def failed(self) -> bool:
        """Whether any document failed."""
        return any(document.status == "failed" for document in self.documents)
