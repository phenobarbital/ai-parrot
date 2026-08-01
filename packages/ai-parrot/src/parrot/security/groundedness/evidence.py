"""Per-turn evidence index for groundedness scoring.

Builds an :class:`EvidenceIndex` from a turn's ``ToolCall.result``
payloads (FEAT-398, spec §3 Module 2): an exact-match hash-set per atom
kind, plus a flat numeric list (money/percent/number) consumed by the
scorer's precision-aware tolerance and contradicted-band checks.
"""
from __future__ import annotations

import logging

from parrot.models.basic import ToolCall

from .extractors import extract_atoms
from .models import Atom, AtomKind
from .policy import GroundednessPolicy

logger = logging.getLogger(__name__)

#: Atom kinds compared via numeric (tolerance/contradicted-band) matching,
#: each kept in its own list — a money claim is only ever matched against
#: money evidence, never against a same-valued percent or bare number
#: extracted from TEXT (whose surface form, "$"/"%"/bare digits,
#: legitimately signals the kind). The one deliberate exception: a raw
#: JSON int/float scalar (e.g. ``{"revenue": 1243500}``) carries no such
#: signal, so it is indexed under all three kinds — see
#: ``EvidenceIndex.from_tool_calls``'s ``add_raw_numeric_scalar``.
_NUMERIC_KINDS = frozenset({AtomKind.MONEY, AtomKind.PERCENT, AtomKind.NUMBER})


class EvidenceIndex:
    """Per-turn evidence extracted from tool-call results.

    Attributes:
        by_kind: Exact-match sets of normalized atom values, keyed by
            :class:`AtomKind`.
        numeric_by_kind: Per-kind ``(normalized_value, raw)`` pairs for
            money/percent/number atoms found in evidence, used by the
            scorer's precision-aware tolerance and contradicted-band
            checks. Kept separate per :class:`AtomKind` so a money claim
            is never matched against percent/number evidence extracted
            from text that happens to share the same numeric value. Raw
            JSON int/float scalars (no surrounding text, no kind signal)
            are the deliberate exception — they populate all three lists.
        tool_call_count: Number of tool calls the index was built from.
            ``0`` means the turn had no tool results — the scorer's
            ``no_evidence`` case.
        evidence_truncated: True once ``max_evidence_bytes`` was hit
            while building the index.
    """

    def __init__(self) -> None:
        self.by_kind: dict[AtomKind, set] = {kind: set() for kind in AtomKind}
        self.numeric_by_kind: dict[AtomKind, list[tuple[float, str]]] = {
            kind: [] for kind in _NUMERIC_KINDS
        }
        self.tool_call_count: int = 0
        self.evidence_truncated: bool = False

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: list[ToolCall],
        policy: GroundednessPolicy,
        user_prompt: str | None = None,
    ) -> EvidenceIndex:
        """Build an :class:`EvidenceIndex` from a turn's tool-call results.

        Recursively traverses dict/list ``ToolCall.result`` payloads
        (both keys and values), extracting atoms from every string
        encountered and indexing every raw int/float scalar directly
        (see ``add_raw_numeric_scalar``), capped by
        ``policy.max_evidence_bytes``.

        Args:
            tool_calls: The turn's aggregated tool calls
                (``AIMessage.tool_calls``).
            policy: The active :class:`GroundednessPolicy`.
            user_prompt: The user's turn prompt. Folded in as additional
                evidence when ``policy.include_user_prompt_as_evidence``
                is True (the agent legitimately echoing a user-stated
                figure should not be flagged unsupported).

        Returns:
            The populated :class:`EvidenceIndex`.
        """
        index = cls()
        index.tool_call_count = len(tool_calls)
        consumed_bytes = 0

        def add_text(text: str) -> bool:
            nonlocal consumed_bytes
            size = len(text.encode("utf-8", errors="replace"))
            if consumed_bytes + size > policy.max_evidence_bytes:
                index.evidence_truncated = True
                return False
            consumed_bytes += size
            for atom in extract_atoms(
                text, min_number_digits=policy.min_number_digits,
            ):
                if atom.kind in policy.enabled_kinds:
                    index._add_atom(atom)
            return True

        def add_raw_numeric_scalar(value: float) -> bool:
            """Index a bare JSON int/float leaf (e.g. ``{"revenue": 1243500}``
            — the typical tool-output shape before any string formatting).

            Its surface form carries no ``$``/``%`` signal, so the intended
            kind is inherently ambiguous — unlike a string atom (which keeps
            exactly the kind its surface form signals), a raw scalar is
            indexed under every numeric kind the policy enables so a
            correctly-formatted ``money``/``percent`` answer claim can still
            match it. Also bypasses the ``min_number_digits`` noise floor
            (a returned scalar is a deliberate value, not incidental text
            noise), mirroring the existing money/magnitude-suffix
            exemptions in ``extractors.py``.
            """
            nonlocal consumed_bytes
            raw = str(value)
            size = len(raw.encode("utf-8", errors="replace"))
            if consumed_bytes + size > policy.max_evidence_bytes:
                index.evidence_truncated = True
                return False
            consumed_bytes += size
            normalized = float(value)
            for kind in (AtomKind.MONEY, AtomKind.PERCENT, AtomKind.NUMBER):
                if kind not in policy.enabled_kinds:
                    continue
                index._add_atom(
                    Atom(kind=kind, raw=raw, normalized=normalized, start=0, end=len(raw))
                )
            return True

        def walk(value: object) -> bool:
            if value is None:
                return True
            if isinstance(value, bool):
                # JSON booleans carry no hard-data atoms; also guards
                # against the int/float branch below (bool is an int
                # subclass in Python).
                return True
            if isinstance(value, dict):
                return (
                    all(walk(key) for key in value)
                    and all(walk(item) for item in value.values())
                )
            if isinstance(value, (list, tuple)):
                return all(walk(item) for item in value)
            if isinstance(value, (int, float)):
                return add_raw_numeric_scalar(value)
            text = value if isinstance(value, str) else str(value)
            return add_text(text)

        for tool_call in tool_calls:
            if tool_call.result is None:
                continue
            if not walk(tool_call.result):
                break

        if policy.include_user_prompt_as_evidence and user_prompt:
            add_text(user_prompt)

        return index

    def _add_atom(self, atom: Atom) -> None:
        """Record *atom* in the exact-match set and (if numeric) the list."""
        self.by_kind[atom.kind].add(atom.normalized)
        if atom.kind in _NUMERIC_KINDS:
            self.numeric_by_kind[atom.kind].append(
                (float(atom.normalized), atom.raw)
            )
