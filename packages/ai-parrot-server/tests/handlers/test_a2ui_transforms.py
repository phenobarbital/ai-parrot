"""Tests for publish_transforms (FEAT-598 M9)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from parrot.handlers.a2ui_transforms import compute_sri, publish_transforms
from parrot.outputs.a2ui.linked.manifest import MANIFEST_KEY_ENV, load_manifest

KEY = "publish-test-key"


@pytest.fixture
def static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("parrot.conf.STATIC_DIR", tmp_path / "static")
    monkeypatch.setenv(MANIFEST_KEY_ENV, KEY)
    return tmp_path / "static"


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "group_by_day@1.0.0.js").write_text("export default (rows) => rows;\n", encoding="utf-8")
    return src


def _transforms_dir(static_dir: Path) -> Path:
    return static_dir / "a2ui" / "transforms"


def test_publish_writes_signed_manifest(static_dir: Path, source_dir: Path) -> None:
    published = publish_transforms(source_dir, key=KEY)
    assert load_manifest() == published  # TASK-3775 loader verifies the same bytes
    copied = _transforms_dir(static_dir) / "group_by_day@1.0.0.js"
    assert copied.exists()
    entry = published.entries["group_by_day@1.0.0"]
    assert entry.integrity == compute_sri(copied.read_bytes())
    assert entry.file == "group_by_day@1.0.0.js"
    assert entry.deprecated is False


def test_publish_keeps_existing_versions(static_dir: Path, source_dir: Path, tmp_path: Path) -> None:
    publish_transforms(source_dir, key=KEY)

    source_dir_2 = tmp_path / "src2"
    source_dir_2.mkdir()
    (source_dir_2 / "group_by_day@1.1.0.js").write_text(
        "export default (rows) => rows.slice().reverse();\n", encoding="utf-8"
    )

    published = publish_transforms(source_dir_2, key=KEY)

    assert set(published.entries) == {"group_by_day@1.0.0", "group_by_day@1.1.0"}
    assert (_transforms_dir(static_dir) / "group_by_day@1.0.0.js").exists()
    assert (_transforms_dir(static_dir) / "group_by_day@1.1.0.js").exists()
    assert load_manifest() == published


def test_publish_refuses_changed_version(static_dir: Path, source_dir: Path) -> None:
    publish_transforms(source_dir, key=KEY)

    (source_dir / "group_by_day@1.0.0.js").write_text("export default (rows) => rows.slice();\n", encoding="utf-8")

    with pytest.raises(ValueError):
        publish_transforms(source_dir, key=KEY)


def test_publish_rejects_tampered_manifest(static_dir: Path, source_dir: Path) -> None:
    publish_transforms(source_dir, key=KEY)
    manifest_path = _transforms_dir(static_dir) / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["entries"]["group_by_day@1.0.0"]["integrity"] = "sha384-" + "B" * 64
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError):
        publish_transforms(source_dir, key=KEY)


def test_publish_skips_non_versioned_files(static_dir: Path, source_dir: Path) -> None:
    (source_dir / "helper.js").write_text("export const helper = 1;\n", encoding="utf-8")

    published = publish_transforms(source_dir, key=KEY)

    assert "helper" not in published.entries
    assert not (_transforms_dir(static_dir) / "helper.js").exists()


def test_publish_requires_key(static_dir: Path, source_dir: Path) -> None:
    with pytest.raises(ValueError):
        publish_transforms(source_dir, key="")


def test_compute_sri_format() -> None:
    data = b"hello world"
    sri = compute_sri(data)
    assert sri == "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")
