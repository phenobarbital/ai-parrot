"""FEAT-799: check_bwrap_sandbox is public and aliased."""

from parrot.self_ import doctor


def test_public_name_is_alias() -> None:
    """The backwards-compatible private name resolves to the public function."""
    assert doctor.check_bwrap_sandbox is doctor._check_bwrap_sandbox


def test_non_linux_returns_empty(monkeypatch) -> None:
    """The public diagnostic preserves non-Linux no-op behavior."""
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    assert doctor.check_bwrap_sandbox() == []
