"""Deterministic groundedness scorer.

Classifies each answer atom against the turn's :class:`EvidenceIndex`
(FEAT-398, spec §3 Module 2): exact normalized match -> ``supported``;
numeric match within a precision-aware tolerance (half a unit of the
answer's last stated significant digit) -> ``supported``; same-magnitude
numeric outside that tolerance but within ``contradicted_band`` ->
``contradicted``; otherwise -> ``unsupported``.

Pure, synchronous, deterministic — no LLM, no network call.
"""
from __future__ import annotations

import math
import time

from .evidence import EvidenceIndex
from .extractors import extract_atoms
from .models import Atom, AtomKind
from .normalize import count_significant_digits
from .policy import AtomVerdict, GroundednessPolicy, GroundednessReport

#: Atom kinds compared via numeric matching (exact -> tolerance -> band).
_NUMERIC_KINDS = frozenset({AtomKind.MONEY, AtomKind.PERCENT, AtomKind.NUMBER})


def _numeric_tolerance(value: float, sig_digits: int) -> float:
    """Half a unit of the last stated significant digit of *value*.

    Precision-aware tolerance (spec §2, normative rule): a fully written
    number (many significant digits) demands near-exact equality; a
    rounded/abbreviated number (few significant digits, e.g. ``$1.24M``)
    tolerates being off by up to half the place value of its last stated
    digit. A fixed global percentage is deliberately not used — it was
    tested and rejected for swallowing digit transpositions.

    Args:
        value: The normalized numeric value.
        sig_digits: Significant digit count, from
            :func:`~parrot.security.groundedness.normalize.count_significant_digits`.

    Returns:
        The absolute tolerance to apply around *value*.
    """
    if value == 0 or sig_digits <= 0:
        return 0.5
    magnitude = math.floor(math.log10(abs(value)))
    place_value = 10.0 ** (magnitude - sig_digits + 1)
    return 0.5 * place_value


class GroundednessScorer:
    """Scores an answer's hard-data atoms against a turn's evidence.

    Example:
        >>> scorer = GroundednessScorer(GroundednessPolicy())
        >>> report = scorer.score(answer_text, evidence_index)
        >>> report.score
        1.0
    """

    def __init__(self, policy: GroundednessPolicy | None = None) -> None:
        """Initialise the scorer.

        Args:
            policy: The scoring policy. Defaults to ``GroundednessPolicy()``.
        """
        self.policy = policy if policy is not None else GroundednessPolicy()

    def score(self, answer_text: str, evidence: EvidenceIndex) -> GroundednessReport:
        """Score *answer_text* against *evidence*.

        Args:
            answer_text: The agent's final answer text for this turn.
            evidence: The turn's :class:`EvidenceIndex`, built from
                ``ToolCall.result`` payloads.

        Returns:
            The assembled :class:`GroundednessReport`.
        """
        start = time.perf_counter()

        if evidence.tool_call_count == 0:
            return GroundednessReport(
                score=1.0,
                total_atoms=0,
                no_evidence=True,
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        answer_atoms = [
            atom for atom in extract_atoms(
                answer_text, min_number_digits=self.policy.min_number_digits,
            )
            if atom.kind in self.policy.enabled_kinds
        ]

        if not answer_atoms:
            return GroundednessReport(
                score=1.0,
                total_atoms=0,
                no_factual_content=True,
                evidence_truncated=evidence.evidence_truncated,
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        supported: list[AtomVerdict] = []
        contradicted: list[AtomVerdict] = []
        unsupported: list[AtomVerdict] = []

        for atom in answer_atoms:
            verdict, nearest = self._classify(atom, evidence)
            entry = AtomVerdict(atom=atom, verdict=verdict, nearest_evidence=nearest)
            if verdict == "supported":
                supported.append(entry)
            elif verdict == "contradicted":
                contradicted.append(entry)
            else:
                unsupported.append(entry)

        total = len(answer_atoms)
        score = len(supported) / total

        return GroundednessReport(
            score=score,
            total_atoms=total,
            supported=supported,
            contradicted=contradicted,
            unsupported=unsupported,
            evidence_truncated=evidence.evidence_truncated,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    def _classify(
        self, atom: Atom, evidence: EvidenceIndex,
    ) -> tuple[str, str | None]:
        """Classify a single answer atom against *evidence*.

        Returns:
            A ``(verdict, nearest_evidence)`` tuple.
        """
        if atom.kind not in _NUMERIC_KINDS:
            if atom.normalized in evidence.by_kind.get(atom.kind, set()):
                return "supported", None
            return "unsupported", None

        return self._classify_numeric(atom, evidence)

    def _classify_numeric(
        self, atom: Atom, evidence: EvidenceIndex,
    ) -> tuple[str, str | None]:
        """Classify a numeric (money/percent/number) atom against evidence."""
        if not evidence.numeric_values:
            return "unsupported", None

        value = float(atom.normalized)
        best_value: float | None = None
        best_raw: str | None = None
        best_diff: float | None = None
        for ev_value, ev_raw in evidence.numeric_values:
            diff = abs(value - ev_value)
            if best_diff is None or diff < best_diff:
                best_value, best_raw, best_diff = ev_value, ev_raw, diff

        if best_diff == 0:
            return "supported", None

        sig_digits = count_significant_digits(atom.raw)
        tolerance = _numeric_tolerance(value, sig_digits)
        if best_diff <= tolerance:
            return "supported", None

        if not best_value:
            return "unsupported", None

        relative_delta = best_diff / abs(best_value)
        if relative_delta <= self.policy.contradicted_band:
            return "contradicted", best_raw

        return "unsupported", None
