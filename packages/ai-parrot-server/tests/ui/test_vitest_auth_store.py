"""FEAT-772 (TASK-4900): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_auth_store_vitest() -> None:
    """AuthStore: BasicAuth + passkey login persistence, authMethod, logout, handle401."""
    run_vitest("src/lib/stores/auth.test.ts")
