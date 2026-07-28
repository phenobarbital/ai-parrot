# TASK-1968: Promote the LLM backend catalog into the package + shim

**Feature**: FEAT-388 — `parrot devloop` CLI Homologation
**Spec**: `sdd/specs/devloop-cli-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none *(external gate: the in-flight Google/agy dispatcher WIP
must be merged to `dev` first — it modifies `examples/dev_loop/llm_catalog.py`)*
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (goal G1). The dev-loop backend/model catalog lives in
`examples/dev_loop/llm_catalog.py`, so the CLI cannot import it. Moving it
into `parrot/flows/dev_loop/catalog.py` gives web console and CLI one source
of truth; a re-export shim keeps `server.py` (`import llm_catalog`,
`server.py:157`) working unchanged.

---

## Scope

- Move `examples/dev_loop/llm_catalog.py` **verbatim** to
  `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py` (no renames, no
  refactors — only the module docstring may note the new home).
- Rewrite `examples/dev_loop/llm_catalog.py` as a thin shim that re-exports
  every public name from `parrot.flows.dev_loop.catalog` at module level.
- Write the shim-integrity test.

**NOT in scope**: consuming the catalog from the CLI (TASK-1970/1971);
touching `server.py`; changing any backend entry or default.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py` | CREATE | Verbatim move of the catalog |
| `examples/dev_loop/llm_catalog.py` | MODIFY | Becomes re-export shim |
| `packages/ai-parrot/tests/flows/dev_loop/test_catalog.py` | CREATE | Shim + catalog tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-28 on `dev` @ `623f0a6`. **The source file carries
> uncommitted WIP** (a Google/Antigravity backend was being added and its
> naming was still shifting — the test file was renamed
> `test_agy_dispatcher.py` → `test_google_coding_dispatcher.py` mid-review).
> **Re-verify the backend id (`agy` or its final name) and all line numbers
> after that WIP lands, before moving the file.**

### Existing Signatures to Use

```python
# examples/dev_loop/llm_catalog.py (public surface to move + re-export)
JUDGE_BACKENDS: Tuple[str, ...]           # :37
ADVERSARIAL_BACKEND: str                  # :43
PRIMARY_REVIEW_BACKENDS: Tuple[str, ...]  # :47
class BackendInfo:                        # :51 (frozen dataclass)
BACKENDS: Tuple[BackendInfo, ...]         # :83
def get_backend(backend_id: str) -> Optional[BackendInfo]:           # :183
def backends_for_role(role: str) -> List[BackendInfo]:               # :188
def effective_default_model(backend, config_getter=None) -> str:     # :201
def default_judge_panel_payload(config_getter=None) -> List[Dict[str, str]]:  # :243
def catalog_payload(config_getter=None) -> Dict[str, Any]:           # :272
```

`server.py` accesses these as module attributes (`llm_catalog.X`) at
`server.py:157,290,295,301,483,833,836,872,875,967` — the shim must define
every name at module level.

### Does NOT Exist

- ~~`llm_catalog.ROLES`~~ — role filtering is `backends_for_role()` only.
- ~~`parrot/flows/dev_loop/catalog.py`~~ — this task creates it.
- The catalog imports only `parrot.conf` + stdlib — it must stay free of
  aiohttp/server imports after the move.

---

## Implementation Notes

### Key Constraints
- The moved module must not trigger heavy imports at package-import time —
  check what `parrot/flows/dev_loop/__init__.py` eagerly imports and do NOT
  add `catalog` to its eager exports (import it as a submodule:
  `from parrot.flows.dev_loop import catalog`).
- Shim pattern: explicit `from parrot.flows.dev_loop.catalog import (...)`
  listing every public name (no `import *` — keeps linting honest), plus
  `__all__`.

### References in Codebase
- `examples/dev_loop/server.py:157` — `import llm_catalog` (sys.path-based).
- `packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py` —
  must keep passing untouched.

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop import catalog` works; catalog behavior
      byte-identical (same BACKENDS ids, same defaults).
- [ ] Shim test: every public name on the shim `is` the same object as on
      `parrot.flows.dev_loop.catalog`.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes unchanged.
- [ ] `ruff check` clean on both files.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_catalog.py
PUBLIC_NAMES = [
    "BACKENDS", "JUDGE_BACKENDS", "ADVERSARIAL_BACKEND",
    "PRIMARY_REVIEW_BACKENDS", "BackendInfo", "get_backend",
    "backends_for_role", "effective_default_model",
    "default_judge_panel_payload", "catalog_payload",
]

def test_shim_reexports_identical_objects():
    import importlib, sys
    sys.path.insert(0, "examples/dev_loop")
    shim = importlib.import_module("llm_catalog")
    from parrot.flows.dev_loop import catalog
    for name in PUBLIC_NAMES:
        assert getattr(shim, name) is getattr(catalog, name)

def test_backends_have_unique_ids():
    from parrot.flows.dev_loop import catalog
    ids = [b.id for b in catalog.BACKENDS]
    assert len(ids) == len(set(ids))
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify the Google/agy dispatcher WIP has merged
   (clean `git status` on the touched files) before moving the catalog
3. **Verify the Codebase Contract** — re-grep every line number first
4. **Update status** in `sdd/tasks/index/devloop-cli-homologation.json`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index**, **fill the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
