# TASK-745: Update examples + internal call sites for new NavigatorToolkit constructor

**Feature**: FEAT-106 — NavigatorToolkit ↔ PostgresToolkit Interaction
**Spec**: `sdd/specs/navigatortoolkit-postgrestoolkit-interaction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-744
**Assigned-to**: unassigned

---

## Context

TASK-744 migrates `NavigatorToolkit` from `connection_params: dict` to
`dsn: str` (**breaking change**) and changes the tool prefix from `""`
to `"nav"`. Every example, loader, tool registry entry, or doc snippet
that constructs `NavigatorToolkit` or references its tool names must be
updated in lockstep so downstream users don't trip on import.

Implements **Module 7** of the spec.

---

## Scope

- Grep the repo for `NavigatorToolkit(` call sites. For each:
  - Replace `connection_params=...` with `dsn="postgres://..."`
    (use an env-var default where the original used env-var lookup).
  - Delete any `await toolkit._get_db()` / `await toolkit._query(...)`
    / `await toolkit._exec(...)` lines — they no longer exist.
  - If the example inspects `toolkit.get_tools()` output by name,
    update the names to the `nav_` prefix.
- Grep for the previous tool names (`create_program`, `create_module`,
  `create_dashboard`, `create_widget`, `update_*`, etc.) used as
  **strings** in any registry, routing table, or workflow config. Add
  the `nav_` prefix where they reference the NavigatorToolkit tools
  (not the Navigator HTTP routes or other namespaces — read each hit
  carefully).
- Known starting points (verify via grep before editing):
  - `examples/navigator_agent.py`
  - `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (tool registry)
  - Any `bots/*.yaml` or `agents/*.yaml` that reference Navigator tools
  - `docs/` folder (if any markdown references the old names)

**NOT in scope**:
- Modifying `NavigatorToolkit` itself — TASK-744.
- Modifying `PostgresToolkit` — TASK-743.
- Writing new integration tests — TASK-746.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/navigator_agent.py` | MODIFY | Switch constructor from `connection_params=` to `dsn=` |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY (if referenced) | Update any `TOOL_REGISTRY` entry that pre-filters Navigator tool names |
| _various (via grep)_ | MODIFY | Rename `create_program` → `nav_create_program` (etc.) in string-based configs |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.navigator import NavigatorToolkit
# verified at: packages/ai-parrot-tools/src/parrot_tools/navigator/__init__.py:25
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py (POST-TASK-744)
class NavigatorToolkit(PostgresToolkit):
    tool_prefix: str = "nav"
    def __init__(
        self,
        dsn: str,
        default_client_id: int = 1,
        user_id: Optional[int] = None,
        confirm_execution: bool = False,
        page_index: Optional[Any] = None,
        builder_groups: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None: ...
```

### Does NOT Exist

- ~~`NavigatorToolkit(connection_params={...})` (post-refactor)~~ — raises `TypeError`.
- ~~`create_program` as a bare tool name (post-refactor)~~ — it's `nav_create_program`.
- ~~Any HTTP route rename~~ — the Navigator REST API routes (if any) are unrelated to toolkit tool names; do NOT rename them.

---

## Implementation Notes

### Grep patterns to run first

```bash
# call sites
grep -rn "NavigatorToolkit(" --include="*.py" .
grep -rn "connection_params" packages/ai-parrot-tools/src/parrot_tools/navigator/
grep -rn "connection_params" examples/

# tool name references (be conservative — only rename when context is clearly a toolkit tool name)
grep -rnE '"(create|update|get|list|clone|assign|find|search)_(program|module|dashboard|widget)[s]?"' --include="*.py" --include="*.yaml" --include="*.yml" .
```

Before renaming a string match, inspect the surrounding code — it may
be a REST path or a Navigator DB column, not a toolkit tool name.

### Key Constraints

- Do NOT commit a DSN with real credentials. Use
  `os.getenv("NAVIGATOR_PG_DSN")` or a documented placeholder string.
- Examples must run — validate by at minimum `python -c "from examples import navigator_agent"`.
  A full runtime check requires a live PG (defer to TASK-746 integration).
- Keep the example's top-level prose / comments updated when the
  construction snippet changes — don't leave stale docs pointing at
  `connection_params`.

### References in Codebase

- `examples/navigator_agent.py` — primary target
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py` — tool registry

---

## Acceptance Criteria

- [ ] `grep -rn "connection_params" packages/ai-parrot-tools/src/parrot_tools/navigator/ examples/` returns 0 matches
- [ ] `grep -rn "from asyncdb import AsyncPool" packages/ai-parrot-tools/src/parrot_tools/navigator/` returns 0 matches
- [ ] `examples/navigator_agent.py` imports and instantiates `NavigatorToolkit(dsn=…)` cleanly
- [ ] `python -c "from examples import navigator_agent"` runs without ImportError
- [ ] Tool-registry entries that previously held `"create_program"` (etc.) as Navigator tool names now hold `"nav_create_program"` — verified by grep
- [ ] No behavioural regression outside the renamed surfaces (no unrelated edits)

---

## Test Specification

This task mostly edits scripts — no dedicated unit-test module. A
smoke-import in the existing test suite is sufficient:

```python
# tests/unit/test_navigator_examples.py (new, optional)
def test_navigator_agent_example_imports():
    import examples.navigator_agent as na  # should import cleanly
    assert hasattr(na, "__name__")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — Section 3 Module 7 is brief; most context lives in TASK-744
2. **Check dependencies** — TASK-744 must be `done`
3. **Verify the Codebase Contract** — run the grep patterns above before editing anything
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Edit one file at a time**, commit after each, so bisecting is easy
6. **Verify** all acceptance criteria (grep returning 0 is the strongest signal)
7. **Move this file** to `tasks/completed/TASK-745-navigator-examples-update.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-17
**Notes**:
- Updated `examples/navigator_agent.py`: replaced `CONNECTION_PARAMS` dict with
  `NAVIGATOR_DSN` string using `NAVIGATOR_PG_DSN` env var; updated
  `NavigatorToolkit(connection_params=..., ...)` to `NavigatorToolkit(dsn=NAVIGATOR_DSN, ...)`.
- Updated `packages/ai-parrot-tools/src/parrot_tools/navigator/__init__.py`:
  replaced `connection_params={...}` with `dsn="postgres://..."` in module docstring.
- `TOOL_REGISTRY` in `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
  maps toolkit class paths only (not individual tool names) — no changes needed.
- All acceptance criteria greps return 0 matches for live `connection_params` usage.

**Deviations from spec**: none
