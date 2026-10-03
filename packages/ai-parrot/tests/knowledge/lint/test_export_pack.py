"""Tests for the export rule pack (TASK-4015)."""

from pathlib import Path
from typing import Any

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import LintOptions
from parrot.knowledge.lint.packs.export import (
    ExportDanglingRelatesToRule,
    ExportDriftRule,
    FrontmatterSchemaRule,
)
from parrot.knowledge.wiki.export import export_okf_bundle


class FakeStore:
    """Minimal store exposing dump_pages / dump_edges."""

    def __init__(self, pages: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> None:
        self.pages = pages
        self.edges = edges or []

    async def dump_pages(self) -> list[dict[str, Any]]:
        return self.pages

    async def dump_edges(self) -> list[dict[str, Any]]:
        return self.edges


def _pages() -> list[dict[str, Any]]:
    return [
        {"concept_id": "a", "title": "A", "category": "concept", "updated_at": "2026-01-01T00:00:00Z", "body": "x"},
        {"concept_id": "b", "title": "B", "category": "concept", "updated_at": "2026-01-02T00:00:00Z", "body": "y"},
    ]


def _ctx(store: FakeStore, export_dir: Path | None) -> LintContext:
    return LintContext(store, options=LintOptions(export_dir=export_dir))  # type: ignore[arg-type]


async def test_frontmatter_schema_invalid(tmp_path):
    store = FakeStore(_pages())
    await export_okf_bundle(store, tmp_path, "w")  # type: ignore[arg-type]
    target = next(tmp_path.rglob("a.md"))
    target.write_text(target.read_text().replace("id: a\n", ""), encoding="utf-8")
    findings = await FrontmatterSchemaRule().check(_ctx(store, tmp_path))
    assert len(findings) == 1
    assert findings[0].rule_id == "frontmatter-schema"
    assert findings[0].severity == "error"
    assert "id" in findings[0].message


async def test_export_drift_fix(tmp_path):
    store = FakeStore(_pages())
    await export_okf_bundle(store, tmp_path, "w")  # type: ignore[arg-type]
    store.pages.append(
        {"concept_id": "c", "title": "C", "category": "concept", "updated_at": "2026-01-03T00:00:00Z", "body": "z"}
    )
    store.pages[0]["updated_at"] = "2026-02-01T00:00:00Z"
    ctx = _ctx(store, tmp_path)
    rule = ExportDriftRule()
    findings = await rule.check(ctx)
    assert {f.subjects[0] for f in findings} == {"a", "c"}
    assert all(f.fixable for f in findings)
    results = [await rule.fix(ctx, f) for f in findings]
    assert all(r.applied for r in results)
    ctx.invalidate()
    assert await rule.check(ctx) == []


async def test_no_export_dir_is_info(tmp_path):
    store = FakeStore(_pages())
    for export_dir in (None, tmp_path / "missing"):
        ctx = _ctx(store, export_dir)
        findings = await FrontmatterSchemaRule().check(ctx)
        assert [(f.rule_id, f.severity) for f in findings] == [("export-missing", "info")]
        assert await ExportDriftRule().check(ctx) == []
        assert await ExportDanglingRelatesToRule().check(ctx) == []


async def test_dangling_relates_to(tmp_path):
    store = FakeStore(_pages(), [{"src": "a", "dst": "ghost", "rel": "references"}, {"src": "a", "dst": "b", "rel": "references"}])
    await export_okf_bundle(store, tmp_path, "w")  # type: ignore[arg-type]
    findings = await ExportDanglingRelatesToRule().check(_ctx(store, tmp_path))
    assert len(findings) == 1
    assert findings[0].data["target"] == "ghost"
