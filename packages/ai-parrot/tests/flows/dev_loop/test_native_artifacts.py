"""Tests for parrot.flows.dev_loop.native_artifacts (FEAT-722)."""

from __future__ import annotations

import sysconfig
from pathlib import Path

import pytest

from parrot.flows.dev_loop.native_artifacts import (
    AUTOBUILD_ENV_VAR,
    SYNC_ENV_VAR,
    NativeGroup,
    NativeManifest,
    env_flag_disabled,
    load_manifest,
    main_checkout_root,
    missing_artifacts,
    sync_native_artifacts,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
EXT = sysconfig.get_config_var("EXT_SUFFIX") or ".so"


@pytest.fixture
def fake_main_root(tmp_path: Path) -> Path:
    """Return a synthetic main checkout with a paired Cython extension."""
    package = tmp_path / "main" / "packages" / "demo" / "src" / "demo"
    package.mkdir(parents=True)
    (package / "fast.pyx").write_text("# cython\n", encoding="utf-8")
    (package / f"fast{EXT}").write_bytes(b"\x7fELF-not-really")
    return tmp_path / "main"


@pytest.fixture
def stub_manifest() -> NativeManifest:
    """Return a declaration for the synthetic demo extension."""
    return NativeManifest(
        enabled=True,
        groups=[
            NativeGroup(
                name="demo",
                copy_globs=["packages/demo/src/**/*.so"],
                pair_sources=["packages/demo/src/**/*.pyx"],
                abi_scoped=True,
                manual_hint="make demo",
            )
        ],
    )


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
        "[tool.parrot.worktree]\nenabled = true\n" '[[tool.parrot.worktree.native_group]]\nname = "x"\nbogus_key = 1\n',
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


def test_sync_copies_declared_artifacts(fake_main_root: Path, stub_manifest: NativeManifest, tmp_path: Path) -> None:
    """Sync recreates declared artifact paths under an initially empty target."""
    target = tmp_path / "wt"
    report = sync_native_artifacts(main_root=fake_main_root, target=target, manifest=stub_manifest)
    expected = f"packages/demo/src/demo/fast{EXT}"
    assert report.enabled is True
    assert report.copied == [expected]
    assert (target / expected).is_file()
    assert report.missing == []


def test_sync_is_idempotent(fake_main_root: Path, stub_manifest: NativeManifest, tmp_path: Path) -> None:
    """An unchanged source is skipped without altering the copied file mtime."""
    target = tmp_path / "wt"
    sync_native_artifacts(main_root=fake_main_root, target=target, manifest=stub_manifest)
    destination = target / f"packages/demo/src/demo/fast{EXT}"
    before = destination.stat().st_mtime_ns
    second = sync_native_artifacts(main_root=fake_main_root, target=target, manifest=stub_manifest)
    assert second.copied == []
    assert second.skipped == [f"packages/demo/src/demo/fast{EXT}"]
    assert destination.stat().st_mtime_ns == before


def test_sync_disabled_by_env(
    fake_main_root: Path, stub_manifest: NativeManifest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit sync disable flag returns an empty disabled report."""
    monkeypatch.setenv(SYNC_ENV_VAR, "0")
    report = sync_native_artifacts(main_root=fake_main_root, target=tmp_path / "wt", manifest=stub_manifest)
    assert report.enabled is False
    assert report.copied == []


def test_sync_disabled_by_manifest(fake_main_root: Path, stub_manifest: NativeManifest, tmp_path: Path) -> None:
    """A disabled manifest bypasses copying even when artifacts are available."""
    stub_manifest.enabled = False
    report = sync_native_artifacts(main_root=fake_main_root, target=tmp_path / "wt", manifest=stub_manifest)
    assert report.enabled is False
    assert report.copied == []


def test_missing_required_group_without_matches() -> None:
    """A required group without source pairs reports its unmatched declaration."""
    manifest = NativeManifest(groups=[NativeGroup(name="missing", copy_globs=["packages/missing/**/*.so"])])
    missing = missing_artifacts(Path("/nonexistent"), manifest)
    assert len(missing) == 1
    assert missing[0].reason == "no_match"
    assert missing[0].detail == "packages/missing/**/*.so"


def test_missing_unpaired_source_detected(fake_main_root: Path, stub_manifest: NativeManifest) -> None:
    """A source lacking every sibling extension is reported as unpaired."""
    (fake_main_root / "packages/demo/src/demo" / f"fast{EXT}").unlink()
    missing = missing_artifacts(fake_main_root, stub_manifest)
    assert len(missing) == 1
    assert missing[0].reason == "unpaired_source"
    assert missing[0].detail == "packages/demo/src/demo/fast.pyx"


def test_missing_abi_mismatch_detected(fake_main_root: Path, stub_manifest: NativeManifest) -> None:
    """A paired extension for another interpreter ABI is reported distinctly."""
    package = fake_main_root / "packages/demo/src/demo"
    (package / f"fast{EXT}").rename(package / "fast.cpython-999-foreign.so")
    missing = missing_artifacts(fake_main_root, stub_manifest)
    assert len(missing) == 1
    assert missing[0].reason == "abi_mismatch"


def test_main_checkout_root_on_non_git_dir(tmp_path: Path) -> None:
    """A directory outside a Git checkout has no primary checkout root."""
    assert main_checkout_root(tmp_path) is None


def test_missing_never_raises_and_warns_with_hint(
    fake_main_root: Path, stub_manifest: NativeManifest, tmp_path: Path
) -> None:
    """A missing extension remains a report entry and retains its manual hint."""
    (fake_main_root / "packages/demo/src/demo" / f"fast{EXT}").unlink()
    report = sync_native_artifacts(main_root=fake_main_root, target=tmp_path / "wt", manifest=stub_manifest)
    assert report.missing
    assert any("make demo" in warning for warning in report.warnings)
