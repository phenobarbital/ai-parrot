"""Unit tests for scripts/odoo_agent/build_odoo_pageindex.py (FEAT-240 TASK-1573).

These tests verify:
- Per-version tree creation (odoo_16, odoo_18, odoo_19).
- Idempotency: existing trees are skipped on re-run.
- import_pdf is called once per discovered PDF.
- ``no_pdf`` outcome when no PDF exists in the version directory.
- ``--force`` flag triggers tree deletion + rebuild.
- ``--dry-run`` flag skips actual ingestion.

All PageIndexToolkit calls are mocked so no real LLM / PDF is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add the scripts directory to sys.path so we can import build_odoo_pageindex
_SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    / "scripts"
    / "odoo_agent"
)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from build_odoo_pageindex import VERSION_MAP, _find_pdf, build_pageindex, main  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_pdf(version_dir: Path, name: str = "docs.pdf") -> Path:
    """Create a dummy PDF file inside a version directory."""
    version_dir.mkdir(parents=True, exist_ok=True)
    pdf = version_dir / name
    pdf.write_bytes(b"%PDF-1.4 fake")
    return pdf


# ── _find_pdf ─────────────────────────────────────────────────────────────────


def test_find_pdf_returns_pdf_when_present(tmp_path):
    """_find_pdf returns the first PDF in the directory."""
    version_dir = tmp_path / "16.0"
    pdf = _make_pdf(version_dir, "odoo_16_docs.pdf")
    found = _find_pdf(version_dir)
    assert found == pdf


def test_find_pdf_returns_none_when_no_pdf(tmp_path):
    """_find_pdf returns None when no PDF exists."""
    version_dir = tmp_path / "16.0"
    version_dir.mkdir()
    assert _find_pdf(version_dir) is None


def test_find_pdf_returns_none_when_dir_missing(tmp_path):
    """_find_pdf returns None when the directory does not exist."""
    assert _find_pdf(tmp_path / "nonexistent") is None


# ── build_pageindex: per-version trees ────────────────────────────────────────


@pytest.mark.asyncio
async def test_creates_per_version_trees(tmp_path):
    """build_pageindex creates odoo_16, odoo_18, odoo_19 trees."""
    # Create dummy PDFs in version subdirectories
    for tree_name, ver in VERSION_MAP.items():
        _make_pdf(tmp_path / ver)

    with (
        patch("build_odoo_pageindex.GoogleGenAIClient") as mock_client_cls,
        patch("build_odoo_pageindex.PageIndexLLMAdapter") as mock_adapter_cls,
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        mock_toolkit.list_trees = AsyncMock(return_value=[])
        mock_toolkit.create_tree = AsyncMock(return_value={})
        mock_toolkit.import_pdf = AsyncMock(
            return_value={"tree_name": "odoo_16", "new_node_ids": ["n1", "n2"]}
        )
        mock_toolkit_cls.return_value = mock_toolkit

        outcomes = await build_pageindex(
            storage_dir=str(tmp_path),
            versions=list(VERSION_MAP.keys()),
        )

    assert outcomes == {"odoo_16": "built", "odoo_18": "built", "odoo_19": "built"}
    # create_tree called once per version
    assert mock_toolkit.create_tree.call_count == 3
    # import_pdf called once per version PDF
    assert mock_toolkit.import_pdf.call_count == 3


@pytest.mark.asyncio
async def test_import_pdf_called_with_with_summaries(tmp_path):
    """import_pdf is always called with with_summaries=True."""
    _make_pdf(tmp_path / "18.0")

    with (
        patch("build_odoo_pageindex.GoogleGenAIClient"),
        patch("build_odoo_pageindex.PageIndexLLMAdapter"),
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        mock_toolkit.list_trees = AsyncMock(return_value=[])
        mock_toolkit.create_tree = AsyncMock(return_value={})
        mock_toolkit.import_pdf = AsyncMock(
            return_value={"tree_name": "odoo_18", "new_node_ids": []}
        )
        mock_toolkit_cls.return_value = mock_toolkit

        await build_pageindex(
            storage_dir=str(tmp_path),
            versions=["odoo_18"],
        )

    call_kwargs = mock_toolkit.import_pdf.call_args
    assert call_kwargs.kwargs.get("with_summaries") is True or (
        len(call_kwargs.args) > 2 and call_kwargs.args[2]
    )


# ── Idempotency ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_rerun_skips_existing_trees(tmp_path):
    """On rerun, existing trees are skipped (import_pdf not called again)."""
    for ver in VERSION_MAP.values():
        _make_pdf(tmp_path / ver)

    with (
        patch("build_odoo_pageindex.GoogleGenAIClient"),
        patch("build_odoo_pageindex.PageIndexLLMAdapter"),
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        # Simulate all three trees already existing
        mock_toolkit.list_trees = AsyncMock(return_value=list(VERSION_MAP.keys()))
        mock_toolkit.create_tree = AsyncMock()
        mock_toolkit.import_pdf = AsyncMock()
        mock_toolkit_cls.return_value = mock_toolkit

        outcomes = await build_pageindex(
            storage_dir=str(tmp_path),
            versions=list(VERSION_MAP.keys()),
        )

    assert all(v == "skipped" for v in outcomes.values())
    mock_toolkit.import_pdf.assert_not_called()
    mock_toolkit.create_tree.assert_not_called()


@pytest.mark.asyncio
async def test_force_rebuilds_existing_tree(tmp_path):
    """--force causes an existing tree to be deleted and rebuilt."""
    _make_pdf(tmp_path / "16.0")

    with (
        patch("build_odoo_pageindex.GoogleGenAIClient"),
        patch("build_odoo_pageindex.PageIndexLLMAdapter"),
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        # Simulate odoo_16 already existing
        list_trees_returns = [["odoo_16"], []]  # first call: exists; after delete: empty
        mock_toolkit.list_trees = AsyncMock(side_effect=list_trees_returns)
        mock_toolkit.delete_tree = AsyncMock(return_value={})
        mock_toolkit.create_tree = AsyncMock(return_value={})
        mock_toolkit.import_pdf = AsyncMock(
            return_value={"tree_name": "odoo_16", "new_node_ids": []}
        )
        mock_toolkit_cls.return_value = mock_toolkit

        outcomes = await build_pageindex(
            storage_dir=str(tmp_path),
            versions=["odoo_16"],
            force=True,
        )

    assert outcomes["odoo_16"] == "built"
    mock_toolkit.delete_tree.assert_called_once_with("odoo_16")
    mock_toolkit.import_pdf.assert_called_once()


# ── no_pdf outcome ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_pdf_outcome_when_directory_empty(tmp_path):
    """When version dir has no PDF, outcome is 'no_pdf' and import is skipped."""
    # Create empty version directories (no PDFs)
    for ver in VERSION_MAP.values():
        (tmp_path / ver).mkdir(parents=True, exist_ok=True)

    with (
        patch("build_odoo_pageindex.GoogleGenAIClient"),
        patch("build_odoo_pageindex.PageIndexLLMAdapter"),
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        mock_toolkit.list_trees = AsyncMock(return_value=[])
        mock_toolkit_cls.return_value = mock_toolkit

        outcomes = await build_pageindex(
            storage_dir=str(tmp_path),
            versions=list(VERSION_MAP.keys()),
        )

    assert all(v == "no_pdf" for v in outcomes.values())


# ── dry_run ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_does_not_call_import(tmp_path):
    """--dry-run logs what would happen but never calls import_pdf."""
    for ver in VERSION_MAP.values():
        _make_pdf(tmp_path / ver)

    with (
        patch("build_odoo_pageindex.GoogleGenAIClient"),
        patch("build_odoo_pageindex.PageIndexLLMAdapter"),
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        mock_toolkit.list_trees = AsyncMock(return_value=[])
        mock_toolkit.import_pdf = AsyncMock()
        mock_toolkit_cls.return_value = mock_toolkit

        outcomes = await build_pageindex(
            storage_dir=str(tmp_path),
            versions=list(VERSION_MAP.keys()),
            dry_run=True,
        )

    assert all(v == "dry_run" for v in outcomes.values())
    mock_toolkit.import_pdf.assert_not_called()


# ── main() CLI ────────────────────────────────────────────────────────────────


def test_main_returns_zero_when_all_skipped(tmp_path):
    """main() returns exit code 0 when all trees already exist (skipped)."""
    for ver in VERSION_MAP.values():
        _make_pdf(tmp_path / ver)

    with (
        patch("build_odoo_pageindex.GoogleGenAIClient"),
        patch("build_odoo_pageindex.PageIndexLLMAdapter"),
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        mock_toolkit.list_trees = AsyncMock(return_value=list(VERSION_MAP.keys()))
        mock_toolkit_cls.return_value = mock_toolkit

        rc = main(["--storage-dir", str(tmp_path)])

    assert rc == 0


def test_main_returns_one_when_pdf_missing(tmp_path):
    """main() returns exit code 1 when a PDF is missing."""
    # Empty storage_dir — no PDFs anywhere
    with (
        patch("build_odoo_pageindex.GoogleGenAIClient"),
        patch("build_odoo_pageindex.PageIndexLLMAdapter"),
        patch("build_odoo_pageindex.PageIndexToolkit") as mock_toolkit_cls,
    ):
        mock_toolkit = AsyncMock()
        mock_toolkit.list_trees = AsyncMock(return_value=[])
        mock_toolkit_cls.return_value = mock_toolkit

        rc = main(["--storage-dir", str(tmp_path)])

    assert rc == 1
