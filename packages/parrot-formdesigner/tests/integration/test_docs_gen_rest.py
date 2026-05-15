"""Integration tests for gen_frontend_docs.py (FEAT-170 / TASK-1172)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "gen_frontend_docs.py"
)


def test_script_exists():
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"


def test_frontend_docs_generated(tmp_path):
    """Running the script produces a Markdown file with required content."""
    out = tmp_path / "rest-field.md"
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script failed:\n{result.stderr}"
    assert out.exists(), "Output file was not created"

    content = out.read_text(encoding="utf-8")

    assert "FieldType.REST" in content
    assert "callback" in content
    assert "remote" in content
    assert "internal" in content
    assert "blob_ref" in content
    assert "planogram" in content.lower()


def test_docs_idempotent(tmp_path):
    """Running the script twice produces identical output."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    first = out.read_text(encoding="utf-8")

    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    second = out.read_text(encoding="utf-8")

    assert first == second


def test_response_envelope_keys_present(tmp_path):
    """All envelope fields from RestFieldResult appear in the doc."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8")

    for key in ("success", "answer", "raw_value", "blob_ref", "display", "warnings", "error"):
        assert key in content, f"Missing envelope key: {key}"


def test_upload_endpoint_contract_present(tmp_path):
    """Upload endpoint URL template and headers are documented."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8")

    assert "/upload" in content
    assert "X-Parrot-Prior-Blob-Ref" in content
    assert "multipart" in content.lower()
