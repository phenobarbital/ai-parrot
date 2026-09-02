# TASK-2738: Symbol models, `sym:` id grammar and additive schema fields

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Everything downstream (rule backend, store schema, resolver,
tools) shares one contract: `SymbolRecord` / `SymbolRef` / `StructuralOutline`
and the `sym:<rel>#<qualname>[~n]` id grammar. This task lands that contract
plus every *additive, default-valued* field on existing models so later tasks
only add behaviour. Nothing here changes runtime output.

---

## Scope

- Create `parrot/knowledge/wiki/symbols.py` with `SymbolKind`, `SymbolRecord`,
  `SymbolRef`, `StructuralOutline`, `sym_concept_id(rel_path, qualname, ordinal=1)`,
  `sha1_of_text(text)` (SHA-1 hex of UTF-8 bytes — same digest family as
  `SourceCollectionManager._compute_hash`), and `parse_sym_id(concept_id) ->
  tuple[rel_path, qualname, ordinal]`.
- Extend `LanguageOutline` (`languages/base.py`) with `symbols: list[SymbolRecord]`
  and `refs: list[SymbolRef]`, both `Field(default_factory=list)`.
- Extend `FileSlice` with `symbols`, `refs` (same defaults) and `RepoScan` with
  `symbol_records: list[WikiPageRecord]` and `symbol_edges: list[tuple[str, str, str, str]]`.
- Extend `WikiPageRecord` (`store.py`) with `content_hash: Optional[str] = None`
  (model field only — persistence is TASK-2747).
- Add `sym` to `context._ID_KINDS`.
- Add `symbol_depth: int = Field(default=2, ge=1, le=6)` and
  `structural_backend: bool = Field(default=True)` to `WikiProjectConfig`.
- Add `CALLS = "calls"` and `IMPLEMENTS = "implements"` to `graphindex/schema.py::EdgeKind`.
- Unit tests for the id grammar, model defaults, `_ID_KINDS`, enum members.

**NOT in scope**: any extraction, rendering, DDL, ingest or tool code; no
`__init__.py` re-exports beyond what tests need.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py` | CREATE | Models + id helpers |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py` | MODIFY | `LanguageOutline.symbols/refs` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | `FileSlice.symbols/refs`, `RepoScan.symbol_records/symbol_edges` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `WikiPageRecord.content_hash` field only |
| `packages/ai-parrot/src/parrot/knowledge/wiki/context.py` | MODIFY | `_ID_KINDS` += `sym` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `WikiProjectConfig.symbol_depth`, `.structural_backend` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | MODIFY | `EdgeKind.CALLS`, `EdgeKind.IMPLEMENTS` |
| `tests/knowledge/wiki/test_symbols.py` | CREATE | Id grammar + model tests |
| `tests/knowledge/wiki/test_context.py` | MODIFY | `sym` id kind accepted by `split_namespaced_id` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field                                          # used throughout wiki/
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner   # languages/__init__.py:14
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, file_concept_id    # repo_scan.py:159/182/249
from parrot.knowledge.wiki.store import WikiPageRecord                              # store.py:224
from parrot.knowledge.wiki.context import split_namespaced_id, qualify_id           # context.py:54/82
from parrot.knowledge.wiki.project import WikiProjectConfig                         # project.py (class body fields :401-422)
from parrot.knowledge.graphindex.schema import EdgeKind                             # graphindex/schema.py:64
```

### Existing Signatures to Use
```python
# languages/base.py:21
class LanguageOutline(BaseModel):
    summary: str = ""                                    # :36
    outline: list[str] = Field(default_factory=list)     # :37
    imports: list[str] = Field(default_factory=list)     # :38   ← add symbols / refs after this

# repo_scan.py:159
class FileSlice(BaseModel):
    rel_path: str; record: WikiPageRecord
    imports: list[str] = Field(default_factory=list); language: str | None = None
# repo_scan.py:182
class RepoScan(BaseModel):
    root: Path; files: list[FileSlice]; dir_records: list[WikiPageRecord]
    dir_edges: list[tuple[str, str, str]]; import_edges: list[tuple[str, str, str]]; skipped: list[str]
def file_concept_id(rel_path: str) -> str:   # repo_scan.py:249 — returns f"file:{rel_path}"; mirror this style

# store.py:224
class WikiPageRecord(BaseModel):
    concept_id: str = Field(..., min_length=1); node_id: Optional[str] = None; title: str = ""
    category: str = "concept"; summary: str = ""; body: str = ""; source_id: Optional[str] = None
    token_count: int = Field(default=0, ge=0); origin: str = "ingest"; asserted_by: Optional[str] = None
    updated_at: Optional[str] = None                     # ← add content_hash: Optional[str] = None after this

# context.py:38
_ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page"   # feeds _ID_PREFIX_RE (:45) and _BARE_ID_PREFIX_RE (:51)
def split_namespaced_id(page_id: str) -> tuple[str | None, str]   # :54

# project.py — class WikiProjectConfig(BaseModel), fields :401-422
    body_max_chars: int = Field(default=16_000, ge=1_000)   # :406 — follow this Field style
    sync_graph: bool = Field(default=False)                # :409

# graphindex/schema.py:64
class EdgeKind(str, Enum):
    CONTAINS="contains"; REFERENCES="references"; DEFINES="defines"; MENTIONS="mentions"; EXPLAINS="explains"
    EXTENDS="extends"; PRODUCED="produced"; ABOUT="about"; SUPPORTED_BY="supported_by"; CONTRADICTS="contradicts"   # :82-91
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.symbols`~~ — this task creates it.
- ~~`SymbolRecord` / `SymbolRef` / `SymbolKind` / `StructuralOutline` / `sym_concept_id`~~ — nowhere in `parrot/` today.
- ~~`WikiPageRecord.content_hash`~~, ~~`LanguageOutline.symbols`~~, ~~`FileSlice.symbols`~~ — not present yet.
- ~~`EdgeKind.CALLS` / `IMPLEMENTS`~~ — not present yet.
- ~~a `sym:` producer anywhere~~ — `func`/`class` are listed in `_ID_KINDS` but nothing emits them; do not repurpose them.

---

## Implementation Notes

### Pattern to Follow
```python
# Model shape (spec §2 Data Models) — keep field names exactly:
class SymbolRecord(BaseModel):
    rel_path: str; language: str; kind: SymbolKind; name: str; qualname: str
    parent: str | None = None; signature: str = ""; doc: str = ""
    exported: bool = False; is_async: bool = False
    start_line: int; end_line: int; start_byte: int; end_byte: int
    node_kind: str = ""; decorators: list[str] = Field(default_factory=list)
    content_hash: str; depth: int = 1

def sym_concept_id(rel_path: str, qualname: str, ordinal: int = 1) -> str:
    base = f"sym:{rel_path}#{qualname}"
    return base if ordinal <= 1 else f"{base}~{ordinal}"
```

### Key Constraints
- `SymbolRef.rel` is `Literal["calls", "extends", "implements", "uses"]`.
- `~` is the ordinal separator; assert in tests that `parse_sym_id` round-trips
  qualnames containing `::`, `\\`, `.` and `#`-free names for the five languages.
- Imports in `base.py`/`repo_scan.py` must not create a cycle: `symbols.py`
  imports only `pydantic`/stdlib.
- Google docstrings + type hints on every public symbol.

### References in Codebase
- `repo_scan.py:249-258` — `file_concept_id` / `dir_concept_id` style.
- `sources.py:1115` — `_compute_hash` (file-path SHA-1) — `sha1_of_text` is the in-memory twin.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/test_symbols.py tests/knowledge/wiki/test_context.py tests/knowledge/wiki/languages tests/knowledge/wiki/test_repo_scan.py tests/knowledge/wiki/test_store.py -v` passes (no behaviour change anywhere).
- [ ] `sym_concept_id("a/b.py", "X")` → `sym:a/b.py#X`; ordinal 2 → `sym:a/b.py#X~2`; `parse_sym_id` inverts both.
- [ ] `split_namespaced_id("ns::sym:a.py#X") == ("ns", "sym:a.py#X")`; bare `sym:a.py#X` → `(None, …)`.
- [ ] `LanguageOutline()`, `FileSlice(...)`, `RepoScan(...)`, `WikiPageRecord(...)` construct with the old argument sets.
- [ ] `EdgeKind.CALLS.value == "calls"`, `EdgeKind.IMPLEMENTS.value == "implements"`.
- [ ] `WikiProjectConfig().symbol_depth == 2`, `.structural_backend is True`; existing `wiki.json` files load unchanged.
- [ ] `ruff check` and `mypy` clean on touched files.

---

## Test Specification

```python
# tests/knowledge/wiki/test_symbols.py
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, sym_concept_id, parse_sym_id, sha1_of_text

def test_sym_id_plain_and_ordinal():
    assert sym_concept_id("a/b.py", "Cls.m") == "sym:a/b.py#Cls.m"
    assert sym_concept_id("a/b.py", "Cls.m", 2) == "sym:a/b.py#Cls.m~2"
    assert parse_sym_id("sym:a/b.py#Cls.m~3") == ("a/b.py", "Cls.m", 3)
    assert parse_sym_id("sym:src/App/User.php#App\\Models\\User::getFullName") == ("src/App/User.php", "App\\Models\\User::getFullName", 1)

def test_sha1_of_text_matches_hashlib():
    import hashlib; assert sha1_of_text("x") == hashlib.sha1(b"x").hexdigest()

def test_record_defaults():
    r = SymbolRecord(rel_path="a.py", language="python", kind=SymbolKind.FUNCTION, name="f", qualname="f",
                     start_line=1, end_line=2, start_byte=0, end_byte=10, content_hash="deadbeef")
    assert r.depth == 1 and r.decorators == [] and r.exported is False
```

---

## Agent Instructions

1. Read spec §2 Data Models and §6. 2. No dependencies. 3. Verify every contract
line above with `grep -n`. 4. Update `sdd/tasks/index/ast-grep-for-wikitoolkit.json`
→ `in-progress`. 5. Implement. 6. Run the acceptance pytest line. 7. Move this file
to `sdd/tasks/completed/`. 8. Index → `done`. 9. Fill the Completion Note.

---

## Completion Note

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
