# TASK-5691: Error boundary for `op_procedure_next`; installer honours `procedure.enabled`

**Feature**: FEAT-899 — Procedure guards and plane — FEAT-891 review follow-ups
**Spec**: `sdd/specs/fixgroup-848b9a0ceee1.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:bab5aa4a8d70`

---

## Context

Spec §2 M4, M5 and M6 / §3 Modules 4–6 (review notes 6, 9 and 10 of `issue:bab5aa4a8d70`).

- `op_procedure_next` catches only `ValueError`/`OSError`. Any other failure while loading the plane or
  resolving (for example a `sqlite3` or `pydantic` error) escapes the `wiki_procedure_next` MCP tool.
- `_install_procedure_index_step` builds the plane even when `sdd/config.json` sets
  `procedure.enabled` to false.
- The FEAT-891 spec's `ProcedureManifest` model omits the shipped `uncovered_ok` field.

---

## Scope

- Add a second `except Exception` clause to `op_procedure_next` that returns an error result.
- Make `_install_procedure_index_step` skip the build when `procedure.enabled` is false.
- Add the `uncovered_ok` line to `ProcedureManifest` in `sdd/specs/procedural-graph-plane.spec.md` §2.
- Tests: `test_operation_reports_unexpected_error`, `test_install_skips_procedure_index_when_disabled`.

**NOT in scope**: replacing `asyncio.run` in the installer (spec Non-Goals, note 9); the text returned for
`ValueError`/`OSError`; any change to `procedure.build`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py` | MODIFY | error boundary |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | skip the build when disabled |
| `sdd/specs/procedural-graph-plane.spec.md` | MODIFY | one model line |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py` | MODIFY | one new test |
| `packages/ai-parrot/tests/sdd/test_procedure_assets.py` | MODIFY | one new test |

---

## Codebase Contract (Anti-Hallucination)

Verified against `909ec8aced`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/installer.py — lazy import inside the step (same style as installer.py:939 and :1600)
from parrot.sdd.config import load_sdd_config

# packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py — already imported
import asyncio                                                                  # line 5
from parrot.knowledge.wiki.procedure.operations import ProcedureNextInput, op_procedure_next   # lines 12-17
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane                # line 18

# packages/ai-parrot/tests/sdd/test_procedure_assets.py — already imported
from parrot.sdd.scripts import procedure                                        # line 16
# add:
from parrot.sdd.installer import _install_procedure_index_step                 # verified: installer.py:1284
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py
async def op_procedure_next(store: Any, params: ProcedureNextInput, **context: Any) -> OperationResult:   # line 90
#   `    except (ValueError, OSError) as exc:` / `        return OperationResult(text=str(exc), is_error=True)`   # lines 118-119
#   inside the try: `specs = await plane.specs()` on a `ProcedurePlane`, imported lazily from
#   parrot.knowledge.wiki.procedure.plane

# packages/ai-parrot/src/parrot/sdd/installer.py
def _install_procedure_index_step(root: Path, receipt: dict[str, Any]) -> list[str]:   # line 1284
#   try: `import asyncio`; `from parrot.sdd.scripts import procedure`; `counts = asyncio.run(procedure.build(root))` (line 1295)
#   except Exception → [f"procedure index: skipped ({type(exc).__name__}: {exc})"]

# packages/ai-parrot/src/parrot/sdd/config.py
class ProcedureSettings(BaseModel):          # line 25
    enabled: bool = True
class SddConfig(BaseModel):
    procedure: ProcedureSettings | None = None   # None means defaults (enabled)
def load_sdd_config(root: Path) -> SddConfig     # absent sdd/config.json → defaults; malformed → SddConfigError (a ValueError)

# packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py
def _project(root: Path, *, with_plane: bool) -> None:   # line 23 — calls asyncio.run, so use it from a SYNC test only

# packages/ai-parrot/tests/sdd/test_procedure_assets.py
def _installed(tmp_path: Path) -> Path:                  # line 24 — copies the packaged manifest to <tmp>/sdd/procedures/
```

### Does NOT Exist
- ~~`op_procedure_next` in `parrot/sdd/scripts/procedure.py`~~ — it lives in `parrot/knowledge/wiki/procedure/operations.py`.
- ~~a module-level logger in `operations.py`~~ — none; do not add logging, return the error in the result.
- ~~a sync `procedure.build`~~ — it is `async def`.
- ~~a `config` parameter on `_install_procedure_index_step`~~ — load the config inside the step.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "sdd/specs/procedural-graph-plane.spec.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_procedure_assets.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py#op_procedure_next",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_procedure_index_step",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#ProcedureSettings"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `asyncio.CancelledError` is a `BaseException`; `except Exception` must not swallow cancellation.
- The installer step never fails the install: the config load stays inside the existing `try`.
- The spec edit is exactly one added line; do not reflow the surrounding block.

---

## Implementation Blueprint

### Steps (in order)
1. Add the second `except` clause in `op_procedure_next` — *why*: a tool operation reports a failure,
   it never raises into the transport.
2. Check `procedure.enabled` at the top of the installer step's `try` — *why*: a disabled plane must not
   be built, and the check must run before the `procedure` module import.
3. Add the spec line.
4. Add the two tests, run the Validation Commands, `ruff check --fix` the four Python files.

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'except (ValueError, OSError) as exc:' …/operations.py)
# AFTER — insert below the two lines `    except (ValueError, OSError) as exc:` / `        return OperationResult(text=str(exc), is_error=True)` (verified: operations.py:118-119)
    except Exception as exc:  # noqa: BLE001 — a tool operation reports failures, it never raises
        return OperationResult(text=f"{type(exc).__name__}: {exc}", is_error=True)
```
**Why**: keeping the first clause leaves the `ValueError`/`OSError` text unchanged. Update the function
docstring to say it never raises.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'counts = asyncio.run(procedure.build(root))' …/installer.py)
# REPLACE the body of the `try:` in `_install_procedure_index_step` (verified: installer.py:1290-1295)
    try:
        import asyncio

        from parrot.sdd.config import load_sdd_config

        settings = load_sdd_config(root).procedure
        if settings is not None and not settings.enabled:
            return ["procedure index: skipped (procedure.enabled is false)"]

        from parrot.sdd.scripts import procedure

        counts = asyncio.run(procedure.build(root))
```
**Why**: the action text is fixed by spec §2 M5. Update the docstring's first line accordingly.

### `sdd/specs/procedural-graph-plane.spec.md` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'procedures: list\[ProcedureSpec\] = \[\]' sdd/specs/procedural-graph-plane.spec.md)
# AFTER — insert below `    procedures: list[ProcedureSpec] = []    # ids written without the prefix; the producer adds it` (verified: procedural-graph-plane.spec.md:298)
    uncovered_ok: list[str] = []            # /sdd-* commands deliberately left without a procedure node
```

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py` (MODIFY)
```python
# AFTER — append at the end of the file
def test_operation_reports_unexpected_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure outside ValueError/OSError becomes an error result instead of escaping the tool."""
    # FILL IN: `_project(tmp_path, with_plane=True)`, monkeypatch `ProcedurePlane.specs` with an async
    #   function raising RuntimeError("boom"), run op_procedure_next through asyncio.run and assert
    #   result.is_error and "RuntimeError: boom" in result.text — sync test, because `_project` calls asyncio.run
```

### `packages/ai-parrot/tests/sdd/test_procedure_assets.py` (MODIFY)
```python
# AFTER — append at the end of the file; add `_install_procedure_index_step` to the installer import
def test_install_skips_procedure_index_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A disabled procedure plane is not built by the installer step."""
    # FILL IN: `_installed(tmp_path)`, write sdd/config.json with {"procedure": {"enabled": false}},
    #   monkeypatch `procedure.build` to an async function that raises AssertionError, assert the step
    #   returns exactly ["procedure index: skipped (procedure.enabled is false)"] and writes no .parrot/procedure
```

### FILL IN checklist
- [ ] two test bodies

---

## Acceptance Criteria

- [ ] `op_procedure_next` returns `is_error=True` with `RuntimeError: boom` when resolving raises `RuntimeError`.
- [ ] With `procedure.enabled` false the installer step returns the fixed skip action and builds nothing;
      with the key absent it builds as before (`test_install_plans_and_builds_index` passes).
- [ ] `sdd/specs/procedural-graph-plane.spec.md` lists `uncovered_ok` in `ProcedureManifest`.
- [ ] Every pre-existing test in the two test files still passes; `ruff check` is clean on the Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_procedure_assets.py -q`

---

## Test Specification

See the two test stubs in the blueprint; spec §4 rows 7–8 state what each asserts.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug fixgroup-848b9a0ceee1 --feature-id FEAT-899`).
2. Verify the Codebase Contract, mark the task `in-progress` in `sdd/tasks/index/fixgroup-848b9a0ceee1.json`.
3. Implement from the blueprint, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the five files listed, close with the close script, fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (`/sdd-fix` session, actor `agent:sdd-fix:cb69fd31`)
**Date**: 2026-11-15
**Notes**: `op_procedure_next` gained a second `except Exception` clause returning
`OperationResult(text="<ExcType>: <message>", is_error=True)`; the `ValueError`/`OSError` text is
unchanged. `_install_procedure_index_step` loads the SDD config first and returns
`procedure index: skipped (procedure.enabled is false)` without importing or building the plane.
`ProcedureManifest.uncovered_ok` added to the FEAT-891 spec §2. Code commit `20343fa686`. Validation:
`pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py packages/ai-parrot/tests/sdd/test_procedure_assets.py`
→ 13 passed; the full Validation Contract (five files) → 79 passed; `ruff check` and `black --check`
clean on the four Python files.

**Deviations from spec**: none. The installer test also asserts the enabled path still builds.
