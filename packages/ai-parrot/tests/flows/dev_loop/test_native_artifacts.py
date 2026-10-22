"""Tests for parrot.flows.dev_loop.native_artifacts (FEAT-722)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.native_artifacts import (
    AUTOBUILD_ENV_VAR,
    SYNC_ENV_VAR,
    NativeGroup,
    NativeManifest,
    env_flag_disabled,
    load_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_load_manifest_reads_declared_groups() -> None:
    """The real declaration parses into both groups, in order."""
    manifest = load_manifest(REPO_ROOT)
    assert manifest.enabled is True
    assert [group.name for group in manifest.groups] == ["cython-core", "navrules-pyo3"]
    cython = manifest.groups[0]
    assert cython.abi_scoped is True
    assert cython.autobuild is True
    assert cython.build_cwd == "packages/ai-parrot"
    assert cython.pair_sources == ["packages/ai-parrot/src/parrot/**/*.pyx"]


def test_load_manifest_empty_when_file_absent(tmp_path: Path) -> None:
    """An absent project file produces an enabled, empty manifest."""
    assert load_manifest(tmp_path) == NativeManifest(enabled=True, groups=[])


def test_load_manifest_empty_when_table_absent(tmp_path: Path) -> None:
    """A project without the declaration produces an empty manifest."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert load_manifest(tmp_path).groups == []


def test_load_manifest_rejects_malformed_table(tmp_path: Path) -> None:
    """Unknown group fields are reported as a caller-friendly ValueError."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.parrot.worktree]\nenabled = true\n"
        '[[tool.parrot.worktree.native_group]]\nname = "x"\nbogus_key = 1\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_manifest(tmp_path)


def test_group_defaults() -> None:
    """Optional group settings use the declaration defaults."""
    group = NativeGroup(name="g")
    assert group.required is True
    assert group.abi_scoped is False
    assert group.autobuild is False
    assert group.build == []
    assert group.build_cwd == "."
    assert group.build_timeout_s == 900
    assert group.manual_hint is None


def test_env_flag_disabled_only_on_explicit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a literal zero disables either environment-controlled behavior."""
    monkeypatch.delenv(SYNC_ENV_VAR, raising=False)
    assert env_flag_disabled(SYNC_ENV_VAR) is False
    monkeypatch.setenv(SYNC_ENV_VAR, "")
    assert env_flag_disabled(SYNC_ENV_VAR) is False
    monkeypatch.setenv(SYNC_ENV_VAR, "1")
    assert env_flag_disabled(SYNC_ENV_VAR) is False
    monkeypatch.setenv(AUTOBUILD_ENV_VAR, "0")
    assert env_flag_disabled(AUTOBUILD_ENV_VAR) is True
