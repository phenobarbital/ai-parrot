"""FEAT-772 packaging guard: the passkey extra exists, is in ``all``, and the lock carries it."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_PYPROJECT = REPO_ROOT / "packages" / "ai-parrot-server" / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads(SERVER_PYPROJECT.read_text())
    return data["project"]["optional-dependencies"]


def test_passkey_extra_pins_navigator_auth_passkey() -> None:
    """The extra pulls navigator-auth's passkey extra at the first release that ships PasskeyAuth."""
    assert _extras()["passkey"] == ["navigator-auth[passkey]>=0.28.9"]


def test_all_includes_passkey() -> None:
    """``ai-parrot-server[all]`` installs the passkey extra too."""
    (aggregate,) = _extras()["all"]
    assert "passkey" in aggregate.split("[", 1)[1].rstrip("]").split(",")


def test_lock_resolves_passkey_capable_navigator_auth() -> None:
    """uv.lock pins navigator-auth >= 0.28.9 and contains webauthn."""
    lock = tomllib.loads(UV_LOCK.read_text())
    packages = {package["name"]: package["version"] for package in lock["package"]}

    assert tuple(int(value) for value in packages["navigator-auth"].split(".")[:3]) >= (0, 28, 9)
    assert "webauthn" in packages
    assert packages["webauthn"].split(".", 1)[0] == "2"
