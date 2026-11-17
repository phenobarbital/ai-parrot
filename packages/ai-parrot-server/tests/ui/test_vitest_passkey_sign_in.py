"""FEAT-772 (TASK-4901): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_passkey_sign_in_vitest() -> None:
    """Login page passkey button, conditional UI, ProviderButtons filtering."""
    run_vitest("src/lib/components/auth/PasskeySignIn.test.ts", "src/pages/Login.test.ts")
