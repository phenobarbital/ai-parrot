"""Tests for the signed transforms manifest (FEAT-598 M9)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.linked.manifest import (
    MANIFEST_KEY_ENV,
    ManifestEntry,
    TransformManifest,
    load_manifest,
    resolve_ref,
    sign_entries,
)

KEY = "test-manifest-key"
SRI = "sha384-" + "A" * 64


@pytest.fixture
def manifest_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Signed manifest with group_by_day@1.0.0 and a deprecated group_by_day@0.9.0."""
    monkeypatch.setenv(MANIFEST_KEY_ENV, KEY)
    entries = {
        "group_by_day@1.0.0": ManifestEntry(file="group_by_day@1.0.0.js", integrity=SRI),
        "group_by_day@0.9.0": ManifestEntry(file="group_by_day@0.9.0.js", integrity=SRI, deprecated=True),
    }
    manifest = TransformManifest(entries=entries, signature=sign_entries(entries, KEY))
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return path


def test_manifest_signature_verified(manifest_file: Path) -> None:
    assert load_manifest(manifest_file) is not None


def test_manifest_tampered_returns_none(manifest_file: Path) -> None:
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    data["entries"]["group_by_day@1.0.0"]["integrity"] = "sha384-" + "B" * 64
    manifest_file.write_text(json.dumps(data), encoding="utf-8")
    assert load_manifest(manifest_file) is None


def test_manifest_missing_key_returns_none(manifest_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MANIFEST_KEY_ENV, raising=False)
    assert load_manifest(manifest_file) is None


def test_manifest_missing_file_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MANIFEST_KEY_ENV, KEY)
    assert load_manifest(tmp_path / "does-not-exist.json") is None


def test_manifest_deprecated_warns(manifest_file: Path, caplog: pytest.LogCaptureFixture) -> None:
    manifest = load_manifest(manifest_file)
    assert manifest is not None
    with caplog.at_level(logging.WARNING):
        ref = resolve_ref("group_by_day@0.9.0", manifest)
    assert ref.name == "group_by_day@0.9.0"
    assert any("deprecated" in record.message for record in caplog.records)


def test_resolve_ref_unknown(manifest_file: Path) -> None:
    manifest = load_manifest(manifest_file)
    assert manifest is not None
    with pytest.raises(KeyError):
        resolve_ref("does_not_exist@1.0.0", manifest)


@pytest.mark.parametrize("bad_file", ["https://cdn.example.com/group_by_day@1.0.0.js", "../x.js", "a/b.js"])
def test_manifest_entry_rejects_url(bad_file: str) -> None:
    with pytest.raises(ValidationError):
        TransformManifest(
            entries={"group_by_day@1.0.0": ManifestEntry(file=bad_file, integrity=SRI)},
            signature="deadbeef",
        )


def test_default_path_uses_static_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("parrot.conf.STATIC_DIR", tmp_path)
    from parrot.outputs.a2ui.linked.manifest import default_manifest_path

    assert default_manifest_path() == tmp_path / "a2ui" / "transforms" / "manifest.json"
