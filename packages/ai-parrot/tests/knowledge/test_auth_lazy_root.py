"""parrot.auth lazy root keeps every export (FEAT-540 M1)."""
from __future__ import annotations

import parrot.auth as auth

from ._support.import_probe import run_import_probe


def test_every_public_name_resolves() -> None:
    """Every declared auth export remains resolvable through the package root."""
    for name in auth.__all__:
        assert getattr(auth, name) is not None, name


def test_dir_lists_exports() -> None:
    """The package directory exposes every lazy public auth export."""
    assert set(auth.__all__) <= set(dir(auth))


def test_exceptions_does_not_load_pbac() -> None:
    """Importing the lightweight exceptions module does not load PBAC settings."""
    result = run_import_probe("parrot.auth.exceptions")
    assert result.error is None, result.error
    assert not result.has("parrot.auth.pbac")
    assert not result.has("parrot.conf")
