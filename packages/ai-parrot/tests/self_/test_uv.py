"""Tests for bounded ``parrot.self_.uv`` resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parrot.self_ import uv

posix_only = pytest.mark.skipif(os.name == "nt", reason="fake uv binaries are sh scripts")


def _fake_uv(path: Path, version: str) -> Path:
    """Create a tiny executable that prints the given uv version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "uv {version} (abc123 2026-01-01)"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set an isolated Parrot home and PATH."""
    result = tmp_path / "parrot-home"
    result.mkdir()
    monkeypatch.setenv("PARROT_HOME", str(result))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    return result


@pytest.mark.parametrize(
    ("version", "ok"),
    [("0.11.27", False), ("0.11.28", True), ("0.11.99", True), ("0.12.0", False), ("0.13.7", False), ("garbage", False), (None, False)],
)
def test_in_range(version: str | None, ok: bool) -> None:
    """The supported 0.11 uv range excludes both adjacent versions."""
    assert uv.in_range(version) is ok


@posix_only
def test_managed_copy_wins(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A compatible managed copy precedes a compatible PATH uv."""
    _fake_uv(uv.managed_uv(), "0.11.28")
    system = _fake_uv(tmp_path / "sys" / "uv", "0.11.30")
    monkeypatch.setenv("PATH", str(system.parent))
    assert uv.resolve_uv().source == "managed"


@posix_only
def test_recorded_uv_used_and_out_of_range_skipped(home: Path, tmp_path: Path) -> None:
    """Recorded uv is used until its installed version leaves the compatible range."""
    system = _fake_uv(tmp_path / "sys" / "uv", "0.11.30")
    uv.record_system_uv(system)
    assert uv.resolve_uv() == uv.UvResolution(path=system, version="0.11.30", source="recorded")
    _fake_uv(system, "0.13.0")
    with pytest.raises(FileNotFoundError, match="install-parrot --global"):
        uv.resolve_uv()


@posix_only
def test_path_search_skips_parrot_bin(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The old managed bin location is excluded from PATH resolution."""
    _fake_uv(home / "bin" / "uv", "0.11.28")
    monkeypatch.setenv("PATH", str(home / "bin"))
    assert uv.find_path_uv() is None
    assert uv.resolve_uv().source == "legacy"


@posix_only
def test_record_keeps_symlink_path(home: Path, tmp_path: Path) -> None:
    """Recording a system uv preserves a stable Homebrew-style symlink path."""
    real = _fake_uv(tmp_path / "cellar" / "0.11.30" / "uv", "0.11.30")
    link = tmp_path / "brew-bin" / "uv"
    link.parent.mkdir()
    link.symlink_to(real)
    uv.record_system_uv(link)
    assert uv.read_recorded_uv() == link.absolute()


@posix_only
def test_migrate_records_system_uv_and_never_touches_it(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration records a compatible user uv before removing legacy shadowing files."""
    _fake_uv(home / "bin" / "uv", "0.11.28")
    _fake_uv(home / "bin" / "uvx", "0.11.28")
    system = _fake_uv(tmp_path / "sys" / "uv", "0.11.30")
    before = (system.read_bytes(), system.stat().st_mtime_ns)
    monkeypatch.setenv("PATH", f"{home / 'bin'}{os.pathsep}{system.parent}")
    log = uv.migrate_legacy_uv()
    assert not (home / "bin" / "uv").exists() and not (home / "bin" / "uvx").exists()
    assert uv.read_recorded_uv() == system and log
    assert (system.read_bytes(), system.stat().st_mtime_ns) == before


@posix_only
def test_migrate_moves_legacy_copy_without_system_uv(home: Path) -> None:
    """Migration moves a compatible legacy uv into private libexec when no system uv exists."""
    _fake_uv(home / "bin" / "uv", "0.11.28")
    uv.migrate_legacy_uv()
    assert uv.managed_uv().is_file() and not (home / "bin" / "uv").exists()


def test_migrate_noop_without_legacy(home: Path) -> None:
    """Migration does nothing for an already clean layout."""
    assert uv.migrate_legacy_uv() == []


@posix_only
def test_migrate_keeps_files_when_nothing_is_compatible(home: Path) -> None:
    """Migration preserves legacy files when no viable replacement exists."""
    _fake_uv(home / "bin" / "uv", "0.10.0")
    log = uv.migrate_legacy_uv()
    assert (home / "bin" / "uv").exists() and log[0].startswith("warning:")
