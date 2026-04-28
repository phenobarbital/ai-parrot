# TASK-899: Scope down `BugIntakeNode` (validation moves to IntentClassifierNode)

**Feature**: FEAT-132 — feat-129-upgrades
**Spec**: `sdd/specs/feat-129-upgrades.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-898
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. After `IntentClassifierNode` (TASK-898) takes over
the universal validation (allowlist + path-traversal),
`BugIntakeNode` only needs to keep the bug-specific event
(`flow.bug_brief_validated`) and act as an extension hook for future
bug-only enrichment. Remove the duplicate validation; tests that
exercise `BugIntakeNode._validate` migrate to the new node's tests.

---

## Scope

- In `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py`:
  - Remove the body of `_validate` (or remove the method entirely if
    no longer referenced).
  - Stop calling `self._validate(brief)` from `execute`.
  - Keep `_load_brief`, `_emit_validated_event`, and the
    `flow.bug_brief_validated` event emission.
- In `packages/ai-parrot/tests/flows/dev_loop/test_bug_intake.py`:
  - Remove the validation-shape tests (they're now covered by
    TASK-898's `test_intent_classifier.py`).
  - Keep tests for `_load_brief` and `_emit_validated_event`.
- Update the docstring on `BugIntakeNode` to make its new role
  explicit ("bug-only post-validation hook for future enrichment").

**NOT in scope**:
- Deleting `BugIntakeNode` entirely (spec keeps it as an extension
  hook — see §7 R6).
- Wiring through `build_dev_loop_flow` (TASK-901).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py` | MODIFY | Remove `_validate`; update docstring. |
| `packages/ai-parrot/tests/flows/dev_loop/test_bug_intake.py` | MODIFY | Remove validation-shape tests; keep load/emit. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop import BugBrief                  # alias OK post-TASK-896
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
# verified: nodes/bug_intake.py:29
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py
class BugIntakeNode(Node):                                   # line 29
    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
        brief = self._load_brief(prompt, ctx)
        # self._validate(brief)  ← REMOVE this call
        run_id = ctx.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        ctx["bug_brief"] = brief
        return brief

    def _load_brief(self, prompt, ctx) -> BugBrief: ...      # KEEP
    def _validate(self, brief) -> None:                      # REMOVE body
        ...
    async def _ensure_redis(self) -> Any: ...                # KEEP
    async def _emit_validated_event(self, run_id, brief): ... # KEEP
```

### Does NOT Exist

- ~~A canonical "deletion test" that asserts `_validate` is gone~~ —
  just remove the test cases that called it. Don't add a negative
  test.
- ~~Re-exporting `_validate` as a free function~~ — IntentClassifier
  has its own copy; do not introduce a shared module to deduplicate
  in this task. (A later refactor may extract a shared validator if
  duplication becomes a problem.)

---

## Implementation Notes

### Pattern to Follow

```python
# After this task, BugIntakeNode.execute looks like:
async def execute(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
    """Bug-specific intake hook (post FEAT-132 scope-down).

    Universal validation now happens in IntentClassifierNode. This
    node remains as an extension point for bug-only enrichment
    (severity classification, stack-trace parsing, etc.); for v1 it
    just re-emits ``flow.bug_brief_validated`` for downstream
    observers that already subscribe to that event.
    """
    brief = self._load_brief(prompt, ctx)
    run_id = ctx.get("run_id", "")
    if run_id:
        await self._emit_validated_event(run_id, brief)
    ctx["bug_brief"] = brief
    return brief
```

### Key Constraints

- The class signature, `__init__`, and `execute` arity stay the same
  — TASK-901 still constructs it as before.
- The `flow.bug_brief_validated` event payload stays the same so any
  external WS/UI consumer keeps working.

### References in Codebase

- `parrot/flows/dev_loop/nodes/intent_classifier.py` — owns
  validation now (post-TASK-898).

---

## Acceptance Criteria

- [ ] `BugIntakeNode._validate` body is gone (method removed or empty
  pass-through).
- [ ] `BugIntakeNode.execute` no longer calls `_validate`.
- [ ] `flow.bug_brief_validated` event still emits with the same
  payload shape on bug-kind briefs.
- [ ] `tests/flows/dev_loop/test_bug_intake.py` does not test
  validation; the tests cover load/emit only.
- [ ] Full dev_loop suite stays green.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_bug_intake.py
class TestBugIntakeExecute:
    async def test_writes_brief_to_ctx(self, sample_brief):
        node = BugIntakeNode(redis_url="redis://localhost:6379/0")
        ctx = {"bug_brief": sample_brief, "run_id": ""}
        result = await node.execute("", ctx)
        assert result is sample_brief
        assert ctx["bug_brief"] is sample_brief

    async def test_emits_event_when_run_id_present(
        self, monkeypatch, sample_brief
    ):
        node = BugIntakeNode(redis_url="redis://localhost:6379/0")
        fake = AsyncMock(); fake.xadd = AsyncMock(return_value=b"1-0")
        async def _ensure(): return fake
        monkeypatch.setattr(node, "_ensure_redis", _ensure)
        await node.execute("", {"bug_brief": sample_brief, "run_id": "r1"})
        assert fake.xadd.call_count == 1

    # NOTE: Validation tests removed — covered by
    # tests/flows/dev_loop/test_intent_classifier.py (TASK-898).
```

---

## Agent Instructions

1. Confirm TASK-898 has landed (check `git log` or
   `sdd/tasks/done/TASK-898-*`).
2. Edit `bug_intake.py`; remove the validation call + method body.
3. Update `test_bug_intake.py`; drop the validation tests.
4. Run `pytest packages/ai-parrot/tests/flows/dev_loop/ -q`.
5. Commit; move; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
