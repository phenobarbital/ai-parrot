"""Unit tests for the Identity Vault re-encryption job (FEAT-773 M10, AC-18)."""

from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, Callable, Dict, List, Literal

from parrot.auth.oauth2.reencrypt import (
    reencrypt_identities,
    retirement_allowed,
    RowClass,
)

# Test fixtures


class MockRow(dict):
    """Mock row with auth_provider and user_id attributes."""

    def __init__(self, provider: str, user_id: int, **kwargs):
        super().__init__(auth_provider=provider, user_id=user_id, **kwargs)
        self.auth_provider = provider
        self.user_id = user_id


class MockLock:
    """Mock lock that tracks acquisitions."""

    def __init__(self):
        self.acquired_providers: List[tuple] = []
        self._acquired = False

    @asynccontextmanager
    async def __call__(self, provider: str, user_id: str) -> AsyncContextManager[Any]:
        self.acquired_providers.append((provider, user_id))
        self._acquired = True
        yield self
        self._acquired = False


@pytest.fixture
def mock_lock() -> MockLock:
    return MockLock()


@pytest.fixture
def sample_rows() -> List[MockRow]:
    """Sample rows for testing."""
    return [
        MockRow("jira", 1001, identity_id="id-1"),
        MockRow("jira", 1002, identity_id="id-2"),
        MockRow("github", 2001, identity_id="id-3"),
    ]


# Tests


@pytest.mark.asyncio
async def test_reencrypt_dry_run_counts_only():
    """Dry-run (apply=False) should count rows but never call reseal_row."""
    rows = [
        MockRow("jira", 1001, identity_id="id-1"),
        MockRow("jira", 1002, identity_id="id-2"),
        MockRow("github", 2001, identity_id="id-3"),
    ]

    lock = MockLock()
    reseal_calls: List[Any] = []

    async def mock_reseal(row: Any) -> None:
        reseal_calls.append(row)

    def mock_verify(row: Any) -> bool:
        return True

    def mock_classify(row: Any) -> RowClass:
        return "current"

    counts = await reencrypt_identities(
        rows,
        lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=False,  # dry-run
    )

    # Should have counts
    assert "jira" in counts
    assert "github" in counts
    assert counts["jira"]["current"] == 2
    assert counts["github"]["current"] == 1

    # Should NOT have called reseal
    assert len(reseal_calls) == 0

    # Should have acquired locks for each row
    assert len(lock.acquired_providers) == 3


@pytest.mark.asyncio
async def test_reencrypt_undecryptable_row_counted_failed():
    """Undecryptable rows should be counted as failed and never modified."""
    rows = [
        MockRow("jira", 1001, identity_id="id-1"),
        MockRow("jira", 1002, identity_id="id-2"),  # This one is failed
        MockRow("github", 2001, identity_id="id-3"),
    ]

    lock = MockLock()
    reseal_calls: List[Any] = []

    async def mock_reseal(row: Any) -> None:
        reseal_calls.append(row)

    def mock_verify(row: Any) -> bool:
        return True

    def mock_classify(row: Any) -> RowClass:
        # Second jira row is failed
        if row["identity_id"] == "id-2":
            return "failed"
        return "current"

    counts = await reencrypt_identities(
        rows,
        lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=True,
    )

    # Should have failed count
    assert counts["jira"]["failed"] == 1
    assert counts["jira"]["current"] == 1

    # Should NOT have resealed the failed row
    assert len(reseal_calls) == 2  # Only the two non-failed rows


def test_reencrypt_retirement_gate():
    """Key retirement requires full-store scan with stale == 0 and failed == 0."""
    # Full-store scan, all current
    counts_full_clean = {
        "jira": {"current": 10, "stale": 0, "resealed": 0, "failed": 0},
        "github": {"current": 5, "stale": 0, "resealed": 0, "failed": 0},
    }
    assert retirement_allowed(counts_full_clean, provider_filter=[]) is True

    # Provider-filtered scan (cannot authorize retirement)
    counts_filtered = {
        "jira": {"current": 10, "stale": 0, "resealed": 0, "failed": 0},
    }
    assert retirement_allowed(counts_filtered, provider_filter=["jira"]) is False

    # Full-store scan with stale rows
    counts_with_stale = {
        "jira": {"current": 10, "stale": 2, "resealed": 0, "failed": 0},
        "github": {"current": 5, "stale": 0, "resealed": 0, "failed": 0},
    }
    assert retirement_allowed(counts_with_stale, provider_filter=[]) is False

    # Full-store scan with failed rows
    counts_with_failed = {
        "jira": {"current": 10, "stale": 0, "resealed": 0, "failed": 1},
        "github": {"current": 5, "stale": 0, "resealed": 0, "failed": 0},
    }
    assert retirement_allowed(counts_with_failed, provider_filter=[]) is False


@pytest.mark.asyncio
async def test_reencrypt_takes_principal_lock():
    """Each row should be processed under its principal lock."""
    rows = [
        MockRow("jira", 1001, identity_id="id-1"),
        MockRow("jira", 1002, identity_id="id-2"),
        MockRow("github", 2001, identity_id="id-3"),
    ]

    lock = MockLock()
    lock_order: List[tuple] = []

    @asynccontextmanager
    async def tracking_lock(provider: str, user_id: str):
        lock_order.append(("acquire", provider, user_id))
        yield None
        lock_order.append(("release", provider, user_id))

    async def mock_reseal(row: Any) -> None:
        pass

    def mock_verify(row: Any) -> bool:
        return True

    def mock_classify(row: Any) -> RowClass:
        return "current"

    counts = await reencrypt_identities(
        rows,
        tracking_lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=False,
    )

    # Should have acquired locks in order
    assert len(lock_order) == 6  # 3 acquires + 3 releases

    # Check that locks were acquired for each row
    acquires = [item for item in lock_order if item[0] == "acquire"]
    assert len(acquires) == 3

    # Verify the lock keys match the expected pattern
    providers_user_ids = {(item[1], item[2]) for item in acquires}
    assert ("jira", "1001") in providers_user_ids
    assert ("jira", "1002") in providers_user_ids
    assert ("github", "2001") in providers_user_ids


@pytest.mark.asyncio
async def test_refresh_under_new_key_before_migration_is_stale():
    """Row stamped v2 with a v1 id_token should be classified stale and resealed.

    This tests the M10 "refresh under the new key before migration" gate:
    - A refresh after activating v2 stamps the row v2
    - But if id_token was minted under v1, it remains v1-encrypted
    - The scan should detect this as stale and re-seal it
    """
    rows = [
        MockRow("jira", 1001, identity_id="id-1", key_version=2),
    ]

    lock = MockLock()
    reseal_calls: List[Any] = []

    async def mock_reseal(row: Any) -> None:
        reseal_calls.append(row)

    def mock_verify(row: Any) -> bool:
        # After re-seal, verification succeeds
        return len(reseal_calls) > 0

    def mock_classify(row: Any) -> RowClass:
        # Row has key_version=2 but id_token is v1-encrypted
        # This is the "stale" case: decrypts with full ring but not active-only
        return "stale"

    counts = await reencrypt_identities(
        rows,
        lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=True,
    )

    # Should have stale count
    assert counts["jira"]["stale"] == 1

    # Should have resealed the row
    assert len(reseal_calls) == 1

    # Should have resealed count
    assert counts["jira"]["resealed"] == 1


@pytest.mark.asyncio
async def test_reencrypt_apply_reseals_current_rows():
    """With apply=True, current rows should be resealed."""
    rows = [
        MockRow("jira", 1001, identity_id="id-1"),
        MockRow("jira", 1002, identity_id="id-2"),
    ]

    lock = MockLock()
    reseal_calls: List[Any] = []

    async def mock_reseal(row: Any) -> None:
        reseal_calls.append(row)

    def mock_verify(row: Any) -> bool:
        return True

    def mock_classify(row: Any) -> RowClass:
        return "current"

    counts = await reencrypt_identities(
        rows,
        lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=True,
    )

    # Should have resealed both rows
    assert len(reseal_calls) == 2
    assert counts["jira"]["resealed"] == 2
    assert counts["jira"]["current"] == 2


@pytest.mark.asyncio
async def test_reencrypt_verification_failure_counts_failed():
    """If verification fails after re-seal, row should be counted as failed."""
    rows = [
        MockRow("jira", 1001, identity_id="id-1"),
    ]

    lock = MockLock()
    reseal_calls: List[Any] = []

    async def mock_reseal(row: Any) -> None:
        reseal_calls.append(row)

    def mock_verify(row: Any) -> bool:
        # Verification fails
        return False

    def mock_classify(row: Any) -> RowClass:
        return "stale"

    counts = await reencrypt_identities(
        rows,
        lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=True,
    )

    # Should have attempted re-seal
    assert len(reseal_calls) == 1

    # But verification failure should count as failed
    assert counts["jira"]["failed"] == 1
    assert counts["jira"]["resealed"] == 0


@pytest.mark.asyncio
async def test_reencrypt_reseal_exception_counts_failed():
    """If reseal raises an exception, row should be counted as failed."""
    rows = [
        MockRow("jira", 1001, identity_id="id-1"),
    ]

    lock = MockLock()

    async def mock_reseal(row: Any) -> None:
        raise RuntimeError("Database error")

    def mock_verify(row: Any) -> bool:
        return True

    def mock_classify(row: Any) -> RowClass:
        return "stale"

    counts = await reencrypt_identities(
        rows,
        lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=True,
    )

    # Should have counted as failed
    assert counts["jira"]["failed"] == 1
    assert counts["jira"]["resealed"] == 0


@pytest.mark.asyncio
async def test_reencrypt_handles_multiple_providers():
    """Should correctly aggregate counts across multiple providers."""
    rows = [
        MockRow("jira", 1001, identity_id="id-1"),
        MockRow("jira", 1002, identity_id="id-2"),
        MockRow("github", 2001, identity_id="id-3"),
        MockRow("github", 2002, identity_id="id-4"),
        MockRow("github", 2003, identity_id="id-5"),
        MockRow("o365", 3001, identity_id="id-6"),
    ]

    lock = MockLock()

    async def mock_reseal(row: Any) -> None:
        pass

    def mock_verify(row: Any) -> bool:
        return True

    def mock_classify(row: Any) -> RowClass:
        # Mix of classifications
        if row["identity_id"] in ("id-1", "id-3"):
            return "current"
        elif row["identity_id"] in ("id-2", "id-4"):
            return "stale"
        else:
            return "failed"

    counts = await reencrypt_identities(
        rows,
        lock,
        reseal_row=mock_reseal,
        verify_active=mock_verify,
        classify=mock_classify,
        apply=False,
    )

    # Check counts per provider
    assert counts["jira"]["current"] == 1
    assert counts["jira"]["stale"] == 1
    assert counts["jira"]["failed"] == 0

    assert counts["github"]["current"] == 1
    assert counts["github"]["stale"] == 1
    assert counts["github"]["failed"] == 1

    assert counts["o365"]["current"] == 0
    assert counts["o365"]["stale"] == 0
    assert counts["o365"]["failed"] == 1


# --- Review fixes: fail-closed retirement, fresh verification (FEAT-773) ---


def test_retirement_denied_when_nothing_was_scanned() -> None:
    """An empty scan (e.g. setup failure) must never authorize key retirement."""
    assert retirement_allowed({}, provider_filter=[]) is False
    assert retirement_allowed({"jira": {"current": 0, "stale": 0, "failed": 0}}, provider_filter=[]) is False


@pytest.mark.asyncio
async def test_async_verifier_is_awaited_after_reseal() -> None:
    """verify_active may be a coroutine (it re-reads the row); its result decides resealed vs failed."""
    lock = MockLock()
    seen: List[Any] = []

    async def reseal(row: Any) -> None:
        seen.append(("reseal", row["user_id"]))

    async def verify_ok(row: Any) -> bool:
        seen.append(("verify", row["user_id"]))
        return True

    async def verify_bad(row: Any) -> bool:
        return False

    row = MockRow("jira", 1)
    ok = await reencrypt_identities(
        [row], lock, reseal_row=reseal, verify_active=verify_ok, classify=lambda r: "stale", apply=True
    )
    assert ok["jira"]["resealed"] == 1 and ("verify", 1) in seen
    bad = await reencrypt_identities(
        [row], lock, reseal_row=reseal, verify_active=verify_bad, classify=lambda r: "stale", apply=True
    )
    assert bad["jira"]["failed"] == 1 and bad["jira"].get("resealed", 0) == 0


@pytest.mark.asyncio
async def test_lock_failure_aborts_without_resealing() -> None:
    """If the principal lock cannot be acquired the row is never re-sealed."""
    resealed: List[Any] = []

    @asynccontextmanager
    async def refusing_lock(provider: str, user_id: str):
        raise RuntimeError("could not acquire refresh lock")
        yield  # pragma: no cover

    async def reseal(row: Any) -> None:
        resealed.append(row)

    with pytest.raises(RuntimeError):
        await reencrypt_identities(
            [MockRow("jira", 1)],
            refusing_lock,
            reseal_row=reseal,
            verify_active=lambda r: True,
            classify=lambda r: "stale",
            apply=True,
        )
    assert resealed == []
