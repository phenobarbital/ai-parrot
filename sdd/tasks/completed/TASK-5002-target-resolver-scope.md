# TASK-5002: Typed target resolver and scope (M4)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4997
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, design-research S5, audit F05, AC7. Decision targets are exact typed ids
(`sym:<rel>#<qualname>`, `file:<rel>`, `dir:<rel>`). Validation is by exact existence in the structural plane
plus repository-path confinement — never by `StructuralService.lookup()` (lexical; suggestions only) and never
by inferring from an empty `outline()`. Scope semantics: symbol → symbol; file → file and its symbols; dir →
path-segment descendants; the ancestor chain (`file:` then every `dir:` up to the root) is what lets a `dir:`
rule govern a descendant symbol target (AC7).

Owner-confirmed **not delegation-eligible**: the dir-expansion completeness contract needs judgement.

---

## Scope

- Create `scope.py`: `ResolvedTarget`, `TargetResolver` (`resolve`, `ancestors_of`, `expand_dir`).
- Diagnostics: `TARGET_UNRESOLVED` (with up to 3 suggestions from `lookup()`), `TARGET_FOREIGN`
  (outside root / foreign namespace), `SCOPE_INCOMPLETE` (dir expansion not complete).
- Tests `test_scope.py`.

**NOT in scope**: impact / blast radius (TASK-5005); collecting governing records (TASK-5003 `governing()`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/scope.py` | CREATE | resolver + scope |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_scope.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.models import (     # models.py:47,57,215 + TASK-4997
    _Strict, DecisionDiagnostic, DecisionError, DecisionTarget,
    TARGET_UNRESOLVED, TARGET_FOREIGN, SCOPE_INCOMPLETE, ADR_PATH_OUTSIDE_ROOT,
)
from parrot.knowledge.wiki.decisions.evidence import _resolve_confined   # verified: evidence.py:205
from parrot.knowledge.wiki.repo_scan import discover_repo_files, dir_concept_id, file_concept_id  # repo_scan.py:369,268,263
from parrot.knowledge.wiki.store import BaseWikiStore                   # store.py (get_page :765, page_hashes :1074)
from parrot.knowledge.wiki.structural.service import StructuralService  # structural/service.py:130
```

### Existing Signatures to Use
```python
# decisions/evidence.py:205
def _resolve_confined(root: Path, rel_path: str) -> Path   # raises DecisionError(ADR_PATH_OUTSIDE_ROOT)
# repo_scan.py
def file_concept_id(rel_path: str) -> str      # line 263 → f"file:{PurePosixPath(rel_path)}"
def dir_concept_id(rel_path: str) -> str       # line 268 → f"dir:{PurePosixPath(rel_path) if rel_path else '.'}"
def discover_repo_files(root: Path, suffixes: Iterable[str] | None = None,
                        exclude_dirs: Iterable[str] | None = None, use_git: bool = True) -> list[str]   # line 369 (sync)
# store.py — class BaseWikiStore
async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]   # line 765
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]                   # line 1074
# structural/service.py
class StructuralService:  # line 130 — __init__(store, root, config, *, read_repair=True) (line 143)
    async def lookup(self, query: str, *, kind=None, language=None, path_prefix=None, limit: int = 20) -> SymbolLookupOutput  # line 182
class SymbolLookupOutput(BaseModel): hits: list[SymbolHit]; total: int; repaired_files: list[str]   # line 66
class SymbolHit(BaseModel): symbol_id: str; rel_path: str; qualname: str; kind; ...                 # line 49
```

### Does NOT Exist
- ~~`StructuralService.lookup()` as an id validator~~ — lexical; suggestions only (spec F05).
- ~~`DecisionService._resolve_symbol()` existence check~~ — it accepts any `sym:` prefix without checking (service.py:171).
- ~~`StructuralService.resolve()` / `exists()`~~ — no such methods; existence is `store.get_page(id) is not None`.
- ~~`store.list_pages` in this module~~ — spec §7: only `InventorySnapshot` may list pages.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/scope.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_scope.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py#_resolve_confined",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#discover_repo_files",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#file_concept_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#dir_concept_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService"
  ]
}
```

---

## Implementation Notes

- `rel` of an id: `sym:<rel>#<qual>` → `<rel>`; `file:<rel>` → `<rel>`; `dir:<rel>` → `<rel>` (`.` = root).
- Confinement first: `_resolve_confined(root, rel)` raising `ADR_PATH_OUTSIDE_ROOT` ⇒ `TARGET_FOREIGN`. An id
  containing a namespace selector (`<ns>::` or any `:`-prefix other than sym/file/dir) ⇒ `TARGET_FOREIGN`.
- Existence: `await store.get_page(target_id, include_body=False)`; `None` ⇒ `state="missing"`, `TARGET_UNRESOLVED`,
  suggestions = `[h.symbol_id for h in (await structural.lookup(<qualname or basename>, limit=3)).hits]`
  in the diagnostic message (suggest, never substitute — S5).
- `expand_dir`: run `discover_repo_files(root)` in `asyncio.to_thread` (it is sync and may call git); keep files
  whose path is `rel` or starts with `rel + "/"` (path segments, not string prefix: `dir:pkg` must not match `pkg2/`);
  map to `file_concept_id`; `page_hashes` → any `None` ⇒ `complete=False`. Return sorted ids.
- `ancestors_of(page_id)`: pure path computation (no I/O needed beyond what the signature allows):
  `sym:a/b/c.py#f` → `["file:a/b/c.py", "dir:a/b", "dir:a", "dir:."]`; `file:` starts at its dir; `dir:` at its parent.
- `ResolvedTarget.state` values: `resolved | missing | unsupported | stale | incomplete` (S5: never infer from an empty outline).

---

## Implementation Blueprint

### Steps (in order)
1. Model + id helpers — *why*: shared parsing of the three prefixes.
2. `resolve()` — confinement, existence, suggestions, ancestors — *why*: AC7 exact-or-invalid.
3. `ancestors_of()` and `expand_dir()` — *why*: ancestor scope for governing collection; completeness for `incomplete`.
4. Tests on the in-memory store with hand-seeded pages.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/scope.py` (CREATE)
```python
"""Typed target resolution and scope for decision targets (FEAT-784 Module 4)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path, PurePosixPath
from typing import Literal

from parrot.knowledge.wiki.decisions.evidence import _resolve_confined
from parrot.knowledge.wiki.decisions.models import (
    TARGET_FOREIGN, TARGET_UNRESOLVED, DecisionDiagnostic, DecisionError, DecisionTarget, _Strict,
)
from parrot.knowledge.wiki.repo_scan import dir_concept_id, discover_repo_files, file_concept_id
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.service import StructuralService

_KINDS = {"sym:": "symbol", "file:": "file", "dir:": "dir"}


class ResolvedTarget(_Strict):
    """Outcome of resolving one exact target id."""

    target: DecisionTarget
    page_id: str | None
    ancestors: list[str]
    descendants: list[str]
    state: Literal["resolved", "missing", "unsupported", "stale", "incomplete"]


def _split(target_id: str) -> tuple[str, str] | None:
    """Return ``(kind, rel_path)`` or ``None`` for an unsupported prefix."""
    # FILL IN: match one of _KINDS prefixes; for sym strip "#<qualname>"; "dir:." / "dir:" → rel "." —
    #          a "<ns>::" selector or any other prefix → None
    return None


class TargetResolver:
    """Exact-id validation against the structural plane and the confined repository root."""

    def __init__(self, store: BaseWikiStore, root: Path, structural: StructuralService) -> None:
        self._store = store
        self._root = root
        self._structural = structural
        self.logger = logging.getLogger(__name__)

    async def resolve(self, target_id: str) -> tuple[ResolvedTarget | None, list[DecisionDiagnostic]]:
        """Exact id only; missing ⇒ TARGET_UNRESOLVED (+ suggestions); foreign/outside root ⇒ TARGET_FOREIGN."""
        parts = _split(target_id)
        if parts is None:
            return None, [DecisionDiagnostic(code=TARGET_FOREIGN, message=f"unsupported target id {target_id!r}")]
        kind, rel = parts
        try:
            _resolve_confined(self._root, rel)
        except DecisionError as exc:
            return None, [DecisionDiagnostic(code=TARGET_FOREIGN, message=str(exc))]
        target = DecisionTarget(target_id=target_id, kind=kind)
        page = await self._store.get_page(target_id, include_body=False)
        if page is None:
            # FILL IN: suggestions via self._structural.lookup(<qualname for sym, basename otherwise>, limit=3);
            #          return ResolvedTarget(state="missing", page_id=None, ...) + TARGET_UNRESOLVED diagnostic listing
            #          suggestions — bounded by AC7 ("resolve exactly or invalid with suggestions"); never substitute
            pass
        # FILL IN: ancestors = await self.ancestors_of(target_id); descendants for dir via expand_dir
        #          (complete=False → state="incomplete" + SCOPE_INCOMPLETE diagnostic); file → [] (its symbols are
        #          covered by ancestor matching in InventorySnapshot.governing); return state="resolved"
        return None, []

    async def ancestors_of(self, page_id: str) -> list[str]:
        """file: then every dir: ancestor up to the repo root (``dir:.``)."""
        # FILL IN: pure path computation per Implementation Notes; use file_concept_id / dir_concept_id
        return []

    async def expand_dir(self, dir_id: str) -> tuple[list[str], bool]:
        """(descendant page ids, complete) — complete=False when scan coverage is partial."""
        # FILL IN: files = await asyncio.to_thread(discover_repo_files, self._root); path-segment filter;
        #          ids = sorted(file_concept_id(f)); hashes = await self._store.page_hashes(ids);
        #          complete = all(v is not None for v in hashes.values())
        return [], False
```
**Why this shape**: signatures fixed by spec §3 M4 skeleton. `ResolvedTarget.state` carries `incomplete`
so TASK-5005 can turn partial scope into status `incomplete` instead of a false `pass`. Note
`SCOPE_INCOMPLETE` must be added to the models import when filling in `resolve`.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_scope.py` (CREATE)
```python
"""FEAT-784 M4 — typed target resolver."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.scope import TargetResolver
from parrot.knowledge.wiki.store import WikiPageRecord


@pytest.fixture
async def resolver(adr_store, tmp_path):
    """adr_store (conftest.py:190) seeded with file:/sym:/dir: pages for a tiny tree under tmp_path."""
    # FILL IN: create tmp_path/pkg/a.py; upsert WikiPageRecord(concept_id="file:pkg/a.py"), "sym:pkg/a.py#f",
    #          "dir:pkg"; structural = a stub object exposing `async def lookup(query, *, limit=20)` returning an
    #          object with `.hits` (each with `.symbol_id`) — avoids building a real StructuralService
    raise AssertionError("fill in")


async def test_resolver_exact_only(resolver):
    # FILL IN: "sym:pkg/a.py#g" → (state missing) + TARGET_UNRESOLVED mentioning "sym:pkg/a.py#f"


async def test_foreign_and_outside_root(resolver):
    # FILL IN: "file:../etc/passwd" and "remote::file:x.py" → TARGET_FOREIGN


async def test_ancestors_of_symbol(resolver):
    # FILL IN: == ["file:pkg/a.py", "dir:pkg", "dir:."]


async def test_dir_expansion_completeness(resolver, tmp_path):
    # FILL IN: add tmp_path/pkg/b.py with no page → expand_dir("dir:pkg") == ([...], False); with page → True;
    #          "dir:pk" must not include pkg/ files (segment semantics)
```

### FILL IN checklist
- [ ] `_split` prefix/namespace handling
- [ ] `resolve` missing/resolved branches + suggestions — AC7
- [ ] `ancestors_of`, `expand_dir` — spec §3 M4
- [ ] fixture + tests

---

## Acceptance Criteria

- [ ] Unresolved id ⇒ `TARGET_UNRESOLVED` with suggestions; foreign / escaping path ⇒ `TARGET_FOREIGN`.
- [ ] Dir expansion uses path segments and reports `complete=False` when any descendant file lacks a page.
- [ ] `ancestors_of` gives file → dirs → `dir:.`.
- [ ] No `list_pages`, no `lookup()`-based acceptance.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_scope.py -q`

---

## Test Specification

See blueprint test block (spec §4 `test_resolver_exact_only`).

---

## Agent Instructions

1. Worktree `feat-FEAT-784-sdd-decision-audit`; TASK-4997 `done`.
2. Implement; complete FILL INs; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the two files; `scripts/sdd/close_task.sh TASK-5002 sdd-decision-audit verified`.

---

## Completion Note

Seat: opus(native) · Backend: native · Model: opus · Attempts: 1 · Duration: 57s · Tokens: n/a

- Delivered files match the task list; no review fixes.
- Merge-tier validation (chunk 1): 230 passed, 1 failed — pre-existing env-gated `test_backend_parity_is_reported` (fails identically on origin/dev without live ArangoDB/Postgres).
