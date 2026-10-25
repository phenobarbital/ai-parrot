"""Tests for parrot.flows.dev_loop.native_artifacts (FEAT-722)."""

from __future__ import annotations

import sys
import sysconfig
import threading
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


def _missing_main_root(tmp_path: Path) -> Path:
    """Return a synthetic checkout with a source but no compiled artifact."""
    package = tmp_path / "main" / "packages" / "demo" / "src" / "demo"
    package.mkdir(parents=True)
    (package / "built.pyx").write_text("# cython\n", encoding="utf-8")
    return tmp_path / "main"


def _counting_build_group(main_root: Path, counter: Path) -> NativeGroup:
    """Return a build group whose argv records one build and creates an artifact."""
    script = main_root / "fake_build.py"
    script.write_text(
        "import pathlib, sys\n"
        "counter = pathlib.Path(sys.argv[1])\n"
        "counter.write_text(counter.read_text() + 'x' if counter.exists() else 'x')\n"
        "artifact = pathlib.Path(sys.argv[2])\n"
        "artifact.parent.mkdir(parents=True, exist_ok=True)\n"
        "artifact.write_bytes(b'ELF')\n",
        encoding="utf-8",
    )
    return NativeGroup(
        name="stub",
        copy_globs=["packages/demo/src/demo/*.so"],
        pair_sources=["packages/demo/src/demo/*.pyx"],
        autobuild=True,
        build=["{python}", "fake_build.py", str(counter), f"packages/demo/src/demo/built{EXT}"],
        build_cwd=".",
        build_timeout_s=60,
        manual_hint="run it yourself",
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


def test_autobuild_runs_declared_argv(tmp_path: Path) -> None:
    """A missing artifact is built, then copied into the target worktree."""
    main_root = _missing_main_root(tmp_path)
    counter = tmp_path / "counter"
    manifest = NativeManifest(groups=[_counting_build_group(main_root, counter)])

    report = sync_native_artifacts(main_root=main_root, target=tmp_path / "wt", manifest=manifest)

    artifact = f"packages/demo/src/demo/built{EXT}"
    assert report.built == ["stub"]
    assert report.copied == [artifact]
    assert report.missing == []
    assert counter.read_text(encoding="utf-8") == "x"


def test_autobuild_failure_is_a_warning(tmp_path: Path) -> None:
    """A failed argv preserves the missing entry and provides the manual command."""
    main_root = _missing_main_root(tmp_path)
    group = NativeGroup(
        name="failing",
        copy_globs=["packages/demo/src/demo/*.so"],
        pair_sources=["packages/demo/src/demo/*.pyx"],
        autobuild=True,
        build=["{python}", "-c", "import sys; sys.stderr.write('failed build'); sys.exit(7)"],
        manual_hint="repair failing manually",
    )

    report = sync_native_artifacts(
        main_root=main_root,
        target=tmp_path / "wt",
        manifest=NativeManifest(groups=[group]),
    )

    assert report.missing
    assert any("status 7" in warning and "repair failing manually" in warning for warning in report.warnings)


def test_autobuild_timeout_is_a_warning(tmp_path: Path) -> None:
    """A timed-out argv leaves the artifact missing and reports the manual command."""
    main_root = _missing_main_root(tmp_path)
    group = NativeGroup(
        name="timed-out",
        copy_globs=["packages/demo/src/demo/*.so"],
        pair_sources=["packages/demo/src/demo/*.pyx"],
        autobuild=True,
        build=["{python}", "-c", "import time; time.sleep(2)"],
        build_timeout_s=1,
        manual_hint="repair timeout manually",
    )

    report = sync_native_artifacts(
        main_root=main_root,
        target=tmp_path / "wt",
        manifest=NativeManifest(groups=[group]),
    )

    assert report.missing
    assert any("timed out" in warning and "repair timeout manually" in warning for warning in report.warnings)


def test_autobuild_skipped_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All explicit autobuild disable mechanisms avoid starting the build argv."""
    main_root = _missing_main_root(tmp_path)
    counter = tmp_path / "counter"
    group = _counting_build_group(main_root, counter)

    monkeypatch.setenv(AUTOBUILD_ENV_VAR, "0")
    env_disabled = sync_native_artifacts(
        main_root=main_root, target=tmp_path / "env", manifest=NativeManifest(groups=[group])
    )
    assert not counter.exists()
    assert any("run it yourself" in warning for warning in env_disabled.warnings)

    monkeypatch.delenv(AUTOBUILD_ENV_VAR)
    caller_disabled = sync_native_artifacts(
        main_root=main_root,
        target=tmp_path / "caller",
        manifest=NativeManifest(groups=[group]),
        autobuild=False,
    )
    assert not counter.exists()
    assert any("run it yourself" in warning for warning in caller_disabled.warnings)

    group_disabled = group.model_copy(update={"autobuild": False})
    group_disabled_report = sync_native_artifacts(
        main_root=main_root, target=tmp_path / "group", manifest=NativeManifest(groups=[group_disabled])
    )
    assert not counter.exists()
    assert any("run it yourself" in warning for warning in group_disabled_report.warnings)

    no_build = group.model_copy(update={"build": []})
    no_build_report = sync_native_artifacts(
        main_root=main_root, target=tmp_path / "empty", manifest=NativeManifest(groups=[no_build])
    )
    assert not counter.exists()
    assert any("run it yourself" in warning for warning in no_build_report.warnings)


def test_autobuild_lock_serializes_builds(tmp_path: Path) -> None:
    """Concurrent syncs share one lock and execute the declared argv once."""
    main_root = _missing_main_root(tmp_path)
    counter = tmp_path / "counter"
    manifest = NativeManifest(groups=[_counting_build_group(main_root, counter)])
    start = threading.Barrier(2)
    reports: list[object] = []

    def run_sync(target: Path) -> None:
        start.wait()
        reports.append(sync_native_artifacts(main_root=main_root, target=target, manifest=manifest))

    first = threading.Thread(target=run_sync, args=(tmp_path / "first",))
    second = threading.Thread(target=run_sync, args=(tmp_path / "second",))
    first.start()
    second.start()
    first.join()
    second.join()

    assert len(reports) == 2
    assert counter.read_text(encoding="utf-8") == "x"


def test_build_lock_propagates_caller_errors_once(tmp_path: Path) -> None:
    """An OSError raised inside the lock body propagates as itself.

    `_build_lock`'s `except OSError` arms must exclude the `yield`. If they wrapped
    it, the caller's error would be thrown back in at the yield point, the generator
    would yield a second time, and contextlib would replace the real error with
    `RuntimeError: generator didn't stop after throw()` — hiding the cause and
    making `build_missing`'s warning misleading.
    """
    from parrot.flows.dev_loop.native_artifacts import _build_lock

    group = NativeGroup(name="stub", build_timeout_s=5)
    with pytest.raises(OSError, match="caller exploded"):
        with _build_lock(tmp_path, group) as acquired:
            assert acquired is True
            raise OSError("caller exploded")


def test_python_placeholder_is_substituted(tmp_path: Path) -> None:
    """The placeholder invokes the running interpreter rather than a shell command."""
    main_root = _missing_main_root(tmp_path)
    executable = tmp_path / "executable"
    artifact = f"packages/demo/src/demo/built{EXT}"
    script = main_root / "capture_python.py"
    script.write_text(
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(sys.executable)\n"
        "artifact = pathlib.Path(sys.argv[2])\n"
        "artifact.parent.mkdir(parents=True, exist_ok=True)\n"
        "artifact.write_bytes(b'ELF')\n",
        encoding="utf-8",
    )
    group = NativeGroup(
        name="interpreter",
        copy_globs=["packages/demo/src/demo/*.so"],
        pair_sources=["packages/demo/src/demo/*.pyx"],
        autobuild=True,
        build=["{python}", "capture_python.py", str(executable), artifact],
        manual_hint="run capture manually",
    )

    report = sync_native_artifacts(
        main_root=main_root,
        target=tmp_path / "wt",
        manifest=NativeManifest(groups=[group]),
    )

    assert report.built == ["interpreter"]
    assert executable.read_text(encoding="utf-8") == sys.executable


def test_matches_skips_symlinks_and_outside_files(tmp_path):
    """FEAT-722 review: a symlinked artifact is never copied."""
    from parrot.flows.dev_loop.native_artifacts import _matches

    root = tmp_path / "main"
    root.mkdir()
    outside = tmp_path / "secret.so"
    outside.write_bytes(b"x")
    (root / "real.so").write_bytes(b"y")
    (root / "link.so").symlink_to(outside)
    assert [p.name for p in _matches(root, ["*.so"])] == ["real.so"]
