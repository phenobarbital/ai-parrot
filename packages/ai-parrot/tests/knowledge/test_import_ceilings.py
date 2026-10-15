"""FEAT-540 import ceilings (spec §1) with persisted probe evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ._support.import_probe import run_import_probe

_REPO_ROOT = Path(__file__).resolve().parents[4]
_EVIDENCE = _REPO_ROOT / "artifacts" / "logs" / "FEAT-540-import-ceilings.json"

CEILINGS = [
    pytest.param("parrot.auth.exceptions", 150, id="auth.exceptions"),
    pytest.param("parrot.knowledge.ontology.schema", 240, id="ontology.schema"),
    pytest.param("parrot.knowledge.graphindex", 800, id="graphindex"),
    pytest.param("parrot.knowledge.graphindex.builder", 1200, id="graphindex.builder"),
    pytest.param(
        "parrot.knowledge.wiki.cli",
        850,
        id="wiki.cli",
    ),
]


def _record(module: str, ceiling: int, result: object) -> None:
    """Merge one probe result into the evidence file (skipped when UPDATE_EVIDENCE=0)."""
    if os.environ.get("UPDATE_EVIDENCE", "1") == "0":
        return
    try:
        _EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(_EVIDENCE.read_text()) if _EVIDENCE.exists() else {}
        data[module] = {
            "ceiling": ceiling,
            "count": result.count,  # type: ignore[attr-defined]
            "loaded_forbidden": result.loaded_forbidden,  # type: ignore[attr-defined]
            "error": result.error,  # type: ignore[attr-defined]
            "python": result.python,  # type: ignore[attr-defined]
            "revision": result.revision,  # type: ignore[attr-defined]
        }
        _EVIDENCE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


@pytest.mark.parametrize(("module", "ceiling"), CEILINGS)
def test_import_ceiling(module: str, ceiling: int) -> None:
    """Assert that an entry-point import stays within its current ceiling."""
    result = run_import_probe(module)
    _record(module, ceiling, result)
    assert result.error is None, result.error
    assert result.loaded_forbidden == [], result.loaded_forbidden
    assert result.count <= ceiling, result.count
