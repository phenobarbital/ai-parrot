"""FEAT-772: the documented passkey settings example is accepted by navigator-auth as-is."""

from __future__ import annotations

import json
from pathlib import Path

from navigator_auth.passkey.rp import RelyingPartyResolver

EXAMPLE = Path(__file__).resolve().parents[3] / "docs" / "examples" / "passkey.settings.example"


def _settings() -> dict[str, str]:
    """Parse KEY=value lines (``#`` comments skipped, one level of single quotes stripped)."""
    out: dict[str, str] = {}
    for raw in EXAMPLE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().removeprefix("'").removesuffix("'")
    return out


def test_relying_parties_pass_navigator_auth_validation() -> None:
    """RelyingPartyResolver raises ConfigError on a bad rp_id / duplicate origin / empty list."""
    parties = json.loads(_settings()["PASSKEY_RELYING_PARTIES"])
    RelyingPartyResolver(parties)
    assert "http://localhost:5173" in {p["origin"] for p in parties}


def test_backends_enable_passkey_next_to_basic() -> None:
    backends = _settings()["AUTHENTICATION_BACKENDS"].split(",")
    assert backends == ["navigator_auth.backends.BasicAuth", "navigator_auth.backends.PasskeyAuth"]
    # FILL IN: PASSKEY_USER_VERIFICATION ∈ {"required","preferred","discouraged"} (conf.py:611 + backend check)
    assert _settings()["PASSKEY_USER_VERIFICATION"] in {"required", "preferred", "discouraged"}
