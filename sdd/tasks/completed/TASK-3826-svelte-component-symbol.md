# TASK-3826: Svelte `component` symbol, markup `uses` edges, and `uses` in blast

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3821
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 2 / §3 Module 3 / G3, and Q3 (answered "qualified"). The unit that other files
import and render, the component, never becomes a symbol. So `symbols lookup AdminBulkBar`
and `symbols blast AdminBulkBar` return nothing, even though the file-level `references` edges
exist. Top-level script refs have `src_qualname == ""` and are dropped by `SymbolResolver`
(`repo_scan.py:903`).

This task adds one `component` symbol per `.svelte` file, emits `uses` refs for markup usage of
imported components, re-attributes the orphan refs to the component, and makes `blast` follow
`uses`.

---

## Scope

- **Symbol kind.** Add `SymbolKind.COMPONENT = "component"` after `MOD`.
- **Augment.** In `javascript.py`, add a pure `_svelte_component_augment(source, rel_path,
  structural) -> StructuralOutline`. In `JavaScriptScanner.outline`, call it only when the
  suffix is `.svelte` **and** the seam returned a `StructuralOutline`. It does four things:
  1. **Prepend the component record:**
     - `kind=COMPONENT`, `exported=True`, `depth=1`, `parent=None`,
       `node_kind="svelte_component"`, `language="javascript"`;
     - `start_line=1`, `end_line=<source line count>`, `start_byte=0`,
       `end_byte=len(source.encode())`;
     - `content_hash` = SHA-1 of the source;
     - `signature` = the `$props()` type annotation when present, else the destructured
       `{ … }`, else `""`, capped at 200 chars;
     - `doc=""`.
  2. **Naming (Q3).**
     - A stem that does **not** start with `+` gets `name = qualname = <stem>`.
     - A **route file** (the stem starts with `+`) gets:
       - `name` = `<parent dir name>/<stem>` (e.g. `fieldsync/+page`);
       - `qualname` = the path from the nearest `routes/` ancestor, without the suffix
         (e.g. `(app)/[programs]/fieldsync/+page`), falling back to `rel_path` without the
         suffix when no `routes/` segment exists.
  3. **`uses` refs.** For every PascalCase opening tag in the markup (the source with
     `<script>`/`<style>` blocks blanked, preserving newlines) whose name is the default binding
     of an `import X from '….svelte'`, emit
     `SymbolRef(src_qualname=<component qualname>, rel="uses", target_text=<imported file stem>,
     line=<tag line>)`. Deduplicate per `(target, line)`.
  4. **Re-attribute.** Every ref with `src_qualname == ""` gets the component qualname.
- **Existing script symbols are untouched**: `parent=None` and qualnames unchanged, so no
  existing `sym:` id changes.
- **Blast.** `structural/service.py` `_DEFAULT_BLAST_RELATIONS` gains `"uses"`.
  `structural/tools.py` `BlastRadiusInput.relations` `Literal` gains `"uses"`, and its
  description's default list is updated.
- Write tests with fixtures.

**NOT in scope**:
- module-local arrow symbols (TASK-3823);
- the CLI `--rel` help text (`cli.py:2338`, which mentions the default list): TASK-3829 updates
  it, because it owns the next `cli.py` edit;
- markup semantics beyond component tags (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py` | MODIFY | `SymbolKind.COMPONENT` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | MODIFY | `_svelte_component_augment` + call site |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` | MODIFY | `"uses"` in `_DEFAULT_BLAST_RELATIONS` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | MODIFY | `"uses"` in the `relations` Literal + description |
| `tests/knowledge/wiki/languages/test_svelte_component.py` | CREATE | unit + blast integration tests |
| `tests/knowledge/wiki/languages/fixtures/svelte_components/Child.svelte` | CREATE | fixture |
| `tests/knowledge/wiki/languages/fixtures/svelte_components/Parent.svelte` | CREATE | fixture |
| `tests/knowledge/wiki/languages/fixtures/svelte_components/Other.svelte` | CREATE | fixture |
| `tests/knowledge/wiki/languages/fixtures/svelte_components/routes/(app)/fieldsync/+page.svelte` | CREATE | fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, SymbolRef, StructuralOutline  # symbols.py:31, :56, :105, :123
from parrot.knowledge.wiki.symbols import sym_concept_id, parse_sym_id
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
```

### Existing Signatures to Use
```python
# symbols.py:53   MOD = "mod"   (last SymbolKind member; occurrences: 1)
# symbols.py:56   class SymbolRecord(BaseModel): rel_path, language, kind, name, qualname, parent,
#                 signature, doc, exported, is_async, start_line, end_line, start_byte, end_byte,
#                 node_kind, decorators, content_hash, depth
# symbols.py:105  class SymbolRef(BaseModel): src_qualname, rel ("calls|extends|implements|uses"), target_text, line
# symbols.py:327  def sha1_of_text(text: str) -> str   — what astgrep uses for content_hash (astgrep.py:841)
# javascript.py:77   _SVELTE_SUFFIX = ".svelte"
# javascript.py:529  script_source, lang = _extract_script_blocks(source, suffix)
# javascript.py:533                  if structural is not None:          (occurrences: 1)
# javascript.py:534-541 returns LanguageOutline(summary=structural.summary, outline=render_outline(structural.symbols, "javascript"),
#                        imports=imports, symbols=structural.symbols, refs=structural.refs)
# structural/service.py:44   _DEFAULT_BLAST_RELATIONS = ("calls", "extends", "implements")    (occurrences: 1)
# structural/tools.py:74-77  relations: list[Literal["calls", "extends", "implements", "references", "contains"]] | None = Field(
#                               default=None, description="Edge relations to follow (default: calls, extends, implements)")
# repo_scan.py:903  class SymbolResolver — step 2 resolves a unique name in a file reachable via a `references` edge
```
Verified: `sym_concept_id("src/routes/(app)/[programs]/fieldsync/+page.svelte",
"(app)/[programs]/fieldsync/+page")` round-trips through `parse_sym_id` (checked 2026-09-28).

### Does NOT Exist
- ~~`SymbolKind.COMPONENT`~~: created here.
- ~~A Svelte ast-grep grammar~~: markup is handled by regex over the blanked source, not parsed.
- ~~An import-binding extractor in `javascript.py`~~: `_extract_imports` returns specifiers
  only. The default-binding regex is new (below).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/languages/test_svelte_component.py", "action": "CREATE"},
    {"path": "tests/knowledge/wiki/languages/fixtures/svelte_components/Child.svelte", "action": "CREATE"},
    {"path": "tests/knowledge/wiki/languages/fixtures/svelte_components/Parent.svelte", "action": "CREATE"},
    {"path": "tests/knowledge/wiki/languages/fixtures/svelte_components/Other.svelte", "action": "CREATE"},
    {"path": "tests/knowledge/wiki/languages/fixtures/svelte_components/routes/(app)/fieldsync/+page.svelte", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolKind",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRef",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py#JavaScriptScanner.outline",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#SymbolResolver"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never raise**: any failure in the augment returns `structural` unchanged (the
  `outline` contract).
- **G5 parity**: `COMPONENT` is not in `render._JS_RENDERED_KINDS`, so the outline is
  unchanged. Pass the *augmented* `symbols` to `LanguageOutline`, but keep calling
  `render_outline` on them. The component is filtered out there by kind.
- **Resolution**: the `uses` target is the imported file's **stem**, because
  `import Kid from './Child.svelte'` renders `<Kid/>` but the target symbol is named `Child`.
  Step 2 of `SymbolResolver` finds it through the file-level `references` edge.
- The regexes below were prototyped on 2026-09-28. On a sample component they returned:
  - imports: `{'Child': './Child.svelte', 'Kid': '../x/Child.svelte', 'Icon': '$lib/components/common/Icon.svelte'}`;
  - `uses` refs: `Child` at line 9, `Kid → Child` at line 10, `Icon` at line 11, `Child` at line 12;
  - `NotImported` ignored;
  - props type: `{ rows: Row[]; onPick: (r: Row) => void }`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the enum member. 2. Add the augment helper and its regexes. 3. Wire it into
`outline`. 4. Add `uses` to blast. 5. Write fixtures and tests. 6. Run parity and mutation-check.

### `packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    MOD = "mod"' symbols.py)
# AFTER — insert below `    MOD = "mod"` (verified: symbols.py:53)
    COMPONENT = "component"
```
Also extend the class docstring: "…plus Svelte single-file components (FEAT-609)".

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` (MODIFY) — helper
```python
# occurrences: 1 (verified: grep -c '^def _astgrep_lang_for' languages/javascript.py)
# BEFORE — insert above `def _astgrep_lang_for(` (verified: javascript.py:241)

_SVELTE_DEFAULT_IMPORT = re.compile(r"""^\s*import\s+([A-Za-z_$][\w$]*)\s+from\s+['"]([^'"]+\.svelte)['"]""", re.M)
_SVELTE_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_SVELTE_COMPONENT_TAG = re.compile(r"<([A-Z][\w$]*)(?=[\s/>])")
_SVELTE_PROPS = re.compile(r"let\s*(\{.*?\})\s*(?::\s*(.+?))?\s*=\s*\$props\(\s*\)", re.S)


def _svelte_component_names(rel_path: str) -> tuple[str, str]:
    """``(name, qualname)`` of a component (FEAT-609 Q3: route files are qualified)."""
    path = PurePosixPath(rel_path)
    stem = path.stem
    if not stem.startswith("+"):
        return stem, stem
    name = f"{path.parent.name}/{stem}" if path.parent.name else stem
    parts = path.with_suffix("").parts
    if "routes" in parts:
        idx = len(parts) - 1 - parts[::-1].index("routes")
        return name, "/".join(parts[idx + 1 :])
    return name, path.with_suffix("").as_posix()


def _svelte_component_augment(source: str, rel_path: str, structural: StructuralOutline) -> StructuralOutline:
    """Return ``structural`` with the component symbol prepended, markup ``uses``
    refs appended, and empty-``src_qualname`` refs re-attributed (FEAT-609 M3).

    Pure; never raises — on any failure returns ``structural`` unchanged.
    """
    try:
        name, qualname = _svelte_component_names(rel_path)
        component = SymbolRecord(
            rel_path=rel_path,
            language="javascript",
            kind=SymbolKind.COMPONENT,
            name=name,
            qualname=qualname,
            signature=_svelte_props_signature(source)[:200],
            exported=True,
            start_line=1,
            end_line=max(1, source.count("\n") + 1),
            start_byte=0,
            end_byte=len(source.encode("utf-8")),
            node_kind="svelte_component",
            content_hash=sha1_of_text(source),
            depth=1,
        )
        refs = [ref if ref.src_qualname else ref.model_copy(update={"src_qualname": qualname}) for ref in structural.refs]
        refs.extend(_svelte_uses_refs(source, qualname))
        return structural.model_copy(update={"symbols": [component, *structural.symbols], "refs": refs})
    except Exception as exc:  # noqa: BLE001 - degrade, never raise
        logger.debug("Svelte component augment failed on %s: %s", rel_path, exc)
        return structural


def _svelte_props_signature(source: str) -> str:
    """The ``$props()`` type annotation, else the destructured pattern, else ``""``."""
    match = _SVELTE_PROPS.search(source)
    if match is None:
        return ""
    return (match.group(2) or match.group(1)).strip()


def _svelte_uses_refs(source: str, qualname: str) -> list[SymbolRef]:
    """One ``uses`` ref per markup tag bound to a default ``.svelte`` import."""
    imports = {m.group(1): m.group(2) for m in _SVELTE_DEFAULT_IMPORT.finditer(source)}
    if not imports:
        return []
    markup = _SVELTE_BLOCK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), source)
    seen: set[tuple[str, int]] = set()
    refs: list[SymbolRef] = []
    for match in _SVELTE_COMPONENT_TAG.finditer(markup):
        spec = imports.get(match.group(1))
        if spec is None:
            continue
        target = PurePosixPath(spec).stem
        line = markup.count("\n", 0, match.start()) + 1
        if (target, line) in seen:
            continue
        seen.add((target, line))
        refs.append(SymbolRef(src_qualname=qualname, rel="uses", target_text=target, line=line))
    return refs
```
Add
`from parrot.knowledge.wiki.symbols import StructuralOutline, SymbolKind, SymbolRecord, SymbolRef, sha1_of_text`
next to the other `parrot.knowledge.wiki` imports (`javascript.py:40-42`). `re` and
`PurePosixPath` are already imported (`javascript.py:34`, `:37`).
**Why**: blanking the script/style blocks while keeping `\n` keeps the tag line numbers exact
(checked in the prototype with an `assert` on the newline counts).

### `javascript.py` (MODIFY) — call site
```python
# occurrences: 1 (verified: grep -c '                if structural is not None:' languages/javascript.py)
# AFTER — insert below `                if structural is not None:` (verified: javascript.py:533)
                    if suffix == _SVELTE_SUFFIX:
                        structural = _svelte_component_augment(source, rel_path, structural)
```
**Why**: the helper receives the **raw** `source` (markup included), not `script_source`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_DEFAULT_BLAST_RELATIONS = ("calls", "extends", "implements")' structural/service.py)
# REPLACE that line (verified: service.py:44) with:
_DEFAULT_BLAST_RELATIONS = ("calls", "extends", "implements", "uses")
```
Update the `blast_radius` docstring default list (`service.py:305-306`).

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'relations: list\[Literal\["calls", "extends", "implements", "references", "contains"\]\]' structural/tools.py)
# REPLACE lines 74-77 (verified: tools.py:74-77) with:
    relations: list[Literal["calls", "extends", "implements", "uses", "references", "contains"]] | None = Field(
        default=None,
        description="Edge relations to follow (default: calls, extends, implements, uses)",
    )
```

### Fixtures (CREATE)
```svelte
<!-- tests/knowledge/wiki/languages/fixtures/svelte_components/Child.svelte -->
<script lang="ts">
	let { items }: { items: string[] } = $props()
	const onPick = (i: string) => pick(i)
</script>
<ul>{#each items as i}<li on:click={() => onPick(i)}>{i}</li>{/each}</ul>
```
```svelte
<!-- Parent.svelte -->
<script lang="ts">
	import Child from './Child.svelte'
	let { rows }: { rows: string[] } = $props()
	const onSave = async () => { persist(rows) }
</script>
<Child items={rows} />
```
```svelte
<!-- Other.svelte : binding differs from the file stem -->
<script lang="ts">
	import Kid from './Child.svelte'
</script>
<Kid items={[]} />
```
```svelte
<!-- routes/(app)/fieldsync/+page.svelte : markup only -->
<h1>FieldSync</h1>
```

### `tests/knowledge/wiki/languages/test_svelte_component.py` (CREATE)
```python
"""FEAT-609 M3: Svelte component symbols, `uses` edges, and blast over them."""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
from parrot.knowledge.wiki.symbols import SymbolKind

from .conftest import requires_astgrep

FIXTURES = Path(__file__).parent / "fixtures" / "svelte_components"


def _outline(rel: str):
    return JavaScriptScanner().outline((FIXTURES / rel).read_text(encoding="utf-8"), f"src/lib/{rel}")


@requires_astgrep
def test_svelte_component_symbol() -> None:
    comps = [s for s in _outline("Parent.svelte").symbols if s.kind == SymbolKind.COMPONENT]
    assert [(c.name, c.qualname) for c in comps] == [("Parent", "Parent")]
    assert comps[0].signature == "{ rows: string[] }"


@requires_astgrep
def test_svelte_uses_ref_by_import_stem() -> None:
    uses = [r for r in _outline("Other.svelte").refs if r.rel == "uses"]
    assert [(r.src_qualname, r.target_text) for r in uses] == [("Other", "Child")]


@requires_astgrep
def test_svelte_orphan_refs_attributed() -> None:
    refs = {r.target_text: r.src_qualname for r in _outline("Parent.svelte").refs if r.rel == "calls"}
    assert refs.get("$props") == "Parent"


@requires_astgrep
def test_svelte_route_component_qualified() -> None:
    rel = "src/routes/(app)/fieldsync/+page.svelte"
    text = (FIXTURES / "routes/(app)/fieldsync/+page.svelte").read_text(encoding="utf-8")
    comps = [s for s in JavaScriptScanner().outline(text, rel).symbols if s.kind == SymbolKind.COMPONENT]
    assert [(c.name, c.qualname) for c in comps] == [("fieldsync/+page", "(app)/fieldsync/+page")]


@requires_astgrep
def test_svelte_route_without_routes_dir() -> None:
    text = "<h1>x</h1>\n"
    comps = [s for s in JavaScriptScanner().outline(text, "pkg/+page.svelte").symbols if s.kind == SymbolKind.COMPONENT]
    assert comps[0].qualname == "pkg/+page"


@requires_astgrep
def test_svelte_existing_qualnames_stable() -> None:
    others = [s for s in _outline("Parent.svelte").symbols if s.kind != SymbolKind.COMPONENT]
    assert all(s.parent is None for s in others)


@requires_astgrep
def test_blast_component_users(tmp_path) -> None:
    # FILL IN: copy the 3 fixtures into tmp_path/src/lib/, build a wiki there
    # (the way tests/knowledge/wiki/structural/test_service.py builds its plane),
    # then StructuralService.blast_radius("sym:src/lib/Child.svelte#Child") must return
    # symbols from BOTH Parent.svelte and Other.svelte via `uses` — bounded by G3
    ...
```
**Why**: `test_svelte_route_without_routes_dir` has no `<script>` block. Verified 2026-09-28:
`_extract_script_blocks` returns `""`, and `astgrep.extract("", "javascript", …)` returns an
**empty `StructuralOutline`, not `None`**. So the augment runs and the markup-only component is
emitted, with no special case.

### FILL IN checklist
- [ ] `test_blast_component_users`. Bound: a real built plane, with no mocked store.
- [ ] Docstrings (the `SymbolKind` class, the `blast_radius` default list).

---

## Acceptance Criteria

- [ ] Each `.svelte` file yields exactly one `component` symbol, and route files are qualified
      (Q3).
- [ ] `<Kid/>` from `import Kid from './Child.svelte'` becomes `uses → Child`.
- [ ] Orphan script refs are attributed to the component.
- [ ] `blast` on a component returns its users by default (mutation-checked: drop `"uses"`
      from the default and see `test_blast_component_users` go RED).
- [ ] `test_outline_parity.py` passes unmodified, and no existing `sym:` id changes.

---

## Validation Commands

- `pytest tests/knowledge/wiki/languages/test_svelte_component.py -q`
- `pytest tests/knowledge/wiki/languages/test_outline_parity.py -q`
- `pytest tests/knowledge/wiki/languages/test_javascript_plugin.py -q`
- `pytest tests/knowledge/wiki/structural/test_service.py -q`
- `pytest tests/knowledge/wiki/structural/test_tools.py -q`

---

## Test Specification

See the CREATE blocks above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Confirm TASK-3821 is `done`, verify the contract, and re-run each `grep -c`.
3. Implement, validate, mutation-check, and stage only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3826 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

Implemented as specified. Mutations RED: dropping 'uses' from _DEFAULT_BLAST_RELATIONS -> test_blast_component_users; disabling orphan re-attribution -> test_svelte_orphan_refs_attributed. Parity + languages + structural + cli_symbols = 353 green.
