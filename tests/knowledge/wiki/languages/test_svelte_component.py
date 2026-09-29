"""FEAT-609 M3: Svelte component symbols, `uses` edges, and blast over them."""

from __future__ import annotations

import shutil
from pathlib import Path

from parrot.knowledge.wiki.cli import _ingest_files, _open_sources, _open_store
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.repo_scan import scan_repository
from parrot.knowledge.wiki.structural import StructuralService
from parrot.knowledge.wiki.symbols import SymbolKind

from .conftest import requires_astgrep

FIXTURES = Path(__file__).parent / "fixtures" / "svelte_components"


def _outline(rel: str):
    return JavaScriptScanner().outline((FIXTURES / rel).read_text(encoding="utf-8"), f"src/lib/{rel}")


def _components(outline) -> list:
    return [s for s in outline.symbols if s.kind == SymbolKind.COMPONENT]


@requires_astgrep
def test_svelte_component_symbol() -> None:
    comps = _components(_outline("Parent.svelte"))
    assert [(c.name, c.qualname) for c in comps] == [("Parent", "Parent")]
    assert comps[0].signature == "{ rows: string[] }"
    assert comps[0].node_kind == "svelte_component"
    assert comps[0].exported is True and comps[0].parent is None


@requires_astgrep
def test_svelte_uses_ref_by_import_stem() -> None:
    uses = [r for r in _outline("Other.svelte").refs if r.rel == "uses"]
    assert [(r.src_qualname, r.target_text) for r in uses] == [("Other", "Child")]


@requires_astgrep
def test_svelte_uses_ref_same_binding() -> None:
    uses = [(r.src_qualname, r.target_text, r.line) for r in _outline("Parent.svelte").refs if r.rel == "uses"]
    assert uses == [("Parent", "Child", 6)]


@requires_astgrep
def test_svelte_orphan_refs_attributed() -> None:
    refs = {r.target_text: r.src_qualname for r in _outline("Parent.svelte").refs if r.rel == "calls"}
    assert refs.get("$props") == "Parent"
    assert not [r for r in _outline("Parent.svelte").refs if not r.src_qualname]


@requires_astgrep
def test_svelte_no_script() -> None:
    rel = "src/routes/(app)/fieldsync/+page.svelte"
    text = (FIXTURES / "routes/(app)/fieldsync/+page.svelte").read_text(encoding="utf-8")
    out = JavaScriptScanner().outline(text, rel)
    assert [c.name for c in _components(out)] == ["fieldsync/+page"]


@requires_astgrep
def test_svelte_route_component_qualified() -> None:
    rel = "src/routes/(app)/[programs]/fieldsync/+page.svelte"
    comps = _components(JavaScriptScanner().outline("<h1>x</h1>\n", rel))
    assert [(c.name, c.qualname) for c in comps] == [("fieldsync/+page", "(app)/[programs]/fieldsync/+page")]


@requires_astgrep
def test_svelte_route_without_routes_dir() -> None:
    comps = _components(JavaScriptScanner().outline("<h1>x</h1>\n", "pkg/+page.svelte"))
    assert comps[0].qualname == "pkg/+page"


@requires_astgrep
def test_svelte_existing_qualnames_stable() -> None:
    others = [s for s in _outline("Parent.svelte").symbols if s.kind != SymbolKind.COMPONENT]
    assert others and all(s.parent is None for s in others)
    assert "onSave" in {s.qualname for s in others}


@requires_astgrep
def test_svelte_outline_text_unchanged() -> None:
    """G5: the component never reaches the `## API outline` text."""
    out = _outline("Parent.svelte")
    assert not any("Parent" in line for line in out.outline)


@requires_astgrep
async def test_blast_component_users(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    lib = root / "src" / "lib"
    lib.mkdir(parents=True)
    for name in ("Child.svelte", "Parent.svelte", "Other.svelte"):
        shutil.copy(FIXTURES / name, lib / name)
    config = WikiProjectConfig()
    store = _open_store(root, config)
    sources = _open_sources(root, config, store=store)
    await _ingest_files(store, sources, root, scan_repository(root, use_git=False))
    service = StructuralService(store, root, config)

    lookup = await service.lookup("Child")
    assert [h.kind for h in lookup.hits if h.qualname == "Child"] == [SymbolKind.COMPONENT]

    out = await service.blast_radius("sym:src/lib/Child.svelte#Child")
    users = {(imp.symbol.qualname, imp.via) for imp in out.impacted}
    assert {("Parent", "uses"), ("Other", "uses")} <= users


@requires_astgrep
def test_svelte_props_signature_ignores_earlier_destructuring() -> None:
    src = "<script>\n  let { a } = foo(); const x = 1;\n  let { rows, onSave } = $props()\n</script>\n<p/>\n"
    comps = _components(JavaScriptScanner().outline(src, "src/lib/P.svelte"))
    assert comps[0].signature == "{ rows, onSave }"
