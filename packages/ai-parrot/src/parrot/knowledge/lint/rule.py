"""LintRule protocol and fingerprint helper (FEAT-625)."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from parrot.knowledge.lint.models import Finding, FixResult, Severity

if TYPE_CHECKING:
    from parrot.knowledge.lint.context import LintContext


def make_fingerprint(rule_id: str, subjects: Sequence[str]) -> str:
    """Return a stable sha1 over ``rule_id`` and the SORTED subjects."""
    payload = rule_id + "\x1f" + "\x1f".join(sorted(subjects))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


@runtime_checkable
class LintRule(Protocol):
    """A single lint rule; packs are plain classes satisfying this protocol."""

    rule_id: str
    pack: str
    default_severity: Severity

    async def check(self, ctx: "LintContext") -> list[Finding]:
        """Return findings; MUST NOT mutate the store."""
        ...

    async def fix(self, ctx: "LintContext", finding: Finding) -> FixResult | None:
        """Apply an idempotent safe fix, or return None when the rule never fixes."""
        ...
