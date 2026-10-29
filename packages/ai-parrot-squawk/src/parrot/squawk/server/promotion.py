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
    model_config = ConfigDict(extra="forbid", frozen=True)
    cap_id: str
    args_digest: str
    llm_backed_calls: int
    deterministic_calls: int
    ratio: float


class PromotionAnalyzer:
    def __init__(self, ledger: ServedLedger, *, min_calls: int = 20) -> None:
        self._ledger = ledger
        self._min = min_calls

    def candidates(self, entries: Sequence[ServedLedgerEntry] | None = None) -> list[PromotionCandidate]:
        rows = entries if entries is not None else self._ledger.recent(limit=10_000)
        counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for e in rows:
            counts[(e.cap_id, e.args_digest)][0 if e.backing == "llm_backed" else 1] += 1
        out = [
            PromotionCandidate(
                cap_id=c,
                args_digest=d,
                llm_backed_calls=l,
                deterministic_calls=k,
                ratio=l / (l + k) if (l + k) > 0 else 0.0,
            )
            for (c, d), (l, k) in counts.items()
            if l >= self._min
        ]
        return sorted(out, key=lambda x: x.llm_backed_calls, reverse=True)

    def draft(self, candidate: PromotionCandidate, current: SquawkCapability, *, tool_name: str) -> CapabilityBinding:
        """Agent-proposed: same cap_id and I/O, backing flipped to deterministic, bound to tool_name."""
        cap = current.model_copy(update={"backing": "deterministic", "version": current.version + 1})
        return CapabilityBinding(capability=cap, tool_name=tool_name)

    async def approve(self, contract: SquawkContract, bindings: Sequence[CapabilityBinding], draft: CapabilityBinding, *, approver: str) -> SquawkContract:
        """Human act: replace the capability, rebuild (re-hash) the contract, ledger the approval."""
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
