"""FEAT-772 (TASK-4899): run the passkey API Vitest suite from pytest."""

from ._vitest import run_vitest


def test_passkey_api_vitest() -> None:
    """Passkey API: transport split, credential URLs, labels, and error messages."""
    run_vitest("src/lib/api/passkey.test.ts")
