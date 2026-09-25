"""Fixtures for the manuals suites (FEAT-601)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from .._support.adapter import FakeAdapter, FakeIndexer
from .._support.files import FakeFileManager
from .._support.graph import FakeGraphStore
from .._support.pdfs import build_image_only_pdf, build_manual_pdf, build_manual_pdf_rev_b

FROZEN_NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def frozen_now() -> datetime:
    """Return the suite's deterministic clock value."""
    return FROZEN_NOW


@pytest.fixture()
def manual_pdf(tmp_path: Path) -> Path:
    """Build the revision-A manual PDF."""
    pytest.importorskip("pymupdf")
    return build_manual_pdf(tmp_path / "manuals" / "model-x-rev-a.pdf")


@pytest.fixture()
def manual_pdf_rev_b(tmp_path: Path) -> Path:
    """Build the revision-B manual PDF."""
    pytest.importorskip("pymupdf")
    return build_manual_pdf_rev_b(tmp_path / "manuals" / "model-x-rev-b.pdf")


@pytest.fixture()
def image_only_pdf(tmp_path: Path) -> Path:
    """Build an image-only PDF."""
    pytest.importorskip("pymupdf")
    return build_image_only_pdf(tmp_path / "manuals" / "image-only.pdf")


@pytest.fixture()
def fake_graph_store() -> FakeGraphStore:
    """Return an empty graph-store double."""
    return FakeGraphStore()


@pytest.fixture()
def fake_adapter() -> FakeAdapter:
    """Return an empty scripted adapter."""
    return FakeAdapter()


@pytest.fixture()
def fake_file_manager() -> FakeFileManager:
    """Return an empty file-manager double."""
    return FakeFileManager()


@pytest.fixture()
def fake_indexer_factory() -> Callable[[Path, FakeAdapter], FakeIndexer]:
    """Return a factory caching fake indexers by storage directory."""
    indexers: dict[Path, FakeIndexer] = {}

    def factory(storage_dir: Path, adapter: FakeAdapter) -> FakeIndexer:
        path = Path(storage_dir)
        if path not in indexers:
            indexers[path] = FakeIndexer(path, adapter)
        return indexers[path]

    return factory
