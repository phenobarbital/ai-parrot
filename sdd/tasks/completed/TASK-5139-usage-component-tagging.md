# TASK-5139: Observability: tag UsageRecord with component

**Feature**: FEAT-796 — Per-Component LLM Defaults
**Spec**: `sdd/specs/per-component-llm-defaults.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (G6, AC10). Adds a `current_component` ContextVar and `usage_component()` context manager, a `UsageRecord.component` field, and fills it in the usage subscriber for both completed and failed calls. Store/span data only — never a metric label.

---

## Scope

- Add `current_component` + `usage_component(name)` to `observability/context.py` after `current_usage_attribution` (token set/reset, nested innermost wins).
- Add `component: Optional[str] = None` to `UsageRecord` after `roster_seat`, with a docstring Attributes entry.
- In `UsageSubscriber._on_client_after` and `_on_client_failed`, pass `component=current_component.get()`.
- Write tests.

**NOT in scope**: Setting the component at crew/expert/handler entry points (TASK-5140/5141/5142). Prometheus/OpenLit labels (spec Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/context.py` | MODIFY | ContextVar + CM |
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | UsageRecord.component |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | fill component |
| `packages/ai-parrot/tests/observability/test_usage_component.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Verify anything not listed
> before using it. Anchors verified at dev `e179aba02f`.

### Verified Imports
```python
from parrot.observability.context import current_run_id, current_seat, current_usage_attribution  # verified: subscriber.py:23
```

### Existing Signatures to Use
```python
# observability/context.py:163
current_usage_attribution: ContextVar[Optional["UsageAttribution"]] = ContextVar(
# observability/context.py:168 — pattern to copy
@contextmanager
def usage_attribution(run_id, seat=None, attribution=None) -> Iterator[None]:
# recorders/models.py:101
    roster_seat: Optional[str] = None
# recorders/subscriber.py:141 and :183 (both handlers)
        seat = current_seat.get()
# subscriber._on_client_after (line 109), _on_client_failed (line 171)
```

### Does NOT Exist
- ~~`UsageRecord.component`~~, ~~`current_component`~~, ~~`usage_component`~~ — created here
- ~~a component metric label~~ — must not be added

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/observability/recorders/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/observability/recorders/subscriber.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/observability/test_usage_component.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/recorders/models.py#UsageRecord",
    "sym:packages/ai-parrot/src/parrot/observability/recorders/subscriber.py#UsageSubscriber"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `seat = current_seat.get()` occurs twice (lines 141, 183) — edit BOTH; disambiguate by enclosing method name.
- `contextmanager`, `ContextVar`, `Iterator`, `Optional` are already imported in context.py (line 50 and module imports) — verify before adding.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path the blueprint fixes.

### Steps (in order)
1. context.py additions — *why*: single tag source.
2. UsageRecord field — *why*: persisted attribution.
3. Subscriber: add import + `component=` kwarg in both record constructions — *why*: success and failure must both be tagged.
4. Tests.

### `packages/ai-parrot/src/parrot/observability/context.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'current_usage_attribution: ContextVar[Optional["UsageAttribution"]] = ContextVar(' context.py)
# AFTER the closing `)` of that ContextVar (line ~165), insert:
current_component: ContextVar[Optional[str]] = ContextVar("parrot_current_component", default=None)


@contextmanager
def usage_component(name: Optional[str]) -> Iterator[None]:
    """Tag every client call in this scope with ``name`` in ``UsageRecord.component`` (FEAT-796).

    Token-based set/reset: nested scopes restore the outer value; innermost wins.
    """
    token = current_component.set(name)
    try:
        yield
    finally:
        current_component.reset(token)
```

### `packages/ai-parrot/src/parrot/observability/recorders/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    roster_seat: Optional[str] = None' models.py)
# AFTER line 101:
    component: Optional[str] = None
# FILL IN: add an Attributes docstring entry "component: FEAT-796 — ..." next to roster_seat (line ~62)
```

### `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '        seat = current_seat.get()' subscriber.py) — lines 141 (_on_client_after) and 183 (_on_client_failed)
# 1) line 23 import becomes:
from parrot.observability.context import current_component, current_run_id, current_seat, current_usage_attribution
# 2) in BOTH UsageRecord(...) constructions, after `node_id=_node_id_from_seat(seat),` add:
            component=current_component.get(),
```

### FILL IN checklist
- [ ] models.py docstring entry; bounded by AC10
- [ ] confirm both subscriber constructions updated (grep -c 'component=current_component.get()' == 2)

---

## Acceptance Criteria

- [ ] `usage_component` sets and restores; nested innermost wins
- [ ] Completed and failed records carry `component`
- [ ] Unattributed records have `component is None`
- [ ] No metric label added
- [ ] `ruff check` clean; existing observability tests still pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/observability/test_usage_component.py -q`
- `pytest packages/ai-parrot/tests/observability/test_usage_record_attribution.py -q`

---

## Test Specification

```python
from parrot.observability.context import current_component, usage_component
from parrot.observability.recorders.models import UsageRecord

def test_usage_component_cm_sets_and_resets(): ...
def test_nested_innermost_wins(): ...
def test_usage_record_component_default_none(): ...
async def test_subscriber_tags_component(): ...  # FILL IN: build AfterClientCallEvent + ClientCallFailedEvent like test_usage_record_attribution.py does
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-component-llm-defaults --feature-id FEAT-796`), never on `dev`.
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/per-component-llm-defaults.json`.
3. Verify the Codebase Contract (re-run the `grep -c` of every anchor) before writing code.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH` set to the changed packages' absolute `src` dirs; `ruff check` the touched files.
7. Commit only the listed files; close with `parrot sdd task close TASK-5139 per-component-llm-defaults verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; coder seat gpt-5.6-sol (codex), 1 attempt, 0 retries
**Date**: 2026-11-04
**Notes**: Merged as f84fa425a5; delivery reviewed against task, merge-tier validation green (5 passed). coder_record_review failed server-side (CoderReview mapping error) — review NOT recorded; 0 fix commits.

**Deviations from spec**: none
