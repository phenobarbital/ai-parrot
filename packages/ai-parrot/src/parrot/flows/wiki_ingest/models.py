"""§10 frontmatter schemas + node contracts (FEAT-481, spec Module 5).

One Pydantic model per operating-contract §10 page type, plus the
structured-LLM node contracts (:class:`Classification`, spec §15;
:class:`MeetingExtraction`, spec §15.2) and the §34 validation result
(:class:`ValidationResult`). Field names and enum values mirror the
contract's YAML frontmatter blocks (``sdd/references/
obsidian-wiki-operating-contract.md`` §10) verbatim.

This is the **shared contract** every other node in this subsystem
depends on (frozen first — spec Module 5 / Worktree Strategy).

Key invariants enforced here (spec §8 Open Questions):

- **D1** — ``raw_summary``/``raw_transcript`` are plain relative paths,
  never Obsidian ``[[wikilinks]]`` (raw files are not Obsidian pages).
- **D2** — ``primary_project`` must also appear in ``projects``.
- **D4** — ``source_id`` is the Fireflies-prefixed authoritative identity
  (``"fireflies:<id>"``), aligned with FEAT-472's ``external_id``.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

#: §8.2 — punctuation that must never appear in an Obsidian-safe filename.
UNSAFE_FILENAME_CHARS = frozenset('/\\:*?"<>|')

#: rule #12 — the only acceptable stand-ins for insufficient evidence.
ALLOWED_PLACEHOLDER_VALUES = frozenset({"Unknown", "Not established", "Requires review"})

_WIKILINK_RE = re.compile(r"\[\[.*?\]\]")


def _reject_wikilink(value: str, *, field_name: str) -> str:
    """D1 — raw provenance fields must be plain relative paths.

    Args:
        value: The candidate path.
        field_name: Field name, used in the raised error message.

    Returns:
        ``value`` unchanged, when valid.

    Raises:
        ValueError: If ``value`` contains an Obsidian ``[[wikilink]]``.
    """
    if _WIKILINK_RE.search(value):
        raise ValueError(
            f"{field_name} must be a plain relative path (D1) — raw files "
            f"are not Obsidian pages and must never be wikilinked, got {value!r}"
        )
    return value


class MeetingSourceFrontmatter(BaseModel):
    """§10.1 — canonical meeting source page frontmatter."""

    id: str
    type: Literal["meeting-source"] = "meeting-source"
    title: str
    aliases: list[str] = Field(default_factory=list)
    status: Literal["processed"] = "processed"
    source_id: str
    meeting_date: str
    processed_at: str
    processing_mode: Literal["summary-only", "summary-and-transcript"]
    classification_confidence: Literal["high", "medium", "low"]
    review_required: bool = False
    raw_summary: str
    raw_transcript: str
    summary_sha256: str
    transcript_sha256: str
    primary_project: str
    projects: list[str] = Field(default_factory=list)
    clients: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=lambda: ["meeting"])
    created: str
    updated: str

    @field_validator("source_id")
    @classmethod
    def _source_id_is_fireflies_prefixed(cls, value: str) -> str:
        """D4 — ``source_id`` must be ``"fireflies:<id>"``."""
        if not value.startswith("fireflies:") or value == "fireflies:":
            raise ValueError(f'source_id must be "fireflies:<id>" (D4), got {value!r}')
        return value

    @field_validator("raw_summary")
    @classmethod
    def _raw_summary_plain_path(cls, value: str) -> str:
        return _reject_wikilink(value, field_name="raw_summary")

    @field_validator("raw_transcript")
    @classmethod
    def _raw_transcript_plain_path(cls, value: str) -> str:
        return _reject_wikilink(value, field_name="raw_transcript")

    @model_validator(mode="after")
    def _primary_project_in_projects(self) -> MeetingSourceFrontmatter:
        """D2 — ``primary_project`` must also appear in ``projects``."""
        if self.primary_project not in self.projects:
            raise ValueError(
                f"primary_project {self.primary_project!r} must also be listed "
                f"in projects (D2), got projects={self.projects!r}"
            )
        return self


class ProjectFrontmatter(BaseModel):
    """§10.2 — project page frontmatter."""

    id: str
    type: Literal["project"] = "project"
    title: str
    aliases: list[str] = Field(default_factory=list)
    status: Literal["proposed", "active", "on-hold", "completed", "cancelled", "unknown"] = "unknown"
    clients: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)
    open_contradictions: list[str] = Field(default_factory=list)
    last_meeting: str | None = None
    created: str
    updated: str


class EntityFrontmatter(BaseModel):
    """§10.3 — entity (person/company/product) page frontmatter."""

    id: str
    type: Literal["person", "company", "product"]
    title: str
    aliases: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created: str
    updated: str

    @model_validator(mode="after")
    def _id_prefix_matches_type(self) -> EntityFrontmatter:
        """``id`` prefix (``person:``/``company:``/``product:``) must match ``type``."""
        expected_prefix = f"{self.type}:"
        if not self.id.startswith(expected_prefix):
            raise ValueError(f"id must start with {expected_prefix!r} for type={self.type!r}, got {self.id!r}")
        return self


class ConceptFrontmatter(BaseModel):
    """§10.4 — concept page frontmatter."""

    id: str
    type: Literal["concept"] = "concept"
    title: str
    aliases: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created: str
    updated: str


class ContradictionFrontmatter(BaseModel):
    """§10.5 — contradiction page frontmatter."""

    id: str
    type: Literal["contradiction"] = "contradiction"
    title: str
    status: Literal["open", "resolved", "superseded"] = "open"
    severity: Literal["low", "medium", "high", "critical"]
    projects: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)
    affected_pages: list[str] = Field(default_factory=list)
    created: str
    updated: str
    resolved_at: str | None = None


class DailyNoteFrontmatter(BaseModel):
    """§10.6 — daily note frontmatter."""

    id: str
    type: Literal["daily-note"] = "daily-note"
    title: str
    date: str
    meetings: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    created: str
    updated: str


class SynthesisFrontmatter(BaseModel):
    """§10.7 — synthesis page frontmatter."""

    id: str
    type: Literal["synthesis"] = "synthesis"
    title: str
    question: str
    projects: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)
    created: str
    updated: str


# ---------------------------------------------------------------------------
# Structured-LLM node contracts (spec §2 Data Models)
# ---------------------------------------------------------------------------


class Classification(BaseModel):
    """§15 — ``invoke(output_type=Classification)`` result."""

    primary_client: str | None = None
    primary_project: str | None = None
    additional_projects: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    transcript_fallback_reason: str | None = None


class ActionItem(BaseModel):
    """One row of the §17 ``## Action Items`` table."""

    action: str
    owner: str = "Unknown"
    due_date: str = "Unknown"
    status: str = "Open"
    source_confidence: Literal["High", "Medium", "Low"] = "Medium"


class MeetingExtraction(BaseModel):
    """§15.2 — ``invoke(output_type=MeetingExtraction)`` result."""

    decisions: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    potential_contradictions: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """§34 — the executable Post-Operation Validation checklist's result.

    Attributes:
        passed: ``True`` only when ``failures`` is empty.
        failures: Hard §34 violations — a failing operation must be
            rolled back (compiled changes only), a review item queued,
            and no success registry/log entry written.
        warnings: Non-blocking observations worth surfacing in the §35
            change summary.
    """

    passed: bool
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
