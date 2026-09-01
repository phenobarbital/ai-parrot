# TASK-2692: Reference docs and end-to-end coverage

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 6)
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2688, TASK-2689, TASK-2691
**Assigned-to**: unassigned

---

## Context

`docs/dev_loop/dev-flow-model-plan.md` documents the build-time-only rule,
which this feature replaces for the dev-flow path. The end-to-end story also
needs coverage that no single earlier task owns.

Spec §3 Module 6.

---

## Scope

- Rewrite the build-time sections of `docs/dev_loop/dev-flow-model-plan.md`:
  seats are per-run for dev-flow; resume keeps original seats; the ops library
  seam exists but its console does not.
- Add the integration coverage from spec §4 that spans tasks: a console run
  applying a per-seat selection end to end, and the always-fresh `run_id`
  premise.

**NOT in scope**: new behaviour of any kind.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/dev-flow-model-plan.md` | MODIFY | Per-run rules |
| `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py` | MODIFY | Integration coverage |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py
# Existing harness to reuse — do NOT build a second one:
def _load_module(name: str, filename: str)   # importlib from examples/dev_loop/
class _StubFlow                              # records ctx in .contexts
@pytest.fixture def make_client(server_dev, aiohttp_client)
def _nl_form(**extra) -> dict[str, Any]
class TestPlanMismatchDiff._roundtrip_form(server_dev, plan)
```

### Does NOT Exist
- ~~a docs generator for this page~~ — it is hand-written Markdown.

---

## Acceptance Criteria

- [ ] The reference doc no longer claims the seats are build-time for dev-flow.
- [ ] The doc states the resume rule and the ops seam/console split.
- [ ] Integration tests from spec §4 exist and pass.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow packages/ai-parrot/tests/flows/dev_loop -v` passes.

---

## Test Specification

```python
async def test_run_endpoint_applies_ideation_model_end_to_end(): ...
async def test_console_run_id_is_always_fresh(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/per-run-model-plan.spec.md` for full context — especially §2 (Overview)
   and §8 (every open question is resolved there; do not re-open them).
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code. The line numbers
   above were correct on 2026-09-01; this repo drifts fast (an unrelated merge
   moved two of these files by 100+ lines in one afternoon). Re-grep the
   symbol, and if it moved, update the contract FIRST.
4. **Update status** in `sdd/tasks/index/per-run-model-plan.json` → `in-progress`.
5. **Implement** following the scope. Do not widen it.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `done`, and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
