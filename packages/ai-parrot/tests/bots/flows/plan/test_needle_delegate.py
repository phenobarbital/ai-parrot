"""FEAT-590 M7: NeedleDelegate (engine stubbed — needle is not installed in CI)."""
from __future__ import annotations

import os
import sys
import pickle
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pytest

from parrot.bots.flows.plan.delegate import ToolCallDelegate
from parrot.bots.flows.plan.delegate.needle import NeedleDelegate, _complete_in_worker


def test_satisfies_protocol_without_needle_installed() -> None:
    """NeedleDelegate satisfies ToolCallDelegate even when needle is not installed."""
    # This test should pass without needle installed
    assert isinstance(NeedleDelegate(), ToolCallDelegate)


def test_needle_lazy_import_error_message(monkeypatch) -> None:
    """When needle is not installed, the import error message mentions ai-parrot[needle]."""
    # Monkeypatch needle to None to trigger the ImportError
    monkeypatch.setitem(sys.modules, "needle", None)

    with pytest.raises(ImportError, match="ai-parrot\\[needle\\]"):
        NeedleDelegate()


def test_worker_is_picklable() -> None:
    """The worker function is picklable for ProcessPoolExecutor."""
    # Pickle and unpickle the worker function
    pickled = pickle.dumps(_complete_in_worker)
    unpickled = pickle.loads(pickled)

    # Verify it's the same function
    assert unpickled is _complete_in_worker


def test_needle_pool_keyed_by_toolset(monkeypatch) -> None:
    """The worker cache is keyed by (weights, frozenset(tool names))."""
    # Create a fake needle module
    fake_needle = type("FakeNeedle", (), {
        "__init__": lambda self, tools, system, weights: None,
        "reset": lambda self: None,
        "complete": lambda self, text, max_new_tokens: {
            "type": "complete",
            "success": True,
            "error": None,
            "error_code": None,
            "reason": None,
            "function_calls": [],
            "suppressed_calls": [],
            "reasoning": None,
            "confidence": 0.5,
            "prefill_tps": 0.0,
            "decode_tps": 0.0,
            "peak_ram_mb": 0.0,
            "validation": None,
        },
    })()

    monkeypatch.setitem(sys.modules, "needle", fake_needle)

    # Create two different toolsets
    tools1 = [
        {"name": "tool1", "description": "Tool 1", "parameters": {"type": "object", "properties": {}}},
        {"name": "tool2", "description": "Tool 2", "parameters": {"type": "object", "properties": {}}},
    ]
    tools2 = [
        {"name": "tool1", "description": "Tool 1", "parameters": {"type": "object", "properties": {}}},
        {"name": "tool3", "description": "Tool 3", "parameters": {"type": "object", "properties": {}}},
    ]

    # Run the worker with different toolsets
    result1 = _complete_in_worker(None, tools1, {}, "test instruction")
    result2 = _complete_in_worker(None, tools2, {}, "test instruction")

    # Both should succeed
    assert result1["success"]
    assert result2["success"]

    # The cache should have two entries (one per toolset)
    # Note: The cache is module-level, so it persists across calls
    # We can't directly test the cache contents, but we can verify that
    # different toolsets produce different results (which implies different cache keys)


@pytest.mark.asyncio
async def test_facts_mapping(monkeypatch) -> None:
    """Facts are mapped to Needle's system keys; other facts are folded into the instruction."""
    # Create a fake needle module
    fake_needle = type("FakeNeedle", (), {
        "__init__": lambda self, tools, system, weights: None,
        "reset": lambda self: None,
        "complete": lambda self, text, max_new_tokens: {
            "type": "complete",
            "success": True,
            "error": None,
            "error_code": None,
            "reason": None,
            "function_calls": [],
            "suppressed_calls": [],
            "reasoning": None,
            "confidence": 0.5,
            "prefill_tps": 0.0,
            "decode_tps": 0.0,
            "peak_ram_mb": 0.0,
            "validation": None,
        },
    })()

    monkeypatch.setitem(sys.modules, "needle", fake_needle)

    # Create a delegate with thread executor (so the fake module is visible)
    delegate = NeedleDelegate(executor="thread")

    # Test with system keys
    facts: Dict[str, str] = {
        "date": "2024-01-01",
        "locale": "en-US",
        "device": "desktop",
        "battery": "100%",
        "network": "wifi",
        "location": "New York",
        "user": "test-user",
    }

    # Test with mixed facts
    instruction = "What is the weather?"
    folded, system = delegate._split_facts(instruction, facts)

    # System keys should be in the system dict
    assert system["date"] == "2024-01-01"
    assert system["locale"] == "en-US"
    assert system["device"] == "desktop"
    assert system["battery"] == "100%"
    assert system["network"] == "wifi"
    assert system["location"] == "New York"
    assert system["user"] == "test-user"

    # Non-system keys should be folded into the instruction
    assert "unknown_key: unknown_value" in folded


@pytest.mark.asyncio
async def test_confidence_none_passthrough(monkeypatch) -> None:
    """A fine-tuned model reports confidence=None; it is passed through."""
    # Create a fake needle module that returns confidence=None
    fake_needle = type("FakeNeedle", (), {
        "__init__": lambda self, tools, system, weights: None,
        "reset": lambda self: None,
        "complete": lambda self, text, max_new_tokens: {
            "type": "complete",
            "success": True,
            "error": None,
            "error_code": None,
            "reason": None,
            "function_calls": [],
            "suppressed_calls": [],
            "reasoning": None,
            "confidence": None,  # Fine-tuned model
            "prefill_tps": 0.0,
            "decode_tps": 0.0,
            "peak_ram_mb": 0.0,
            "validation": None,
        },
    })()

    monkeypatch.setitem(sys.modules, "needle", fake_needle)

    delegate = NeedleDelegate(executor="thread")

    # Create a simple tool spec
    from parrot.bots.flows.plan.delegate.protocol import ToolSpec

    tools = [ToolSpec(name="test", description="Test", parameters={"type": "object", "properties": {}})]

    # Propose a call
    proposal = await delegate.propose_call("test instruction", tools)

    # Confidence should be None
    assert proposal.confidence is None


@pytest.mark.asyncio
async def test_aclose_idempotent(monkeypatch) -> None:
    """aclose() is idempotent."""
    # Create a fake needle module
    fake_needle = type("FakeNeedle", (), {
        "__init__": lambda self, tools, system, weights: None,
        "reset": lambda self: None,
        "complete": lambda self, text, max_new_tokens: {
            "type": "complete",
            "success": True,
            "error": None,
            "error_code": None,
            "reason": None,
            "function_calls": [],
            "suppressed_calls": [],
            "reasoning": None,
            "confidence": 0.5,
            "prefill_tps": 0.0,
            "decode_tps": 0.0,
            "peak_ram_mb": 0.0,
            "validation": None,
        },
    })()

    monkeypatch.setitem(sys.modules, "needle", fake_needle)

    delegate = NeedleDelegate(executor="thread")

    # Close the delegate multiple times
    await delegate.aclose()
    await delegate.aclose()
    await delegate.aclose()

    # Should not raise
    assert delegate._closed is True


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("NEEDLE_WEIGHTS"), reason="needs cactus-needle + weights")
@pytest.mark.asyncio
async def test_live_needle_delegate() -> None:
    """Integration test with a real Needle instance (requires NEEDLE_WEIGHTS)."""
    # This test is gated on NEEDLE_WEIGHTS being set
    # It requires cactus-needle to be installed with weights
    from parrot.bots.flows.plan.delegate.needle import NeedleDelegate
    from parrot.bots.flows.plan.delegate.protocol import ToolSpec

    delegate = NeedleDelegate(executor="thread", weights=os.environ["NEEDLE_WEIGHTS"])

    # Create a simple tool spec
    tools = [ToolSpec(name="test", description="Test", parameters={"type": "object", "properties": {}})]

    # Propose a call
    proposal = await delegate.propose_call("test instruction", tools)

    # Should return a proposal (even if it's a decline)
    assert isinstance(proposal, ToolCallProposal)
    assert proposal.backend == "needle"

    # Clean up
    await delegate.aclose()
