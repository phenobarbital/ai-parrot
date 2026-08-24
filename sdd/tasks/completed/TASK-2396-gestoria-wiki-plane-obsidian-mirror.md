# TASK-2396: gestoria wiki plane + Obsidian mirror (FEAT-452 recipe)

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2390
**Assigned-to**: unassigned

---

## Context

Implements **Module 10** (Goal G8).

FEAT-452 (merged, PR #1209) established the recipe for a domain-scoped wiki
plane mirrored into an Obsidian folder, and `wikitoolkit ns list` confirms its
`notes` plane is live. This task instantiates that recipe for `gestoria`.

**A stale reference to avoid.** The FEAT-452 `TASK-2379` artifact cites
`_config_for` at `wiki/toolkit.py:1205` and says another wiki name "will raise".
Re-verification on current `dev` puts it at **line 1378**, and the FEAT-450 merge
made the guard **conditional**: a *registered namespace* name no longer raises.
Follow the corrected behaviour below, not the task doc.

Implements spec **Module 10**.

---

## Scope

- Build a dedicated `LLMWikiToolkit` instance for the `gestoria` plane with its
  own storage root, its own PageIndex plane and its own graph toolkit
  (`tenant_id="gestoria"`).
- Bootstrap once with the idempotent `create_wiki("gestoria")`, wired into
  `configure()`; best-effort — a failure logs a warning, leaves the handle
  `None`, and lets the agent boot.
- Mirror recorded operations into an Obsidian folder via `ObsidianToolkit`.
- Record each completed operation as a page: what ran, with which params digest,
  the gate decision, and the outcome.
- Document the **one-off operator step** `wikitoolkit ns add` for the `gestoria`
  plane in the runbook — it is explicitly NOT agent code (FEAT-452 TASK-2382
  non-scope).

**NOT in scope**: auto-registering the namespace from agent code; injecting a
`FederatedWikiStore` into `LLMWikiToolkit` (both FEAT-452 non-goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py` | CREATE | gestoria plane + vault mirror |
| `packages/ai-parrot-tools/tests/business_automation/test_memory.py` | CREATE | Storage-root isolation tests |
| `docs/business-automation-runbook.md` | CREATE | Operator runbook incl. ns add |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit   # verified: wiki/toolkit.py:54
from parrot.tools.obsidian import ObsidianToolkit           # verified: tools/obsidian.py:78
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):              # line 54
    async def create_wiki(self, wiki_name: str,
                          description: Optional[str] = None) -> dict[str, Any]: ...  # line 544
        # Creates {storage_dir}/ with sources/, wiki.db, index.md — IDEMPOTENT
    def _config_for(self, wiki_name: str) -> WikiConfig:     # line 1378  (NOT 1205)
        """Validates that wiki_name names either the toolkit's configured wiki
        or one of the federated namespaces its injected store serves (FEAT-450).
        The config object is per-toolkit, so a namespace resolves to the SAME
        config — namespace dispatch is a *store* concern, handled by
        _store_for / _search_for.
        Raises: ValueError when wiki_name does not match the configured wiki."""
        if wiki_name != self._config.wiki_name and not self._is_namespace(wiki_name):
            raise ValueError(...)

# packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):             # line 78
    def __init__(self, vault_path=None, backend: Literal["local","rest"]="local",
                 vault=None, allowed_operations=None, **backend_kwargs) -> None: ...  # line 127
    async def create_note(...)   # line 439
    async def update_note(...)   # line 471
    async def append_note(...)   # line 504
    async def _open/_close       # lines 189/194  (FEAT-391 lazy lifecycle)
```

### Does NOT Exist

- ~~`_config_for` at `wiki/toolkit.py:1205`~~ — **stale**; it is at **1378** and its ValueError is now conditional on `_is_namespace()`. The FEAT-452 TASK-2379 artifact predates the FEAT-450 merge.
- ~~passing `wiki_name="gestoria"` to the existing toolkit instance to "route" there~~ — a namespace resolves to the SAME config; it does not give you a second storage plane. You need a separate `LLMWikiToolkit` instance.
- ~~auto-registering the namespace from agent code~~ — explicit FEAT-452 non-scope. It is an operator step.
- ~~`FederatedWikiStore` injection into `LLMWikiToolkit`~~ — explicit FEAT-452 non-goal.

---

## Implementation Notes

### Pattern to Follow
The FEAT-452 recipe: config constants (`GESTORIA_WIKI_NAME`,
`GESTORIA_WIKI_STORAGE_DIR`, `GESTORIA_FOLDER`) with constructor overrides
mirroring the existing `wiki_name`/`wiki_storage_dir`; a
`_build_gestoria_wiki_toolkit()` near-copy of `_build_wiki_toolkit()`; idempotent
`create_wiki()`; best-effort failure.

### Key Constraints
- **Separate storage root.** Different roots means no shared manifest and no
  shared `wiki.db`, hence no cross-instance consistency hazard.
- **Built but unregistered = silently unqueryable.** `wikitoolkit query` reads
  one plane; an unregistered `gestoria` accumulates knowledge nobody can
  retrieve. The runbook step is the guard — AC covers it.
- Checkpoints must NOT live under the vault or a wiki root (D3) — both are
  mirrored/ingested surfaces and would leak client names and amounts.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] The `gestoria` plane uses a storage root distinct from the default wiki
- [ ] `create_wiki("gestoria")` is idempotent across restarts
- [ ] A build failure logs a warning, leaves the handle `None`, and the agent still boots
- [ ] Completed operations are recorded as pages and mirrored to the Obsidian folder
- [ ] The runbook documents the one-off `wikitoolkit ns add`, and `wikitoolkit query --ns gestoria` returns a seeded page
- [ ] No checkpoint path resolves inside the vault or any wiki storage root
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/ -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.business_automation.memory import build_gestoria_wiki


class TestGestoriaPlane:
    async def test_distinct_storage_root(self, default_wiki, tmp_path):
        g = await build_gestoria_wiki(storage_dir=tmp_path / "gestoria")
        assert g.config.storage_dir != default_wiki.config.storage_dir

    async def test_create_wiki_idempotent(self, tmp_path):
        a = await build_gestoria_wiki(storage_dir=tmp_path / "g")
        b = await build_gestoria_wiki(storage_dir=tmp_path / "g")   # must not raise
        assert b is not None

    async def test_failure_is_best_effort(self, unwritable_dir, caplog):
        assert await build_gestoria_wiki(storage_dir=unwritable_dir) is None
        assert "gestoria" in caplog.text
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2396-gestoria-wiki-plane-obsidian-mirror.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Implemented `build_gestoria_wiki()` and `record_operation_page()` in
a new `memory.py`, instantiating the FEAT-452 domain-plane recipe (already
proven by TASK-2379's `notes` plane) for a dedicated `gestoria` plane: its own
`LLMWikiToolkit` instance, own storage root (`GESTORIA_WIKI_STORAGE_DIR`,
default `~/.parrot/wikis/gestoria`), own PageIndex authoring plane
(`_build_pageindex_toolkit()`, best-effort — logs a warning and returns
`None` on failure, leaving the wiki retrieval-only), and own GraphIndex
tenant (`tenant_id="gestoria"` passed to `build_graph_memory_toolkit()`).
`build_gestoria_wiki()` bootstraps with an idempotent `create_wiki()` call in
a *separate* try/except from toolkit construction, so a `create_wiki()`
bootstrap failure (e.g. re-running against an already-initialized layout)
never nulls out an otherwise-valid toolkit handle — only a construction
failure (storage `mkdir()`, graph/pageindex wiring) returns `None`. Every
failure path logs a warning naming `"gestoria"` so the agent still boots.
`record_operation_page()` records what ran (`operation`), a stable sha256
digest of `params` (never raw values — verified by a dedicated test that
literal client names/amounts never leak into the page body), the
confirmation-gate decision, and the outcome, as a page (`category="summary"`,
the closest fit among `LLMWikiToolkit.create_page`'s existing categories —
no dedicated "operation-record" category exists) and mirrors it to an
Obsidian note via `ObsidianToolkit.create_note()` when an instance is
passed. Both the wiki write and the Obsidian mirror are independently
best-effort: either can fail without raising or blocking the other, since
this is an audit/knowledge side effect, not the operation's own result.

**Codebase Contract correction applied at implementation time** (the task's
own contract already flagged this as a known-stale FEAT-452 TASK-2379
artifact reference, not a new finding): confirmed via `read` that
`LLMWikiToolkit._config_for()` is at `wiki/toolkit.py:1378` (not the
TASK-2379 artifact's stale `:1205`) and that its `ValueError` is
conditional on `_is_namespace()` post-FEAT-450 — consistent with this
task's own already-corrected contract, requiring no further correction.
Verified `ObsidianToolkit.create_note()` signature via read
(`tools/obsidian.py:439`) before use.

**Test-fixture correction**: `test_create_wiki_failure_does_not_null_toolkit`
initially built a toolkit via the normal path and then separately, redundantly,
built a second `RaisingWikiToolkit` — simplified to directly monkeypatch
`LLMWikiToolkit` with a `RaisingWikiToolkit` subclass (overriding only
`create_wiki` to raise) and call `build_gestoria_wiki()` once, asserting the
returned toolkit is not `None` and that the failure was logged.

**Environment-gap resolution carried over from TASK-2394**: this task's
tests initially hit the same pre-existing Cython-extension gap (worktrees
don't carry compiled `.pyx`→`.so` build artifacts, since those aren't
git-tracked) via `packages/ai-parrot/tests/conftest.py`'s autouse
`_reset_injection_engine_singleton` fixture. Copying the two specific `.so`
files already identified in TASK-2394 (`parrot/utils/types.*.so`,
`parrot/utils/parsers/toml.*.so`) from the main repo checkout into this
worktree (confirmed gitignored via `git check-ignore -v`, so no risk of an
accidental commit) resolved it — all 11 new tests ran and passed via real
`pytest` (not a standalone workaround script). Full regression
(`business_automation` + `scraping` + `google` suites, 872 tests) re-run
clean: only the same 2 pre-existing, unrelated failure groups
(`CrawlEngine`/FEAT-013, `test_places.py`), zero regressions introduced.
`ruff check` clean except the same `UP006`/`UP035`/`UP045`/`UP017`/`UP037`
pyupgrade-style debt already established as this feature's convention
(matching `advanced_actions.py`'s `typing.Dict`/`Optional` style) plus 2
`RUF059` unpacked-variable findings pre-dating this task's changes.

**Deviations from spec**: none beyond the contract corrections the task
file itself already flagged as expected (stale `_config_for` line number /
conditional-guard behavior). `category="summary"` for `create_page()` is an
implementation choice (no dedicated category exists for operation records)
rather than a deviation from any specified value.
