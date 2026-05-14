"""Integration tests for scripts/gen_frontend_docs.py — FEAT-170."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


# Path to the script under test
_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "gen_frontend_docs.py"
)


def test_script_exists() -> None:
    """The gen_frontend_docs.py script must exist."""
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"


def test_script_generates_output(tmp_path: Path) -> None:
    """Running the script with --out must create the Markdown file."""
    out = tmp_path / "rest-field.md"
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script exited with {result.returncode}:\n{result.stderr}"
    assert out.exists(), "Output file was not created"


def test_output_mentions_field_type_rest(tmp_path: Path) -> None:
    """Generated output must mention FieldType.REST."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8")
    assert "FieldType.REST" in content


def test_output_mentions_all_three_modes(tmp_path: Path) -> None:
    """Generated output must cover all three modes: remote, internal, callback."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8")
    assert "remote" in content
    assert "internal" in content
    assert "callback" in content


def test_output_mentions_blob_ref(tmp_path: Path) -> None:
    """Generated output must mention blob_ref (response envelope key)."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8")
    assert "blob_ref" in content


def test_output_mentions_planogram(tmp_path: Path) -> None:
    """Generated output must include the planogram worked example."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8").lower()
    assert "planogram" in content


def test_output_is_idempotent(tmp_path: Path) -> None:
    """Running the script twice must produce identical output."""
    out1 = tmp_path / "rest-field-1.md"
    out2 = tmp_path / "rest-field-2.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out1)], check=True)
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out2)], check=True)
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_output_mentions_upload_endpoint(tmp_path: Path) -> None:
    """Generated output must document the upload endpoint URL template."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8")
    assert "upload" in content.lower()
    assert "form_id" in content
    assert "field_id" in content


def test_output_mentions_error_codes(tmp_path: Path) -> None:
    """Generated output must document HTTP error codes 400, 413, 415."""
    out = tmp_path / "rest-field.md"
    subprocess.run([sys.executable, str(_SCRIPT), "--out", str(out)], check=True)
    content = out.read_text(encoding="utf-8")
    assert "400" in content
    assert "413" in content
    assert "415" in content
