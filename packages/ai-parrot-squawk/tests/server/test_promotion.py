"""Tests for server/promotion.py."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from parrot.interagent import CallCost, CallerIdentity, ServedLedgerEntry
from parrot.squawk.contract import CapabilityBinding
from parrot.squawk.server.ledger import ServedLedger
from parrot.squawk.server.promotion import PromotionAnalyzer, PromotionCandidate


def test_candidates_threshold():
    from parrot.security.audit_ledger import LocalHMACSigner

    ledger = ServedLedger(signer=LocalHMACSigner(b"test-key"))
    entries = [
        ServedLedgerEntry(
            entry_id=f"e{i}",
            created_at=datetime(2025, 1, 1, 12, 0, i, tzinfo=timezone.utc),
            caller=CallerIdentity(agent_id="agent1", network="net1", subject="subj1"),
            cap_id="cap1",
            category="cat1",
            contract_hash="h1",
            args_digest="digest1",
            result_kind="inline",
            cost=CallCost(duration_ms=100, tokens_in=10, tokens_out=20),
            backing="llm_backed" if i < 25 else "deterministic",
            status="OK",
            trace_id=f"trace{i}",
            signature=f"sig{i}",
        )
        for i in range(28)
    ]
    analyzer = PromotionAnalyzer(ledger, min_calls=20)
    candidates = analyzer.candidates(entries)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.cap_id == "cap1"
    assert c.args_digest == "digest1"
    assert c.llm_backed_calls == 25
    assert c.deterministic_calls == 3
    assert c.ratio == 25 / 28


def test_candidates_below_threshold():
    from parrot.security.audit_ledger import LocalHMACSigner

    ledger = ServedLedger(signer=LocalHMACSigner(b"test-key"))
    entries = [
        ServedLedgerEntry(
            entry_id=f"e{i}",
            created_at=datetime(2025, 1, 1, 12, 0, i, tzinfo=timezone.utc),
            caller=CallerIdentity(agent_id="agent1", network="net1", subject="subj1"),
            cap_id="cap1",
            category="cat1",
            contract_hash="h1",
            args_digest="digest1",
            result_kind="inline",
            cost=CallCost(duration_ms=100, tokens_in=10, tokens_out=20),
            backing="llm_backed" if i < 15 else "deterministic",
            status="OK",
            trace_id=f"trace{i}",
            signature=f"sig{i}",
        )
        for i in range(18)
    ]
    analyzer = PromotionAnalyzer(ledger, min_calls=20)
    candidates = analyzer.candidates(entries)
    assert len(candidates) == 0


def test_draft_flips_backing_and_bumps_version():
    from parrot.interagent import SquawkCapability, ReturnsSpec

    cap = SquawkCapability(
        cap_id="cat1.cap1",
        category="cat1",
        description="Test capability",
        input_schema={},
        returns=ReturnsSpec(kind="inline", schema={}),
        backing="llm_backed",
        version=1,
    )
    analyzer = PromotionAnalyzer(ledger=None, min_calls=20)
    candidate = PromotionCandidate(
        cap_id="cat1.cap1", args_digest="digest1", llm_backed_calls=25, deterministic_calls=3, ratio=25 / 28
    )
    binding = analyzer.draft(candidate, cap, tool_name="tool1")
    assert binding.capability.backing == "deterministic"
    assert binding.capability.version == 2
    assert binding.capability.cap_id == "cat1.cap1"
    assert binding.tool_name == "tool1"


async def test_approve_rehashes_category_and_appends_one_entry():
    from parrot.interagent import SquawkContract, SquawkCapability, ReturnsSpec
    from parrot.security.audit_ledger import LocalHMACSigner

    ledger = ServedLedger(signer=LocalHMACSigner(b"test-key"))
    analyzer = PromotionAnalyzer(ledger, min_calls=20)
    cap1 = SquawkCapability(
        cap_id="cat1.cap1",
        category="cat1",
        description="Test 1",
        input_schema={},
        returns=ReturnsSpec(kind="inline", schema={}),
        backing="llm_backed",
        version=1,
    )
    cap2 = SquawkCapability(
        cap_id="cat2.cap2",
        category="cat2",
        description="Test 2",
        input_schema={},
        returns=ReturnsSpec(kind="inline", schema={}),
        backing="llm_backed",
        version=1,
    )
    from parrot.squawk.contract import LLMBackedSpec

    bindings = [
        CapabilityBinding(capability=cap1, llm_backed=LLMBackedSpec(system_prompt="prompt1", output_schema={})),
        CapabilityBinding(capability=cap2, llm_backed=LLMBackedSpec(system_prompt="prompt2", output_schema={})),
    ]
    from parrot.interagent import CapabilityCategory

    cat1 = CapabilityCategory(name="cat1", capabilities=(cap1,))
    cat2 = CapabilityCategory(name="cat2", capabilities=(cap2,))
    contract = SquawkContract(agent_id="agent1", major=1, categories=(cat1, cat2))
    candidate = PromotionCandidate(
        cap_id="cat1.cap1", args_digest="digest1", llm_backed_calls=25, deterministic_calls=3, ratio=25 / 28
    )
    draft = analyzer.draft(candidate, cap1, tool_name="tool1")
    promoted = await analyzer.approve(contract, bindings, draft, approver="approver1")
    assert promoted.agent_id == "agent1"
    assert promoted.major == 1
    assert "cat1" in promoted.hashes
    assert promoted.hashes["cat1"] != contract.hashes["cat1"]
    entries = ledger.recent(limit=10)
    assert len(entries) == 1
    e = entries[0]
    assert e.cap_id == "squawk.promotion.approve"
    assert e.backing == "deterministic"
    assert e.status == "OK"
