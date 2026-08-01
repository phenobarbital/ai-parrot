"""JSONL review manifest layer for supervised wiki ingestion (FEAT-402).

Implements the HITL contract described in the spec (§2 Overview, Module 2):
``wikitoolkit ingest --dry-run`` writes a JSONL manifest, a human edits the
``decision`` field on each row, and ``--review`` applies the edited
decisions. This module owns:

- The triage data models shared by the router (``triage.py``, TASK-2071)
  and the manifest: :class:`DimensionScores`, :class:`Claim`,
  :class:`TriageOutput`.
- The manifest row models: :class:`ManifestRunHeader` (line 1) and
  :class:`ManifestDocEntry` (one per triaged document).
- :class:`ManifestWriter` / :class:`ManifestReader` for the JSONL file
  itself.
- :func:`stratified_sample` — the charter-configurable 60/40
  near-threshold/uniform audit sampler used by ``--auto`` mode.
- :func:`agreement_rate` — human-vs-proposed agreement on decided entries.
- :func:`propose_gray_zone_widening` — a **propose-only** calibration
  helper; v1 never auto-writes charter changes (spec §1 Non-Goals, §7).

Design notes:
- ``TriageOutput`` deliberately has **no composite field** — the LLM only
  scores dimensions; the weighted composite is always computed in Python
  from the charter's weights (``triage.py``, TASK-2071). Do not add one.
- Every manifest line carries an explicit ``kind`` discriminator
  (``"run_header"`` or ``"doc"``) so the reader is order-tolerant.
- All I/O here is synchronous — manifest read/write happens outside the
  async apply pipeline (CLI setup / HITL edit step), matching the pattern
  established in ``charter.py`` (TASK-2069).
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from parrot.knowledge.wiki.charter import CalibrationPolicy, Thresholds

logger = logging.getLogger(__name__)

#: Valid manifest decision / proposed_action values (document-level, v1).
DOC_ACTIONS: frozenset[str] = frozenset({"admit", "archive", "discard"})


class ManifestParseError(ValueError):
    """Raised when a JSONL manifest line cannot be parsed or validated.

    The error message always names the offending 1-based line number so a
    human editing the manifest by hand can find and fix the mistake.
    """


class DimensionScores(BaseModel):
    """Per-dimension triage scores, each in ``[0, 1]``.

    Attributes:
        density: Information density — how much admissible content per
            unit of document.
        novelty: How much the document adds beyond what the wiki already
            covers (grounding-backed; see ``triage.py`` NoveltyScorer).
        durability: Long-term relevance of the content.
    """

    density: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    durability: float = Field(ge=0.0, le=1.0)


class Claim(BaseModel):
    """A single claim extracted from a document during triage.

    Attributes:
        text: The claim text.
        grounded: Whether the claim was found to be grounded against the
            existing GraphIndex plane. ``None`` until novelty scoring
            fills it in (``triage.py``).
    """

    text: str
    grounded: bool | None = None


class TriageOutput(BaseModel):
    """Structured output produced by the triage LLM (``ask_structured``).

    Attributes:
        briefing: 2-3 sentence summary, reused as the ingester ``hint``.
        scores: Per-dimension scores. **No composite field** — the
            weighted composite is always computed in code from the
            charter's weights, never emitted by the LLM.
        claims: Claims extracted from the document (capped per charter
            config; used for novelty scoring and, behind the experimental
            ``--extract`` flag, claim-level admission).
        sensitive: When true, forces discard regardless of composite
            score (spec §5 acceptance criteria).
        category_hint: Optional suggested wiki page category.
    """

    briefing: str
    scores: DimensionScores
    claims: list[Claim] = Field(default_factory=list)
    sensitive: bool = False
    category_hint: str | None = None


class ManifestRunHeader(BaseModel):
    """The first line of a JSONL review manifest: run-level metadata.

    Attributes:
        kind: Discriminator, always ``"run_header"``.
        charter_sha256: sha256 fingerprint of the charter used this run.
        charter_version: Charter version used this run.
        mode: The CLI mode that produced this manifest.
        novelty_backend: Which novelty-scoring backend ran this run —
            ``"grounding"`` when the GraphIndex plane exists, or
            ``"search-proxy"`` as the fallback.
        counts: Summary counts (e.g. proposed action tallies).
        created_at: ISO-8601 timestamp string.
    """

    kind: Literal["run_header"] = "run_header"
    charter_sha256: str
    charter_version: str
    mode: Literal["dry-run", "review", "interactive", "auto"]
    novelty_backend: Literal["grounding", "search-proxy"]
    counts: dict[str, int]
    created_at: str


class ManifestDocEntry(BaseModel):
    """A single document row in a JSONL review manifest.

    Attributes:
        kind: Discriminator, always ``"doc"``.
        source_uri: Identifier of the source document.
        file_hash: Content hash of the source document.
        briefing: The triage briefing (see :class:`TriageOutput`).
        scores: Per-dimension triage scores.
        composite: The weighted composite score, computed in code from
            the charter weights (never emitted by the LLM).
        proposed_action: The router's proposed destination.
        claims: Claims extracted from the document.
        decision: The final decision. ``None`` in a fresh ``--dry-run``
            manifest; filled by a human edit or ``--auto`` thresholding.
        decision_source: Where the decision came from.
        audit_sample: Whether this entry was flagged for audit review by
            :func:`stratified_sample`.
        audit_stratum: Which stratum the entry was sampled from
            (``"near_threshold"`` or ``"uniform"``) when ``audit_sample``
            is true.
    """

    kind: Literal["doc"] = "doc"
    source_uri: str
    file_hash: str
    briefing: str
    scores: DimensionScores
    composite: float = Field(ge=0.0, le=1.0)
    proposed_action: Literal["admit", "archive", "discard"]
    claims: list[Claim] = Field(default_factory=list)
    decision: Literal["admit", "archive", "discard"] | None = None
    decision_source: Literal["heuristic", "model", "human", "auto"] | None = None
    audit_sample: bool = False
    audit_stratum: str | None = None


class ManifestWriter:
    """Writes a JSONL review manifest: one run-header line + one doc line each.

    Attributes:
        path: Target manifest file path.
    """

    def __init__(self, path: Path) -> None:
        """Initialize the writer.

        Args:
            path: Target manifest file path. Parent directories are
                created if needed at write time.
        """
        self.path = Path(path)

    def write(
        self,
        header: ManifestRunHeader,
        entries: list[ManifestDocEntry],
    ) -> Path:
        """Write the run header followed by one line per doc entry.

        Args:
            header: The run-header row (always written first).
            entries: The doc entries to write, in order.

        Returns:
            The path the manifest was written to.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            fh.write(header.model_dump_json())
            fh.write("\n")
            for entry in entries:
                fh.write(entry.model_dump_json())
                fh.write("\n")
        logger.debug(
            "Wrote manifest %s (%d doc entries)", self.path, len(entries)
        )
        return self.path


class ManifestReader:
    """Parses and validates a JSONL review manifest, including human edits.

    Attributes:
        path: Manifest file path to read.
    """

    def __init__(self, path: Path) -> None:
        """Initialize the reader.

        Args:
            path: Manifest file path to read.
        """
        self.path = Path(path)

    def read(self) -> tuple[ManifestRunHeader, list[ManifestDocEntry]]:
        """Read and validate the manifest.

        Returns:
            A ``(header, entries)`` tuple.

        Raises:
            ManifestParseError: If a line is malformed JSON, has an
                unknown ``kind``, fails model validation (e.g. an invalid
                hand-edited ``decision`` value), or the run header is
                missing/duplicated. The error message always names the
                offending 1-based line number.
        """
        header: ManifestRunHeader | None = None
        entries: list[ManifestDocEntry] = []

        with self.path.open("r", encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ManifestParseError(
                        f"line {lineno}: invalid JSON ({exc})"
                    ) from exc

                kind = data.get("kind")
                if kind == "run_header":
                    if header is not None:
                        raise ManifestParseError(
                            f"line {lineno}: duplicate run_header "
                            "(only one is allowed per manifest)"
                        )
                    try:
                        header = ManifestRunHeader.model_validate(data)
                    except ValidationError as exc:
                        raise ManifestParseError(
                            f"line {lineno}: invalid run_header ({exc})"
                        ) from exc
                elif kind == "doc":
                    try:
                        entries.append(ManifestDocEntry.model_validate(data))
                    except ValidationError as exc:
                        raise ManifestParseError(
                            f"line {lineno}: invalid doc entry ({exc})"
                        ) from exc
                else:
                    raise ManifestParseError(
                        f"line {lineno}: unknown kind {kind!r} "
                        "(expected 'run_header' or 'doc')"
                    )

        if header is None:
            raise ManifestParseError(
                f"{self.path}: manifest is missing its run_header line"
            )
        return header, entries


def stratified_sample(
    entries: list[ManifestDocEntry],
    thresholds: Thresholds,
    sample_size: int,
    *,
    near_fraction: float = 0.6,
    uniform_fraction: float = 0.4,
    seed: int | None = None,
) -> None:
    """Flag a stratified audit sample on ``entries``, in place.

    Splits ``sample_size`` total picks between two strata:

    - **near-threshold** (``near_fraction`` of the sample): the entries
      whose composite score is closest to either the ``admit`` or
      ``reject`` boundary — where the router is most likely to be wrong.
    - **uniform** (``uniform_fraction`` of the sample): entries drawn
      uniformly at random from the remainder, to catch "confidently
      wrong" errors far from the thresholds.

    Mutates the selected entries' ``audit_sample`` (set ``True``) and
    ``audit_stratum`` (``"near_threshold"`` or ``"uniform"``) fields in
    place. Does not return anything.

    Args:
        entries: The manifest doc entries to sample from.
        thresholds: The charter thresholds, used to compute distance to
            the nearest admit/reject boundary for the near-threshold
            stratum.
        sample_size: Total number of entries to flag for audit. Clamped
            to ``len(entries)``.
        near_fraction: Fraction of ``sample_size`` drawn from the
            near-threshold stratum (charter-configurable; default 0.6).
        uniform_fraction: Fraction of ``sample_size`` drawn from the
            uniform stratum (charter-configurable; default 0.4).
        seed: Optional seed for the uniform draw, for deterministic
            tests/reruns.
    """
    if not entries or sample_size <= 0:
        return

    sample_size = min(sample_size, len(entries))
    near_count = round(sample_size * near_fraction)
    uniform_count = sample_size - near_count

    def _distance_to_threshold(entry: ManifestDocEntry) -> float:
        return min(
            abs(entry.composite - thresholds.admit),
            abs(entry.composite - thresholds.reject),
        )

    ranked = sorted(entries, key=_distance_to_threshold)
    near_stratum = ranked[:near_count]
    near_ids = {id(entry) for entry in near_stratum}

    remaining = [entry for entry in entries if id(entry) not in near_ids]
    rng = random.Random(seed)
    uniform_stratum = rng.sample(remaining, k=min(uniform_count, len(remaining)))

    for entry in near_stratum:
        entry.audit_sample = True
        entry.audit_stratum = "near_threshold"
    for entry in uniform_stratum:
        entry.audit_sample = True
        entry.audit_stratum = "uniform"


def agreement_rate(entries: list[ManifestDocEntry]) -> float | None:
    """Compute the human/router agreement rate on decided entries.

    Args:
        entries: The manifest doc entries to evaluate.

    Returns:
        The fraction of entries with a non-null ``decision`` where
        ``decision == proposed_action``, rounded to 4 decimals. ``None``
        when no entry has been decided yet.
    """
    decided = [entry for entry in entries if entry.decision is not None]
    if not decided:
        return None
    agreed = sum(1 for entry in decided if entry.decision == entry.proposed_action)
    return round(agreed / len(decided), 4)


def propose_gray_zone_widening(
    thresholds: Thresholds,
    calibration: CalibrationPolicy,
    observed_agreement: float | None,
) -> Thresholds | None:
    """Propose widened gray-zone thresholds when agreement is low.

    **Propose-only** (spec §1 Non-Goals, §7): this never mutates
    ``thresholds`` or writes to the charter. It only returns a new
    :class:`Thresholds` instance for a human to review and apply as a
    versioned charter edit.

    Args:
        thresholds: The current charter thresholds (read-only).
        calibration: The charter's calibration policy.
        observed_agreement: The agreement rate observed on the audited
            sample (see :func:`agreement_rate`), or ``None`` if nothing
            has been audited yet.

    Returns:
        A new :class:`Thresholds` instance with the gray zone widened by
        ``calibration.gray_zone_step`` on each side, or ``None`` when no
        widening is warranted (calibration disabled, agreement unknown,
        agreement already meets the bar, or the policy's low-agreement
        action isn't ``"widen_gray_zone"``).
    """
    if calibration.autotune == "off":
        return None
    if observed_agreement is None:
        return None
    if observed_agreement >= calibration.min_agreement:
        return None
    if calibration.on_low_agreement != "widen_gray_zone":
        return None

    new_admit = min(1.0, thresholds.admit + calibration.gray_zone_step)
    new_reject = max(0.0, thresholds.reject - calibration.gray_zone_step)
    return Thresholds(admit=new_admit, reject=new_reject)
