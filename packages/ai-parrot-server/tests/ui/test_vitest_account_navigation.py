"""FEAT-772 (TASK-4903): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_account_navigation_vitest() -> None:
    """Run /account/security route, Topbar link, and Passkey badge tests."""
    run_vitest("src/lib/router.test.ts", "src/App.test.ts", "src/lib/components/AppShell.test.ts")
