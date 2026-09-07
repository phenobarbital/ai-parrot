"""Shared fixtures for the ai-parrot-saas test suite.

Most of the suite is pure and needs nothing external. Tests that genuinely
exercise SQL are marked ``integration`` and skip unless ``SAAS_TEST_DSN``
points at a reachable PostgreSQL instance, so a contributor without a
database still gets a meaningful green run rather than a wall of errors.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator, Iterator

import pytest

#: Master keys used by the whole suite. Fixed rather than random so a failure
#: is reproducible; obviously never used outside tests.
TEST_MASTER_KEYS = {1: b"\xa1" * 32, 2: b"\xb2" * 32}


def pytest_configure(config: pytest.Config) -> None:
    """Register the suite's custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: requires a real PostgreSQL instance via SAAS_TEST_DSN",
    )
    config.addinivalue_line(
        "markers",
        "live: requires external infrastructure (Docker daemon, Pulumi CLI)",
    )


@pytest.fixture(scope="session")
def test_dsn() -> str:
    """DSN of a PostgreSQL instance usable by integration tests.

    Skips the test when unset, so the default developer experience does not
    depend on having a database.
    """
    dsn = os.environ.get("SAAS_TEST_DSN")
    if not dsn:
        pytest.skip("SAAS_TEST_DSN is not set; skipping integration test")
    return dsn


@pytest.fixture
def master_keys() -> dict[int, bytes]:
    """The suite's fixed master keys, as a fixture.

    Exposed this way rather than imported across test modules: the tests
    directory is not a package, so a relative import would not resolve.
    """
    return dict(TEST_MASTER_KEYS)


@pytest.fixture
def envelope_cipher():
    """An :class:`EnvelopeCipher` with the suite's fixed master keys."""
    from parrot.security.secrets.envelope import EnvelopeCipher

    return EnvelopeCipher(TEST_MASTER_KEYS, active_key_id=1)


@pytest.fixture
def unique_schema() -> Iterator[str]:
    """A collision-free schema name for one integration test.

    Each test owns its own schema so the suite can run in parallel (and so a
    failure leaves evidence behind without poisoning the next run).
    """
    yield f"saas_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def secret_store(test_dsn: str, unique_schema: str, envelope_cipher) -> AsyncIterator:
    """An :class:`EncryptedPostgresSecretStore` on a throwaway schema."""
    from asyncdb import AsyncDB

    from parrot.security.secrets.postgres import EncryptedPostgresSecretStore

    store = EncryptedPostgresSecretStore(
        test_dsn, schema=unique_schema, cipher=envelope_cipher
    )
    try:
        yield store
    finally:
        await store.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")
