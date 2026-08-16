"""Policy and report models for deterministic groundedness scoring.

Defines the per-agent ``GroundednessPolicy``, the per-atom
``AtomVerdict``, and the aggregate ``GroundednessReport`` (FEAT-398,
spec §2 Data Models).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import Atom, AtomKind


class GroundednessPolicy(BaseModel):
    """Per-agent groundedness scoring policy.

    Scoring-only — there is no enforce mode; every knob here tunes
    *classification*, never mutation/blocking of the response.

    Attributes:
        enabled_kinds: Atom kinds to extract. Default: all five.
        include_user_prompt_as_evidence: Treat the user's question as
            legitimate evidence (agent echoing a user-stated figure).
        contradicted_band: Upper relative delta for "contradicted"
            (same-magnitude) classification.
        min_alert_score: Below this, telemetry marks the turn flagged.
            Score is always emitted regardless.
        max_evidence_bytes: Evidence-index input cap.
        min_number_digits: Bare integers shorter than this are skipped
            (noise floor).
    """

    enabled_kinds: list[AtomKind] = Field(default_factory=lambda: list(AtomKind))
    include_user_prompt_as_evidence: bool = True
    contradicted_band: float = 0.15
    min_alert_score: float = 0.8
    max_evidence_bytes: int = 262_144
    min_number_digits: int = 4


class AtomVerdict(BaseModel):
    """A per-atom groundedness verdict.

    Attributes:
        atom: The answer atom being verified.
        verdict: ``supported`` / ``contradicted`` / ``unsupported``.
        nearest_evidence: The closest evidence candidate's raw text
            (``contradicted`` only) — diagnostic aid.
    """

    atom: Atom
    verdict: Literal["supported", "contradicted", "unsupported"]
    nearest_evidence: str | None = None


class GroundednessReport(BaseModel):
    """Aggregate groundedness report for one turn's final answer.

    Attributes:
        score: ``supported / total_atoms``; ``1.0`` when there are no
            atoms to check (``no_factual_content``) or no evidence
            (``no_evidence``).
        total_atoms: Total answer atoms scored.
        supported: Atoms matched (exactly or within precision tolerance).
        contradicted: Same-magnitude atoms outside stated precision but
            within ``contradicted_band``.
        unsupported: Atoms with no trace in evidence.
        no_factual_content: True when the answer had no verifiable atoms.
        no_evidence: True when the turn had no tool-call results.
        evidence_truncated: True when ``max_evidence_bytes`` was hit
            while building the evidence index.
        duration_ms: Wall-clock scoring time. Excluded from
            ``model_dump``/``model_dump_json`` by default so identical
            (answer, evidence) inputs produce byte-identical serialized
            reports (spec §5 determinism criterion) regardless of timing
            jitter; still directly readable via ``report.duration_ms``.
    """

    score: float
    total_atoms: int
    supported: list[AtomVerdict] = Field(default_factory=list)
    contradicted: list[AtomVerdict] = Field(default_factory=list)
    unsupported: list[AtomVerdict] = Field(default_factory=list)
    no_factual_content: bool = False
    no_evidence: bool = False
    evidence_truncated: bool = False
    duration_ms: float = Field(default=0.0, exclude=True)
