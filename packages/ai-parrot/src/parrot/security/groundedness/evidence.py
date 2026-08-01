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

#: Atom kinds pooled into the flat numeric evidence list (spec §2/§3: "a
#: numeric list for tolerance checks" — deliberately not per-kind).
_NUMERIC_KINDS = frozenset({AtomKind.MONEY, AtomKind.PERCENT, AtomKind.NUMBER})


class EvidenceIndex:
    """Per-turn evidence extracted from tool-call results.

    Attributes:
        by_kind: Exact-match sets of normalized atom values, keyed by
            :class:`AtomKind`.
        numeric_values: Flat ``(normalized_value, raw)`` pairs for every
            money/percent/number atom found in evidence.
        tool_call_count: Number of tool calls the index was built from.
            ``0`` means the turn had no tool results — the scorer's
            ``no_evidence`` case.
        evidence_truncated: True once ``max_evidence_bytes`` was hit
            while building the index.
    """

    def __init__(self) -> None:
        self.by_kind: dict[AtomKind, set] = {kind: set() for kind in AtomKind}
        self.numeric_values: list[tuple[float, str]] = []
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

        Recursively traverses dict/list ``ToolCall.result`` payloads,
        extracting atoms from every string (and stringified scalar)
        encountered, capped by ``policy.max_evidence_bytes``.

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

        def walk(value: object) -> bool:
            if value is None:
                return True
            if isinstance(value, dict):
                return all(walk(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return all(walk(item) for item in value)
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
            self.numeric_values.append((float(atom.normalized), atom.raw))
