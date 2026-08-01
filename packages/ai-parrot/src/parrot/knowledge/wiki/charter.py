"""Editorial charter models, YAML loader, and fingerprinting (FEAT-402).

The editorial **charter** is the versioned policy artifact that drives
every supervised-ingestion triage decision: scope include/exclude rules,
scoring-dimension weights, admit/reject thresholds, routing destinations,
calibration policy, and the few-shot examples loop that anchors the
triage LLM against past human decisions.

Design notes:
- All models follow the same Pydantic v2 pattern used throughout the wiki
  package (see ``parrot.knowledge.wiki.models.WikiConfig``).
- The composite score is **always** computed in application code from the
  charter's dimension weights — the charter only stores the weights and
  thresholds; the LLM never sees or emits a composite (spec Data Models,
  Non-Goals).
- ``Charter.fingerprint`` is a sha256 hash of the *raw bytes* of the YAML
  file as read from disk, computed once at ``load_charter`` time. It is
  NOT a field in the YAML document itself — any edit to the file (even
  whitespace) changes the fingerprint and therefore versions every
  decision made against it.
- ``examples_file`` (when set) is an appendable JSONL file of
  :class:`TriageExample` rows — human decisions accumulate here via
  :func:`append_example` without needing to rewrite the whole charter
  YAML document.
- This module performs only synchronous, in-memory work (YAML parse +
  Pydantic validation) and synchronous file I/O. It is invoked from CLI
  setup, before the async ingestion pipeline starts — no async wrapper is
  needed here.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

#: Names of the scoring dimensions every charter must weight.
DIMENSION_NAMES: frozenset[str] = frozenset({"density", "novelty", "durability"})

#: Valid routing destinations for a triaged document.
DESTINATIONS: frozenset[str] = frozenset({"wiki", "archive", "discard"})


class CharterScopeRule(BaseModel):
    """A single scope rule (an include or exclude reason).

    Attributes:
        id: Short, stable identifier for the rule (e.g. ``"decisions"``).
        description: Prose description used as LLM triage context.
    """

    id: str
    description: str


class CharterScope(BaseModel):
    """Editorial scope: what belongs in the wiki and what does not.

    Attributes:
        include: Rules describing admissible content categories.
        exclude: Rules describing content that should never be admitted.
    """

    include: list[CharterScopeRule] = Field(default_factory=list)
    exclude: list[CharterScopeRule] = Field(default_factory=list)


class Thresholds(BaseModel):
    """Composite-score admission thresholds.

    Attributes:
        admit: Composite scores at or above this value are admitted.
        reject: Composite scores below this value are rejected.

    The half-open interval ``[reject, admit)`` is the gray zone that
    requires heavy-tier escalation and/or human review.
    """

    admit: float = Field(ge=0.0, le=1.0)
    reject: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_order(self) -> Thresholds:
        """Ensure a non-empty gray zone exists between reject and admit.

        Returns:
            The validated instance.

        Raises:
            ValueError: If ``reject >= admit``.
        """
        if self.reject >= self.admit:
            raise ValueError(
                f"thresholds.reject ({self.reject}) must be < "
                f"thresholds.admit ({self.admit}); otherwise there is no "
                "gray zone"
            )
        return self

    def route(self, composite: float) -> Literal["admit", "gray", "reject"]:
        """Route a composite score to an admission band.

        Args:
            composite: The weighted composite score in ``[0, 1]``.

        Returns:
            ``"admit"`` if ``composite >= admit``, ``"reject"`` if
            ``composite < reject``, otherwise ``"gray"``.
        """
        if composite >= self.admit:
            return "admit"
        if composite < self.reject:
            return "reject"
        return "gray"


class CalibrationPolicy(BaseModel):
    """Stratified audit sampling and gray-zone calibration policy.

    Attributes:
        near_fraction: Fraction of the audit sample drawn from documents
            near the admit/reject thresholds (default 0.6).
        uniform_fraction: Fraction of the audit sample drawn uniformly at
            random across all triaged documents (default 0.4).
        min_agreement: Minimum acceptable human/router agreement rate on
            the audited sample.
        on_low_agreement: Action to propose when agreement drops below
            ``min_agreement``.
        gray_zone_step: How much to widen the gray zone (per threshold)
            when agreement is low.
        autotune: Calibration write mode. v1 supports only ``"off"`` and
            ``"propose"`` — charter amendments are never auto-applied.
    """

    near_fraction: float = Field(default=0.6, ge=0.0, le=1.0)
    uniform_fraction: float = Field(default=0.4, ge=0.0, le=1.0)
    min_agreement: float = Field(default=0.9, ge=0.0, le=1.0)
    on_low_agreement: Literal["widen_gray_zone", "halt", "warn"] = "widen_gray_zone"
    gray_zone_step: float = Field(default=0.05, ge=0.0, le=1.0)
    autotune: Literal["off", "propose"] = Field(
        default="propose",
        description=(
            "Calibration is propose-only in v1: 'off' disables calibration "
            "suggestions entirely, 'propose' surfaces amendment proposals "
            "for a human to accept. There is no 'apply' mode — the charter "
            "is never auto-written."
        ),
    )

    @model_validator(mode="after")
    def _validate_fractions(self) -> CalibrationPolicy:
        """Ensure the stratified sample fractions sum to ~1.0.

        Returns:
            The validated instance.

        Raises:
            ValueError: If ``near_fraction + uniform_fraction`` deviates
                from 1.0 by more than 0.01.
        """
        total = self.near_fraction + self.uniform_fraction
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                "calibration.near_fraction + calibration.uniform_fraction "
                f"must sum to ~1.0 (got {total:.4f})"
            )
        return self


class TriageExample(BaseModel):
    """A single few-shot example anchoring the triage LLM.

    Attributes:
        summary: Short summary of the example document.
        why: Rationale for the destination assigned to the example.
        destination: The routing destination this example illustrates.
    """

    summary: str
    why: str
    destination: Literal["wiki", "archive", "discard"] | None = None


class Amendment(BaseModel):
    """A single entry in the charter's editorial amendment history.

    Attributes:
        version: The charter version this amendment introduced.
        date: The date the amendment was made.
        change: Prose description of what changed.
        source: Who/what proposed the change (e.g. ``"manual"`` or an
            autotune-calibration proposal reference).
    """

    version: str
    date: date
    change: str
    source: str


class Charter(BaseModel):
    """The editorial charter: the versioned policy artifact for triage.

    Attributes:
        version: Charter version identifier (bumped on every amendment).
        scope: Include/exclude scope rules.
        weights: Scoring-dimension weights; keys must be exactly
            ``{"density", "novelty", "durability"}``, each in ``[0, 1]``,
            summing to ~1.0.
        thresholds: Admit/reject composite-score thresholds.
        destinations: Valid routing destinations. Defaults to
            ``["wiki", "archive", "discard"]``.
        calibration: Audit-sampling and gray-zone calibration policy.
        examples: Inline few-shot examples embedded in the charter YAML.
        examples_file: Optional path to an appendable JSONL file of
            additional :class:`TriageExample` rows (see
            :func:`append_example`).
        amendments: Editorial amendment history.
        fingerprint: sha256 hex digest of the raw charter file bytes.
            Populated by :func:`load_charter`; NOT part of the YAML
            document and not validated as an input field.
    """

    version: str
    scope: CharterScope
    weights: dict[str, float]
    thresholds: Thresholds
    destinations: list[str] = Field(
        default_factory=lambda: ["wiki", "archive", "discard"]
    )
    calibration: CalibrationPolicy
    examples: list[TriageExample] = Field(default_factory=list)
    examples_file: Path | None = None
    amendments: list[Amendment] = Field(default_factory=list)
    fingerprint: str = Field(
        default="",
        description=(
            "sha256 of the raw charter YAML bytes, set by load_charter() "
            "after validation. Empty until then."
        ),
    )

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, v: dict[str, float]) -> dict[str, float]:
        """Ensure weights cover exactly the known dimensions and sum to 1.

        Mirrors ``WikiConfig.validate_search_weights``
        (``parrot/knowledge/wiki/models.py``).

        Args:
            v: The raw weights mapping.

        Returns:
            The validated mapping unchanged.

        Raises:
            ValueError: If keys don't match ``DIMENSION_NAMES``, any
                weight is outside ``[0, 1]``, or the sum deviates from
                1.0 by more than 0.01.
        """
        extra = set(v) - DIMENSION_NAMES
        missing = DIMENSION_NAMES - set(v)
        if extra:
            raise ValueError(f"weights contains unknown dimensions: {sorted(extra)}")
        if missing:
            raise ValueError(f"weights is missing dimensions: {sorted(missing)}")
        for key, weight in v.items():
            if not (0.0 <= weight <= 1.0):
                raise ValueError(f"weights['{key}'] = {weight} is outside [0, 1]")
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"weights must sum to ~1.0 (got {total:.4f})")
        return v

    @field_validator("destinations")
    @classmethod
    def validate_destinations(cls, v: list[str]) -> list[str]:
        """Ensure every listed destination is a known routing target.

        Args:
            v: The raw destinations list.

        Returns:
            The validated list unchanged.

        Raises:
            ValueError: If any entry is not in ``DESTINATIONS``.
        """
        unknown = set(v) - DESTINATIONS
        if unknown:
            raise ValueError(f"destinations contains unknown values: {sorted(unknown)}")
        return v


def load_charter(path: Path) -> Charter:
    """Load, validate, and fingerprint an editorial charter YAML file.

    Args:
        path: Path to the charter YAML file.

    Returns:
        A validated :class:`Charter` instance with ``.fingerprint``
        populated as the sha256 hex digest of the raw file bytes.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        pydantic.ValidationError: If the charter document fails model
            validation (bad weights, bad threshold ordering, etc).
    """
    path = Path(path)
    raw_bytes = path.read_bytes()
    fingerprint = hashlib.sha256(raw_bytes).hexdigest()
    data = yaml.safe_load(raw_bytes) or {}
    charter = Charter.model_validate(data)
    charter.fingerprint = fingerprint
    logger.debug(
        "Loaded charter version=%s fingerprint=%s from %s",
        charter.version,
        fingerprint,
        path,
    )
    return charter


def append_example(
    charter: Charter,
    example: TriageExample,
    path: Path | None = None,
) -> Path:
    """Append a human triage decision to the charter's examples file.

    The examples file is a JSONL file (one :class:`TriageExample` per
    line) so human decisions can be appended without rewriting the whole
    charter YAML document. This feeds the few-shot loop described in the
    spec (Module 1).

    Args:
        charter: The charter the example belongs to. Used to resolve the
            default target file (``charter.examples_file``) when ``path``
            is not given.
        example: The example to append.
        path: Optional explicit target file, overriding
            ``charter.examples_file``.

    Returns:
        The path the example was appended to.

    Raises:
        ValueError: If neither ``path`` nor ``charter.examples_file`` is
            set.
    """
    target = Path(path) if path is not None else charter.examples_file
    if target is None:
        raise ValueError(
            "charter.examples_file is not set and no explicit path was given"
        )
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(example.model_dump_json())
        fh.write("\n")
    logger.debug("Appended triage example to %s", target)
    return target
