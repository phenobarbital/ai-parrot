"""Source backend parity (FEAT-540 M7)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager


class FakeArangoDb:
    """Small in-memory asyncdb double for manifest AQL operations."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def execute(self, aql: str, *, bind_vars: dict[str, Any]) -> tuple[list[Any], None]:
        """Apply the source UPSERT statements used by the backend."""
        documents = bind_vars.get("docs", [bind_vars.get("doc")])
        for document in documents:
            if document is not None:
                self.documents[document["_key"]] = dict(document)
        return [], None

    async def query(self, aql: str, *, bind_vars: dict[str, Any]) -> tuple[list[Any], None]:
        """Interpret the source read/remove statements used by the backend."""
        rows = list(self.documents.values())
        if "REMOVE doc" in aql:
            key = bind_vars["key"]
            removed = self.documents.pop(key, None)
            return ([removed] if removed else []), None
        if "doc.source_uri IN" in aql:
            wanted = set(bind_vars["uris"])
            return [row for row in rows if row["source_uri"] in wanted], None
        if "doc._key IN" in aql:
            wanted = set(bind_vars["keys"])
            return [row for row in rows if row["_key"] in wanted], None
        if "doc.external_id IN" in aql:
            wanted = set(bind_vars["ids"])
            return [row for row in rows if row.get("external_id") in wanted], None
        if "STARTS_WITH" in aql:
            return [row for row in rows if (row.get("external_id") or "").startswith(bind_vars["prefix"])], None
        if "doc.external_id ==" in aql:
            return [row for row in rows if row.get("external_id") == bind_vars["external_id"]][:1], None
        if "doc.source_uri ==" in aql:
            matching = [row for row in rows if row["source_uri"] == bind_vars["uri"]][:1]
            return ([row["source_id"] for row in matching] if "RETURN doc.source_id" in aql else matching), None
        if "doc._key ==" in aql:
            return [row for row in rows if row["_key"] == bind_vars["key"]][:1], None
        return rows, None


def _entry(source_id: str, external_id: str | None = None) -> SourceManifestEntry:
    """Create a deterministic source entry for backend parity checks."""
    return SourceManifestEntry(
        source_id=source_id,
        source_uri=f"/documents/{source_id}.md",
        file_hash=f"hash-{source_id}",
        mtime=1.0,
        ingested_at="2026-10-15T00:00:00Z",
        external_id=external_id,
    )


@pytest.mark.parametrize("backend", ["sqlite", "json", "arangodb"])
def test_source_backend_parity(tmp_path: Path, backend: str) -> None:
    """Verify all manifest operations yield the same observable results."""
    options: dict[str, Any] = {"backend": backend}
    if backend == "arangodb":
        options["arango_db"] = FakeArangoDb()
    manager = SourceCollectionManager(tmp_path / backend / "sources", **options)
    first = _entry("one", "fireflies:one")
    second = _entry("two", "fireflies:two")

    manager._upsert(first)
    manager._upsert_many([second])

    assert {entry.source_id for entry in manager.list_sources()} == {"one", "two"}
    assert manager.get_source("one") == first
    assert manager.find_by_uri(first.source_uri) == "one"
    assert manager.find_entries_by_uris([first.source_uri]) == {first.source_uri: first}
    assert manager.find_entries_by_ids(["two"]) == {"two": second}
    assert manager.find_by_external_id("fireflies:one") == first
    assert manager.find_entries_by_external_ids(["fireflies:two"]) == {"fireflies:two": second}
    assert manager.list_by_external_prefix("fireflies:") == [first, second]
    assert manager.remove_source("one") is True
    assert manager.remove_source("one") is False


def test_source_manager_has_no_backend_equality_branch() -> None:
    """Ensure public dispatch remains behind the source backend registry."""
    source_path = Path(__file__).parents[3] / "src" / "parrot" / "knowledge" / "wiki" / "sources.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Compare)
        and any(isinstance(operator, ast.Eq) for operator in node.ops)
        and any(
            isinstance(value, ast.Attribute) and value.attr == "backend" for value in [node.left, *node.comparators]
        )
        for node in ast.walk(tree)
    )
