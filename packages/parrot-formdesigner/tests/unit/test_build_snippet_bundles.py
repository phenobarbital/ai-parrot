"""Unit tests for build_snippet_bundles.py — FEAT-459 / TASK-3174.

All tests use a FAKE `esbuild` (a shell script placed on PATH via
monkeypatch/tmp_path) — no real esbuild binary is required.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from scripts.build_snippet_bundles import EsbuildNotFoundError, _compile_one


def _write_bundle(root: Path, name: str, *, with_ts: bool = True) -> Path:
    bundle_dir = root / name
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "handler_ref": f"{name}.onBeforeSubmit",
                "event": "onBeforeSubmit",
                "python_sha256": "a" * 64,
                "manifest": {"tier": "pure"},
            }
        )
    )
    (bundle_dir / "run.py").write_text("def run(ctx): return {}")
    if with_ts:
        (bundle_dir / "client.ts").write_text("export function run() { return []; }")
    return bundle_dir


@pytest.fixture
def fake_esbuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal fake `esbuild` CLI: echoes a fixed JS string to stdout."""
    fake_bin_dir = tmp_path / "fakebin"
    fake_bin_dir.mkdir()
    fake_esbuild_path = fake_bin_dir / "esbuild"
    fake_esbuild_path.write_text("#!/bin/sh\necho '(function(){return [];})();'\n")
    fake_esbuild_path.chmod(fake_esbuild_path.stat().st_mode | stat.S_IEXEC)

    # Prepend the fake bin dir to PATH - must capture original before monkeypatching
    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{fake_bin_dir}{os.pathsep}{original_path}")

    return fake_esbuild_path


def test_skips_bundle_without_client_ts(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path, "server_only", with_ts=False)
    changed = _compile_one(bundle_dir, check_only=False)
    assert changed is False
    assert not (bundle_dir / "client.js").exists()


def test_raises_when_esbuild_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    bundle_dir = _write_bundle(tmp_path, "needs_ts", with_ts=True)
    with pytest.raises(EsbuildNotFoundError):
        _compile_one(bundle_dir, check_only=False)


def test_compile_writes_client_js_and_updates_hash(tmp_path: Path, fake_esbuild: Path) -> None:
    bundle_dir = _write_bundle(tmp_path, "with_client", with_ts=True)

    changed = _compile_one(bundle_dir, check_only=False)
    assert changed is True

    client_js_path = bundle_dir / "client.js"
    assert client_js_path.exists()
    client_js_content = client_js_path.read_text()
    assert client_js_content == "(function(){return [];})();\n"

    # Verify manifest.json was updated with the correct hash
    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    expected_hash = hashlib.sha256(client_js_content.encode("utf-8")).hexdigest()
    assert manifest["client_sha256"] == expected_hash


def test_check_mode_does_not_write(tmp_path: Path, fake_esbuild: Path) -> None:
    bundle_dir = _write_bundle(tmp_path, "check_mode_test", with_ts=True)

    # In check mode, should NOT create client.js
    changed = _compile_one(bundle_dir, check_only=True)
    assert changed is True  # indicates "would change"

    client_js_path = bundle_dir / "client.js"
    assert not client_js_path.exists()  # Should NOT be created in check mode


def test_idempotent_run_no_change(tmp_path: Path, fake_esbuild: Path) -> None:
    """Running twice on unchanged sources should not report changes."""
    bundle_dir = _write_bundle(tmp_path, "idempotent_test", with_ts=True)

    # First run
    changed1 = _compile_one(bundle_dir, check_only=False)
    assert changed1 is True

    # Second run - should not report changes
    changed2 = _compile_one(bundle_dir, check_only=False)
    assert changed2 is False

    # Verify content is still correct
    client_js_path = bundle_dir / "client.js"
    assert client_js_path.read_text() == "(function(){return [];})();\n"