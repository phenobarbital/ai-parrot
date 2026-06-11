"""Unit tests for ConfirmationConfig, ConfirmationDecision,
InMemoryConfirmationWindowStore, and compute_args_hash.

Run with:
    pytest packages/ai-parrot/tests/test_confirmation_models.py -v
"""
import asyncio
import time

import pytest

from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationDecision,
    InMemoryConfirmationWindowStore,
    compute_args_hash,
)


# ── ConfirmationConfig ─────────────────────────────────────────────────────────


def test_config_defaults():
    """ConfirmationConfig defaults match spec (window_seconds=0, max_edit_retries=1)."""
    c = ConfirmationConfig()
    assert c.window_seconds == 0
    assert c.max_edit_retries == 1
    assert c.approval_timeout == 120.0
    assert c.default_channel == "telegram"


def test_config_custom_values():
    """ConfirmationConfig accepts custom values."""
    c = ConfirmationConfig(
        window_seconds=300,
        approval_timeout=60.0,
        default_channel="web",
        max_edit_retries=3,
    )
    assert c.window_seconds == 300
    assert c.approval_timeout == 60.0
    assert c.default_channel == "web"
    assert c.max_edit_retries == 3


def test_config_window_seconds_zero_valid():
    """window_seconds=0 is valid (always re-ask)."""
    c = ConfirmationConfig(window_seconds=0)
    assert c.window_seconds == 0


def test_config_max_edit_retries_zero_valid():
    """max_edit_retries=0 is valid (no retries)."""
    c = ConfirmationConfig(max_edit_retries=0)
    assert c.max_edit_retries == 0


# ── ConfirmationDecision ───────────────────────────────────────────────────────


def test_decision_defaults():
    """ConfirmationDecision: allowed=True, default status='confirmed'."""
    d = ConfirmationDecision(allowed=True, reason="approved")
    assert d.allowed is True
    assert d.status == "confirmed"
    assert d.parameters is None


def test_decision_cancelled():
    """ConfirmationDecision: allowed=False, status='cancelled'."""
    d = ConfirmationDecision(allowed=False, status="cancelled", reason="rejected")
    assert d.allowed is False
    assert d.status == "cancelled"


def test_decision_not_required():
    """ConfirmationDecision: not_required status."""
    d = ConfirmationDecision(
        allowed=True, status="not_required", reason="no confirmation needed"
    )
    assert d.status == "not_required"


def test_decision_with_parameters():
    """ConfirmationDecision: parameters field carries edited params."""
    params = {"employee_id": 123, "time": "09:00"}
    d = ConfirmationDecision(allowed=True, reason="ok", parameters=params)
    assert d.parameters == params


# ── compute_args_hash ──────────────────────────────────────────────────────────


def test_args_hash_order_independent():
    """Same keys/values in different order → same hash."""
    assert compute_args_hash({"a": 1, "b": 2}) == compute_args_hash({"b": 2, "a": 1})


def test_args_hash_different_values():
    """Different values → different hashes."""
    assert compute_args_hash({"a": 1}) != compute_args_hash({"a": 2})


def test_args_hash_different_keys():
    """Different keys → different hashes."""
    assert compute_args_hash({"x": 1}) != compute_args_hash({"y": 1})


def test_args_hash_empty():
    """Empty dict has a stable hash."""
    h1 = compute_args_hash({})
    h2 = compute_args_hash({})
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_args_hash_nested():
    """Nested dicts are handled (via default=str fallback)."""
    h1 = compute_args_hash({"a": {"x": 1}})
    h2 = compute_args_hash({"a": {"x": 1}})
    assert h1 == h2


def test_args_hash_non_json_value():
    """Non-JSON-serializable values don't crash (default=str)."""
    from datetime import datetime

    h = compute_args_hash({"ts": datetime(2024, 1, 1)})
    assert isinstance(h, str)
    assert len(h) == 64


# ── InMemoryConfirmationWindowStore ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_window_zero_never_confirms():
    """Recording with window_seconds=0 → is_confirmed always returns False."""
    store = InMemoryConfirmationWindowStore()
    await store.record("u1", "my_tool", "hash1", window_seconds=0)
    result = await store.is_confirmed("u1", "my_tool", "hash1")
    assert result is False


@pytest.mark.asyncio
async def test_window_records_and_confirms():
    """Recording with window_seconds=300 → is_confirmed returns True."""
    store = InMemoryConfirmationWindowStore()
    await store.record("u1", "my_tool", "hash1", window_seconds=300)
    result = await store.is_confirmed("u1", "my_tool", "hash1")
    assert result is True


@pytest.mark.asyncio
async def test_window_different_hash_is_false():
    """A recorded key does not match a different args_hash."""
    store = InMemoryConfirmationWindowStore()
    await store.record("u1", "my_tool", "hash1", window_seconds=300)
    result = await store.is_confirmed("u1", "my_tool", "hash_other")
    assert result is False


@pytest.mark.asyncio
async def test_window_unknown_key_is_false():
    """Unknown key returns False without error."""
    store = InMemoryConfirmationWindowStore()
    result = await store.is_confirmed("nobody", "tool", "hash")
    assert result is False


@pytest.mark.asyncio
async def test_window_different_owner_is_false():
    """A window recorded for one owner does not apply to another."""
    store = InMemoryConfirmationWindowStore()
    await store.record("user_a", "my_tool", "hash1", window_seconds=300)
    result = await store.is_confirmed("user_b", "my_tool", "hash1")
    assert result is False


@pytest.mark.asyncio
async def test_window_expires():
    """A window with window_seconds=1 expires after 1 second."""
    store = InMemoryConfirmationWindowStore()
    await store.record("u1", "my_tool", "hash1", window_seconds=1)
    # Verify it's active immediately
    assert await store.is_confirmed("u1", "my_tool", "hash1") is True
    # Wait for expiry
    await asyncio.sleep(1.1)
    assert await store.is_confirmed("u1", "my_tool", "hash1") is False


@pytest.mark.asyncio
async def test_window_records_and_expires_separate_entry():
    """Expired key is lazily cleaned up; a different active key still works."""
    store = InMemoryConfirmationWindowStore()
    await store.record("u1", "tool_a", "hash1", window_seconds=1)
    await store.record("u1", "tool_b", "hash2", window_seconds=300)

    await asyncio.sleep(1.1)

    assert await store.is_confirmed("u1", "tool_a", "hash1") is False
    assert await store.is_confirmed("u1", "tool_b", "hash2") is True
