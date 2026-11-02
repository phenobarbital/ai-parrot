"""FEAT-772 (TASK-4902): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_account_security_vitest() -> None:
    """Account > Security: list, add, rename, delete passkeys and error copy."""
    run_vitest("src/pages/account/Security.test.ts")
