# TASK-4009: Lint engine core: models, rule protocol, context

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (first half). Creates the backend-neutral data model and the per-run context cache that every rule pack and the runner build on.

---

## Scope

- Create package `parrot.knowledge.lint` with a lazy `__init__.py` exporting the public names (incl. `LintRunner` from `.runner`, created by TASK-4010, resolved lazily so this task does not depend on it).
- Implement `Severity`, `Finding`, `FixResult`, `LintReport`, `LintOptions` (Pydantic v2) exactly as spec §2 Data Models.
- Implement the `LintRule` Protocol and `make_fingerprint()`.
- Implement `LintContext` lazy cache over a `BaseWikiStore`.
- Create empty `lint/packs/__init__.py` (docstring only) and the test package `tests/knowledge/lint/__init__.py`.
- Write unit tests.

**NOT in scope**: Runner (TASK-4010); any rule pack; routing; `default_rules()` (TASK-4019).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/__init__.py` | CREATE | Lazy public exports |
| `packages/ai-parrot/src/parrot/knowledge/lint/models.py` | CREATE | Finding/FixResult/LintReport/LintOptions |
| `packages/ai-parrot/src/parrot/knowledge/lint/rule.py` | CREATE | LintRule protocol + make_fingerprint |
| `packages/ai-parrot/src/parrot/knowledge/lint/context.py` | CREATE | LintContext |
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` | CREATE | Package marker (docstring only) |
| `packages/ai-parrot/tests/knowledge/lint/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot/tests/knowledge/lint/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore  # verified: wiki/store.py:525
from parrot.knowledge.wiki.file_store import InMemoryWikiStore  # verified: wiki/file_store.py:73 (tests)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                              # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # :544
    async def add_edges(self, edges: list[tuple]) -> int: ...          # :547  (src, dst, rel, provenance)
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # :565
    async def list_pages(self, category=None, limit: int = 100, origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...  # :568
    async def dump_pages(self) -> list[dict[str, Any]]: ...            # :590  keys: concept_id,node_id,title,category,summary,body,source_id,token_count,created_at,updated_at,content_hash
    async def dump_edges(self) -> list[dict[str, Any]]: ...            # :593  keys: src,dst,rel
    async def orphan_sources(self) -> list[str]: ...                   # :600
    async def broken_edges(self) -> list[dict[str, Any]]: ...          # :603  keys: src,dst,rel
    async def missing_bodies(self) -> list[str]: ...                   # :606
# wiki/file_store.py:88  InMemoryWikiStore.__init__(self, bundle_dir: str | Path, wiki_name: str = '')
```

### Does NOT Exist
- ~~`provenance` in `dump_edges()` rows~~ — SQLite `dump_edges` returns only `src, dst, rel` (`wiki/store.py:2222-2226`)
- ~~`origin` in `dump_pages()` rows~~ — use `list_pages(origin=[...])` (`wiki/store.py:2038`) to find memory pages
- ~~`memories` / `notes` tables~~ — memories are `pages.origin='memory'`
- ~~`parrot.knowledge.lint`~~ — does not exist before this task

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/rule.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/context.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Write `models.py` first — *why*: rule.py and context.py import from it.
2. Write `rule.py` with a `typing.Protocol` (`runtime_checkable`) — *why*: packs are plain classes, not subclasses; the runner duck-types them.
3. Write `context.py`; cache each loader result on first await — *why*: several rules read the same pages/edges, one dump per run (spec §2).
4. Write `__init__.py` with a `__getattr__` lazy map — *why*: `LintRunner` lives in a module created by another task; eager import would break until it lands.
5. Write tests and run them.

### `packages/ai-parrot/src/parrot/knowledge/lint/models.py` (CREATE)
```python
"""Lint engine data models (FEAT-625)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "error"]
SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "error": 2}


class Finding(BaseModel):
    """One lint finding produced by a rule."""

    rule_id: str
    severity: Severity
    subjects: list[str] = Field(default_factory=list)
    message: str
    fixable: bool = False
    fingerprint: str
    data: dict[str, Any] = Field(default_factory=dict)


class FixResult(BaseModel):
    """Outcome of applying one fix."""

    fingerprint: str
    applied: bool
    detail: str = ""


class LintOptions(BaseModel):
    """Options controlling one lint run."""

    rules: list[str] | None = None
    skip: list[str] = Field(default_factory=list)
    fix: bool = False
    llm: bool = False
    llm_model: str | None = None
    llm_max_pairs: int = 50
    ledger: bool = True
    notes: bool = True
    ledger_cap_per_rule: int = 20
    fail_on: Severity | None = "error"
    export_dir: Path | None = None
    report_dir: Path | None = None


class LintReport(BaseModel):
    """Result of a lint run (findings are what remains after fixes)."""

    wiki_name: str = ""
    backend: str = ""
    rules_run: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    fixed: list[FixResult] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    started_at: str = ""
    duration_ms: int = 0
    routing: dict[str, int] = Field(default_factory=dict)
```

### `packages/ai-parrot/src/parrot/knowledge/lint/rule.py` (CREATE)
```python
"""LintRule protocol and fingerprint helper (FEAT-625)."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from parrot.knowledge.lint.models import Finding, FixResult, Severity

if TYPE_CHECKING:
    from parrot.knowledge.lint.context import LintContext


def make_fingerprint(rule_id: str, subjects: Sequence[str]) -> str:
    """Return a stable sha1 over ``rule_id`` and the SORTED subjects."""
    payload = rule_id + "\x1f" + "\x1f".join(sorted(subjects))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


@runtime_checkable
class LintRule(Protocol):
    """A single lint rule; packs are plain classes satisfying this protocol."""

    rule_id: str
    pack: str
    default_severity: Severity

    async def check(self, ctx: "LintContext") -> list[Finding]:
        """Return findings; MUST NOT mutate the store."""
        ...

    async def fix(self, ctx: "LintContext", finding: Finding) -> FixResult | None:
        """Apply an idempotent safe fix, or return None when the rule never fixes."""
        ...
```

### `packages/ai-parrot/src/parrot/knowledge/lint/context.py` (CREATE)
```python
"""Per-run lazy cache over the wiki store (FEAT-625)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.knowledge.lint.models import LintOptions
from parrot.knowledge.wiki.store import BaseWikiStore  # verified: wiki/store.py:525


class LintContext:
    """Lazily loads and caches pages/edges/memories for one lint run."""

    def __init__(
        self,
        store: BaseWikiStore,
        *,
        root: Path | None = None,
        config: Any | None = None,
        options: LintOptions | None = None,
    ) -> None:
        self.store = store
        self.root = root
        self.config = config
        self.options = options or LintOptions()
        self.logger = logging.getLogger(__name__)
        self._pages: list[dict[str, Any]] | None = None
        self._edges: list[dict[str, Any]] | None = None
        self._memories: list[dict[str, Any]] | None = None
        self.extras: dict[str, Any] = {}

    async def pages(self) -> list[dict[str, Any]]:
        """All pages with bodies (``store.dump_pages``), cached."""
        if self._pages is None:
            self._pages = await self.store.dump_pages()
        return self._pages

    async def edges(self) -> list[dict[str, Any]]:
        """All edges (``store.dump_edges``: src, dst, rel), cached."""
        if self._edges is None:
            self._edges = await self.store.dump_edges()
        return self._edges

    async def page_ids(self) -> set[str]:
        """Set of every ``concept_id`` in the plane."""
        return {str(p["concept_id"]) for p in await self.pages()}

    async def memories(self) -> list[dict[str, Any]]:
        """Memory page stubs (``origin='memory'``), cached."""
        if self._memories is None:
            # FILL IN: page through list_pages(origin=["memory"], limit=...) — bounded by: no silent truncation; use a limit >= stats()["pages"]
            raise NotImplementedError
        return self._memories

    def invalidate(self) -> None:
        """Drop every cache (called by the runner after fixes)."""
        self._pages = None
        self._edges = None
        self._memories = None
        self.extras.clear()
```

### `packages/ai-parrot/src/parrot/knowledge/lint/__init__.py` (CREATE)
```python
"""Shared, backend-agnostic lint engine for the wiki graph (FEAT-625)."""
from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "Finding": "parrot.knowledge.lint.models",
    "FixResult": "parrot.knowledge.lint.models",
    "LintOptions": "parrot.knowledge.lint.models",
    "LintReport": "parrot.knowledge.lint.models",
    "Severity": "parrot.knowledge.lint.models",
    "LintRule": "parrot.knowledge.lint.rule",
    "make_fingerprint": "parrot.knowledge.lint.rule",
    "LintContext": "parrot.knowledge.lint.context",
    "LintRunner": "parrot.knowledge.lint.runner",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Resolve public names lazily."""
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_LAZY[name]), name)
```

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` (CREATE)
```python
"""Lint rule packs (FEAT-625). ``default_rules()`` is added by TASK-4019."""
```

### `packages/ai-parrot/tests/knowledge/lint/__init__.py` (CREATE)
```python

```

**Why this shape**: Shapes are fixed by spec §2 Data Models; do not rename fields — every pack and the CLI JSON output depend on them. `make_fingerprint` sorts subjects so ledger/notes dedup is order-independent (spec M8).

### FILL IN checklist
- [ ] `context.py::LintContext.memories` — paging strategy; bounded by: no truncation

---

## Acceptance Criteria

- [ ] `Finding`, `LintOptions`, `LintReport` validate per spec §2
- [ ] `make_fingerprint` is order-independent
- [ ] `LintContext` caches (one `dump_pages` call per run until `invalidate()`)
- [ ] `from parrot.knowledge.lint import Finding, LintContext` works
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/lint` clean
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_models.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_models.py
import pytest
from parrot.knowledge.lint.models import Finding, LintOptions
from parrot.knowledge.lint.rule import make_fingerprint


def test_fingerprint_stable():
    assert make_fingerprint("r", ["b", "a"]) == make_fingerprint("r", ["a", "b"])


def test_options_defaults():
    o = LintOptions()
    assert o.fix is False and o.llm_max_pairs == 50 and o.fail_on == "error"


async def test_context_caches(tmp_path):
    # FILL IN: InMemoryWikiStore(tmp_path) with a spy on dump_pages; await ctx.pages() twice -> 1 call
    ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4009 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

## Completion Note

Implemented by gpt-5.6-terra (codex), 1 attempt. Merged via coder_merge. Merge-tier run: 1520 passed, 2 failed — both in tests/sdd/test_ledger_lifecycle_acceptance.py, unrelated to this task (pass on main checkout, fail in worktree; filed issue:dc663a223799). Closed via close_task.sh, not finalize_task (no green validation ref).
