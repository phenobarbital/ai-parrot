"""FEAT-772 (TASK-4898): run the WebAuthn Vitest suite from pytest."""

from ._vitest import run_vitest


def test_passkey_webauthn_vitest() -> None:
    """WebAuthn helper: native/fallback conversion, base64url, cancel classification."""
    run_vitest("src/lib/webauthn.test.ts")
