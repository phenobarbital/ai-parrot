"""Promotion loop: LLM-backed call patterns → drafted deterministic capability → human approval (Q10, D12)."""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from parrot.interagent import CallCost, CallerIdentity, ServedLedgerEntry, SquawkCapability, SquawkContract
from parrot.squawk.contract import CapabilityBinding, build_contract
from parrot.squawk.server.ledger import ServedLedger


class PromotionCandidate(BaseModel):
    """A repeated LLM-backed call pattern worth promoting to a deterministic capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    cap_id: str
    args_digest: str
    llm_backed_calls: int
    deterministic_calls: int
    ratio: float


class PromotionAnalyzer:
    """Find promotion candidates in the served ledger, draft them, and apply human approval."""

    def __init__(self, ledger: ServedLedger, *, min_calls: int = 20) -> None:
        """Initialize the analyzer.

        Args:
            ledger: Served ledger read for candidates and written on approval.
            min_calls: Minimum successful LLM-backed calls before a pattern is proposed.
        """
        self._ledger = ledger
        self._min = min_calls

    def candidates(self, entries: Sequence[ServedLedgerEntry] | None = None) -> list[PromotionCandidate]:
        """Group successful calls by ``(cap_id, args_digest)`` and keep frequent LLM-backed ones.

        Failed calls are ignored: a pattern that errors is not evidence for promotion.

        Args:
            entries: Entries to analyze, defaulting to the ledger's recent window.

        Returns:
            Candidates sorted by LLM-backed call count, descending.
        """
        rows = entries if entries is not None else self._ledger.recent(limit=10_000)
        counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for e in rows:
            if (e.status if isinstance(e.status, str) else e.status.value) != "OK":
                continue
            counts[(e.cap_id, e.args_digest)][0 if e.backing == "llm_backed" else 1] += 1
        out = [
            PromotionCandidate(
                cap_id=c,
                args_digest=d,
                llm_backed_calls=n_llm,
                deterministic_calls=n_det,
                ratio=n_llm / (n_llm + n_det) if (n_llm + n_det) > 0 else 0.0,
            )
            for (c, d), (n_llm, n_det) in counts.items()
            if n_llm >= self._min
        ]
        return sorted(out, key=lambda x: x.llm_backed_calls, reverse=True)

    def draft(self, candidate: PromotionCandidate, current: SquawkCapability, *, tool_name: str) -> CapabilityBinding:
        """Draft a deterministic replacement (agent-proposed): same cap_id and I/O, bound to ``tool_name``.

        Args:
            candidate: The pattern being promoted; must match ``current``.
            current: The LLM-backed capability currently published.
            tool_name: Deterministic tool that will serve the capability.

        Returns:
            The drafted binding, version bumped.

        Raises:
            ValueError: If the candidate and capability disagree or ``current`` is not LLM-backed.
        """
        if candidate.cap_id != current.cap_id or current.backing != "llm_backed":
            raise ValueError("draft requires the candidate's own LLM-backed capability")
        cap = current.model_copy(update={"backing": "deterministic", "version": current.version + 1})
        return CapabilityBinding(capability=cap, tool_name=tool_name)

    async def approve(
        self,
        contract: SquawkContract,
        bindings: Sequence[CapabilityBinding],
        draft: CapabilityBinding,
        *,
        approver: str,
    ) -> SquawkContract:
        """Apply a human approval: replace the capability, rebuild (re-hash) the contract, ledger it.

        Args:
            contract: Currently published contract.
            bindings: Bindings that produced ``contract``.
            draft: Drafted deterministic binding from :meth:`draft`.
            approver: Identity of the approving human.

        Returns:
            The rebuilt contract.

        Raises:
            ValueError: If the draft targets an unknown capability or changes its I/O.
        """
        current = next((b.capability for b in bindings if b.capability.cap_id == draft.capability.cap_id), None)
        if current is None:
            raise ValueError(f"unknown capability: {draft.capability.cap_id}")
        if (
            current.input_schema != draft.capability.input_schema
            or current.returns != draft.capability.returns
            or current.category != draft.capability.category
        ):
            raise ValueError("promotion must keep the capability's category, input schema and returns")
        new = [b for b in bindings if b.capability.cap_id != draft.capability.cap_id] + [draft]
        promoted = build_contract(new, agent_id=contract.agent_id, major=contract.major)
        digest = "sha256:" + hashlib.sha256(draft.model_dump_json().encode()).hexdigest()
        await self._ledger.append(
            ServedLedgerEntry(
                entry_id=uuid.uuid4().hex,
                created_at=datetime.now(timezone.utc),
                caller=CallerIdentity(agent_id=approver, network="local", subject=approver),
                cap_id="squawk.promotion.approve",
                category="squawk.promotion",
                contract_hash=promoted.hashes[draft.capability.category],
                args_digest=digest,
                result_kind="inline",
                cost=CallCost(duration_ms=0),
                backing="deterministic",
                status="OK",
                trace_id=uuid.uuid4().hex,
            )
        )
        return promoted
