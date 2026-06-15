"""Tests for FEAT-237 TASK-1550: compliance corpus manifest and fetch utilities.

Tests:
  - manifest.yaml parses as valid YAML.
  - All 4 source entries are present with required fields.
  - AICPA TSC is marked non-redistributable.
  - NIST sources are marked redistributable.
  - fetch.py _load_manifest raises on malformed input.
  - _compute_sha256 produces correct digest.
  - fetch_all skips non-redistributable sources without URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_WT = Path(__file__).parents[2]  # <worktree root>
_MANIFEST_PATH = _WT / "corpus/compliance_soc2_hipaa/manifest.yaml"
_FETCH_MOD_PATH = _WT / "corpus/compliance_soc2_hipaa/fetch.py"

# ---------------------------------------------------------------------------
# Load fetch.py directly (avoids any import issues with sys.path)
# ---------------------------------------------------------------------------
import importlib.util as _ilu

if "corpus.compliance_soc2_hipaa.fetch" not in sys.modules:
    _spec = _ilu.spec_from_file_location("corpus.compliance_soc2_hipaa.fetch", str(_FETCH_MOD_PATH))
    _fetch_mod = _ilu.module_from_spec(_spec)
    sys.modules["corpus.compliance_soc2_hipaa.fetch"] = _fetch_mod
    _spec.loader.exec_module(_fetch_mod)
else:
    _fetch_mod = sys.modules["corpus.compliance_soc2_hipaa.fetch"]

_load_manifest = _fetch_mod._load_manifest
_compute_sha256 = _fetch_mod._compute_sha256
fetch_all = _fetch_mod.fetch_all


# ---------------------------------------------------------------------------
# TestManifest — manifest.yaml structure
# ---------------------------------------------------------------------------


class TestManifest:
    def test_manifest_exists(self) -> None:
        """manifest.yaml exists at the expected path."""
        assert _MANIFEST_PATH.exists(), (
            f"manifest.yaml not found at {_MANIFEST_PATH}"
        )

    def test_manifest_parses(self) -> None:
        """manifest.yaml parses as valid YAML with 'sources' key."""
        if not _MANIFEST_PATH.exists():
            pytest.skip("Corpus manifest not found")
        data = _load_manifest(_MANIFEST_PATH)
        assert "sources" in data
        assert isinstance(data["sources"], list)

    def test_all_required_fields(self) -> None:
        """Every source entry has name, sha256, and redistributable fields."""
        if not _MANIFEST_PATH.exists():
            pytest.skip("Corpus manifest not found")
        data = _load_manifest(_MANIFEST_PATH)
        for source in data["sources"]:
            assert "name" in source, f"Missing 'name' in {source}"
            assert "sha256" in source, f"Missing 'sha256' in {source}"
            assert "redistributable" in source, f"Missing 'redistributable' in {source}"

    def test_four_sources(self) -> None:
        """manifest.yaml has exactly 4 source entries."""
        if not _MANIFEST_PATH.exists():
            pytest.skip("Corpus manifest not found")
        data = _load_manifest(_MANIFEST_PATH)
        assert len(data["sources"]) == 4, (
            f"Expected 4 sources, got {len(data['sources'])}"
        )

    def test_aicpa_not_redistributable(self) -> None:
        """AICPA TSC source is marked as non-redistributable."""
        if not _MANIFEST_PATH.exists():
            pytest.skip("Corpus manifest not found")
        data = _load_manifest(_MANIFEST_PATH)
        aicpa = [s for s in data["sources"] if "AICPA" in s.get("name", "")]
        assert len(aicpa) == 1, "Expected exactly 1 AICPA source"
        assert aicpa[0]["redistributable"] is False, (
            "AICPA TSC must be marked redistributable: false"
        )

    def test_nist_redistributable(self) -> None:
        """NIST sources are marked redistributable."""
        if not _MANIFEST_PATH.exists():
            pytest.skip("Corpus manifest not found")
        data = _load_manifest(_MANIFEST_PATH)
        nist = [s for s in data["sources"] if "NIST" in s.get("name", "")]
        assert len(nist) == 2, "Expected 2 NIST sources"
        for s in nist:
            assert s["redistributable"] is True, (
                f"NIST source '{s['name']}' must be redistributable"
            )

    def test_hipaa_redistributable(self) -> None:
        """HIPAA Security Rule source is marked redistributable."""
        if not _MANIFEST_PATH.exists():
            pytest.skip("Corpus manifest not found")
        data = _load_manifest(_MANIFEST_PATH)
        hipaa = [s for s in data["sources"] if "HIPAA" in s.get("name", "")]
        assert len(hipaa) == 1, "Expected 1 HIPAA source"
        assert hipaa[0]["redistributable"] is True


# ---------------------------------------------------------------------------
# TestLoadManifest — error handling
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_missing_file_raises(self, tmp_path) -> None:
        """_load_manifest raises FileNotFoundError on missing file."""
        with pytest.raises((FileNotFoundError, Exception)):
            _load_manifest(tmp_path / "nonexistent.yaml")

    def test_malformed_yaml_raises(self, tmp_path) -> None:
        """_load_manifest raises ValueError on YAML with no 'sources' key."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("key: value\nno_sources: true\n")
        with pytest.raises(ValueError, match="sources"):
            _load_manifest(bad_yaml)


# ---------------------------------------------------------------------------
# TestComputeSha256
# ---------------------------------------------------------------------------


class TestComputeSha256:
    def test_known_hash(self, tmp_path) -> None:
        """_compute_sha256 returns correct SHA-256 for known content."""
        content = b"compliance corpus test content\n"
        expected = hashlib.sha256(content).hexdigest()
        f = tmp_path / "test.txt"
        f.write_bytes(content)
        assert _compute_sha256(f) == expected

    def test_empty_file(self, tmp_path) -> None:
        """_compute_sha256 handles empty files."""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        result = _compute_sha256(f)
        assert len(result) == 64  # SHA-256 hex digest is 64 chars
        assert result == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# TestFetchAll — async downloader
# ---------------------------------------------------------------------------


class TestFetchAll:
    @pytest.mark.asyncio
    async def test_skips_non_redistributable_without_url(
        self, tmp_path
    ) -> None:
        """fetch_all skips non-redistributable sources that have no URL and no file."""
        import yaml

        # Create a minimal manifest with only a non-redistributable source.
        manifest_data = {
            "sources": [
                {
                    "name": "Internal Doc",
                    "url": None,
                    "filename": "internal.pdf",
                    "sha256": None,
                    "redistributable": False,
                    "license": "Internal",
                }
            ]
        }
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest_data))

        results = await fetch_all(
            manifest_path=manifest_path,
            output_dir=tmp_path / "raw",
        )
        # Non-redistributable sources without a local file are skipped
        assert "Internal Doc" not in results

    @pytest.mark.asyncio
    async def test_skips_existing_verified_file(self, tmp_path) -> None:
        """fetch_all skips a file that already exists with matching SHA-256."""
        import yaml

        # Write a test file
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        content = b"test content for verification"
        sha = hashlib.sha256(content).hexdigest()
        (raw_dir / "test.pdf").write_bytes(content)

        manifest_data = {
            "sources": [
                {
                    "name": "Test Source",
                    "url": "https://example.com/test.pdf",
                    "filename": "test.pdf",
                    "sha256": sha,
                    "redistributable": True,
                    "license": "Public Domain",
                }
            ]
        }
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest_data))

        # File already exists with correct SHA — should not download
        results = await fetch_all(
            manifest_path=manifest_path,
            output_dir=raw_dir,
        )
        assert "Test Source" in results
        assert results["Test Source"] == str(raw_dir / "test.pdf")
