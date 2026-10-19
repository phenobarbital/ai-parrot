# TASK-4473: Role catalog and saved queries (M7)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4467
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 + AC19: the role-filtered view the LLM sees; member-right checks on every referenced member (incl. filters/order/dimension values) with ≤3 suggestions among ALLOWED members; saved-query expansion before compile; a governed model exposes nothing without an authorized subject.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py`: `RoleCatalog` (`visible_members`, `check_query_rights`, `expand_saved_query`, `search`).
- Write `test_catalog.py`.

**NOT in scope**: PBAC manifest authorization (the toolkit passes `authorized=` after calling `PbacGate.authorize_manifest`, TASK-4477).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py` | CREATE | role-filtered catalog |
| `packages/ai-parrot-semantic/tests/test_catalog.py` | CREATE | catalog tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
import difflib
from parrot.semantic.loader import LoadedModel                     # TASK-4467
from parrot.semantic.models import SemanticQuery, ModelMember      # TASK-4464
from parrot.semantic.errors import SemanticAccessError, SemanticValidationError   # TASK-4464
```

### Existing Signatures to Use
```python
# no core signature used
```

### Does NOT Exist
- ~~Suggestions drawn from all members~~ — only from members the subject may see (never leak hidden names).
- ~~`RoleCatalog.durable()`~~ — the spec text places `durable` near M7 by layout only; it belongs to `SemanticAuditLedger` (TASK-4474).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/catalog.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_catalog.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Suggestions: top-3 by `difflib.SequenceMatcher(None, a, b).ratio()` among allowed members (spec §3 delegation table).

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Write `RoleCatalog` per the skeleton — *why*: AC19.
2. Write tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py` (CREATE)
```python
"""Role-filtered catalog, member-right checks and saved-query expansion (spec §3 Module 7)."""
from __future__ import annotations

import difflib
import logging

from .errors import SemanticAccessError, SemanticValidationError
from .loader import LoadedModel
from .models import ModelMember, SemanticQuery


class RoleCatalog:
    def __init__(self, models: dict[str, LoadedModel]) -> None:
        self.models = models
        self.logger = logging.getLogger(__name__)

    def visible_members(self, model: str, roles: frozenset[str], *, authorized: bool) -> list[ModelMember]:
        """Allowed members only; a governed model with authorized=False exposes nothing (not even names)."""
        # FILL IN: ungoverned -> all members; governed and not authorized -> []; else filter by
        #          policy.allowed_members(roles, members); hide members whose mask hides them from projection
        raise NotImplementedError

    def check_query_rights(self, query: SemanticQuery, roles: frozenset[str]) -> None:
        """Every metric/dimension/time-dimension/filter/order member must be allowed."""
        # FILL IN: collect referenced names (walk FilterGroup recursively); first disallowed ->
        #   SemanticAccessError("member_not_granted", details={"member": n, "suggestions": self._suggest(...)})
        raise NotImplementedError

    def expand_saved_query(self, query: SemanticQuery) -> SemanticQuery:
        """Replace `saved_query` with the stored query (same model); unknown name -> SemanticValidationError."""
        # FILL IN: copy limit/offset overrides from the request onto the stored query only if set
        raise NotImplementedError

    def search(self, text: str, roles: frozenset[str], model: str | None = None, *,
               authorized: dict[str, bool] | None = None) -> list[dict]:
        """Case-insensitive substring + difflib ranking over visible members and descriptions."""
        # FILL IN: only models whose authorized[...] is True (governed) or ungoverned
        raise NotImplementedError

    @staticmethod
    def _suggest(name: str, allowed: list[str]) -> list[str]:
        ranked = sorted(allowed, key=lambda a: difflib.SequenceMatcher(None, name, a).ratio(), reverse=True)
        return ranked[:3]
```
**Why**: spec §3 M7 skeleton; `search` gains keyword-only `authorized` so governed models stay invisible (AC19) — record as a deviation.

### FILL IN checklist
- [ ] `visible_members` — bounded by AC19.
- [ ] `check_query_rights` — bounded by AC19 + spec M7.
- [ ] `expand_saved_query`.
- [ ] `search`.

---

## Acceptance Criteria

- [ ] `test_catalog_role_filtering_and_suggestions` and `test_saved_query_expansion` pass.
- [ ] A governed model with `authorized=False` returns `[]` from `visible_members` and nothing from `search` (AC19).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_catalog.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_catalog.py
from ._models import models_dir, loaded_models  # noqa: F401
from parrot.semantic.catalog import RoleCatalog


def test_catalog_role_filtering_and_suggestions(loaded_models):
    cat = RoleCatalog(loaded_models)
    assert cat.visible_members("orders", frozenset({"analyst"}), authorized=False) == []
    # FILL IN: authorized analyst sees only granted members; unknown "revenu" -> suggestions ["revenue", ...] (<=3)


def test_saved_query_expansion(loaded_models):
    # FILL IN: saved_query="monthly_revenue" expands; unknown name -> SemanticValidationError
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4473 — Role catalog and saved queries (M7)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4473 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4473
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: opus (native) · Attempts: 1 · Tokens: 61k
- Validation: merge-tier ad0839b5:wave5:merge completed exit 0 (24 passed); full satellite suite after review fix 53 passed.
- Review: coder-review:d50e7ac12860b5e38ad69018 — no corrections.
- Deviations (recorded per blueprint): search() takes keyword-only authorized=; unknown model raises SemanticValidationError('unknown_model'); expanded saved query with offset but no order_by raises 'offset_requires_order_by'.
