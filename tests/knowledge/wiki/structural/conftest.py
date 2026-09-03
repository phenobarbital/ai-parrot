"""Shared fixtures for ``StructuralService`` tests (FEAT-498 TASK-2749)."""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.knowledge.wiki.cli import _ingest_files, _open_sources, _open_store
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.repo_scan import scan_repository
from parrot.knowledge.wiki.structural import StructuralService


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
async def built_repo(tmp_path: Path) -> tuple[StructuralService, Path]:
    """Tmp repo (py + ts + php) ingested into a sqlite plane, plus its service.

    Python is always extracted via the stdlib-``ast`` heuristic tier (no
    ``ast-grep-py`` needed); the TS/PHP files exercise the seam when the
    optional extra is installed and fall back to the existing tree-sitter
    walkers otherwise — either way the plane ends up populated.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, "a.py", "def helper():\n    return 1\n")
    _write(root, "b.py", "from a import helper\n\n\ndef run():\n    return helper()\n")
    _write(root, "c.ts", "export function tsHelper(): number {\n  return 1;\n}\n")
    _write(root, "d.php", "<?php\nfunction phpHelper() {\n    return 1;\n}\n")

    config = WikiProjectConfig()
    store = _open_store(root, config)
    sources = _open_sources(root, config, store=store)
    scan = scan_repository(root, use_git=False)
    await _ingest_files(store, sources, root, scan)

    service = StructuralService(store, root, config)
    return service, root
