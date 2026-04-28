# TASK-898: Implement `IntentClassifierNode`

**Feature**: FEAT-132 — feat-129-upgrades
**Spec**: `sdd/specs/feat-129-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-896
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. New head-of-flow node that:
1. Validates the brief (allowlist heads, path-traversal — the logic
   currently inside `BugIntakeNode._validate`).
2. Emits a single `flow.intake_validated` event to
   `flow:{run_id}:flow` with the resolved `kind`.
3. Returns the validated `WorkBrief` so the flow's
   `on_condition(predicate=…)` can route on `result.kind` (TASK-901).

Side effect requirement: also writes the brief into `ctx['bug_brief']`
(legacy key, kept for back-compat with Development/QA/Failure nodes
that already read it) AND into `ctx['work_brief']` (forward-compat).

---

## Scope

- Create the new node module
  `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py`.
- Implement `IntentClassifierNode(Node)` with:
  - `__init__(self, *, redis_url: str, name: str = "intent_classifier")`
  - `async def execute(self, prompt: str, ctx: Dict[str, Any]) -> WorkBrief`
- Migrate the validation logic verbatim from
  `BugIntakeNode._validate` (do not change semantics).
- Emit ONE `flow.intake_validated` redis event per dispatch with
  payload `{kind, n_criteria, affected_component, summary}`.
- Add `IntentClassifierNode` to
  `parrot/flows/dev_loop/nodes/__init__.py` (if a public re-export
  exists there) and to the package `__init__.py` `__all__`.
- Write unit tests in
  `packages/ai-parrot/tests/flows/dev_loop/test_intent_classifier.py`.

**NOT in scope**:
- Removing the validation logic from `BugIntakeNode` — that's TASK-899.
- Wiring the node into `build_dev_loop_flow` — that's TASK-901.
- Routing predicates — that's TASK-901.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py` | CREATE | The new node. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/__init__.py` | MODIFY | Re-export if pattern exists for other nodes. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Add `IntentClassifierNode` to public exports + `__all__`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_intent_classifier.py` | CREATE | Unit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.flow.node import Node                      # node.py:14
from parrot.conf import ACCEPTANCE_CRITERION_ALLOWLIST       # conf.py
from parrot.flows.dev_loop.models import (
    WorkBrief, ShellCriterion, FlowtaskCriterion,
)
# verified: parrot/flows/dev_loop/models.py (post-TASK-896)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py
class BugIntakeNode(Node):                                   # line 29
    def __init__(self, *, redis_url: str, name: str = "bug_intake"):
        super().__init__()
        self._name = name
        self._init_node(name)
        self._redis_url = redis_url
        self._redis: Any = None
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str: ...

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
        brief = self._load_brief(prompt, ctx)
        self._validate(brief)
        run_id = ctx.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        ctx["bug_brief"] = brief
        return brief

    def _load_brief(self, prompt, ctx) -> BugBrief:
        # Loads from ctx["bug_brief"] / dict / JSON prompt — REUSE as-is.
        ...

    def _validate(self, brief: BugBrief) -> None:
        # Allowlist heads + path-traversal — MIGRATE this verbatim.
        ...

    async def _ensure_redis(self) -> Any:
        # Lazy import + cache — MIRROR.
        ...

    async def _emit_validated_event(self, run_id, brief) -> None:
        # XADD to flow:{run_id}:flow — MIRROR with event_kind change.
        ...

# parrot.bots.flow.node.Node API to inherit:
class Node(ABC):                                             # node.py:14
    def _init_node(self, name: str) -> None: ...
    @property
    def name(self) -> str: ...
```

### Pattern reference — emit event payload shape

```python
envelope = {
    "kind": "flow.intake_validated",
    "ts": time.time(),
    "run_id": run_id,
    "node_id": self.name,
    "payload": {
        "kind": brief.kind,
        "n_criteria": len(brief.acceptance_criteria),
        "affected_component": brief.affected_component,
        "summary": brief.summary,
    },
}
fields = {"event": json.dumps(envelope)}
await redis_client.xadd(
    f"flow:{run_id}:flow", fields, maxlen=10_000, approximate=True,
)
# Mirrors bug_intake.py _emit_validated_event but with new kind name.
```

### Does NOT Exist

- ~~`Node.classify(...)`~~ — there is no base classify method; this
  node is just a `Node` subclass.
- ~~LLM-based classification~~ — explicitly out of scope (spec §1
  Non-Goals). The node only reads `brief.kind`.
- ~~An `IntakeRouterNode` / `RouterNode`~~ — the canonical name is
  `IntentClassifierNode` (spec §8 Resolved Q4).
- ~~A new `WorkKind` import path~~ — `WorkKind` is internal to
  `models.py`; this task only uses `WorkBrief.kind` at runtime, not
  the type alias.

---

## Implementation Notes

### Pattern to Follow

Copy the structure of `BugIntakeNode` verbatim and rename:

```python
# nodes/intent_classifier.py
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from parrot.bots.flow.node import Node
from parrot.conf import ACCEPTANCE_CRITERION_ALLOWLIST
from parrot.flows.dev_loop.models import (
    WorkBrief,
    ShellCriterion,
    FlowtaskCriterion,
)


class IntentClassifierNode(Node):
    """First node — validates the WorkBrief and routes by kind.

    Absorbs BugIntakeNode's universal validation (allowlist heads,
    path-traversal). Emits one ``flow.intake_validated`` event.
    Returns the validated ``WorkBrief`` so the flow factory's
    ``on_condition`` predicates can read ``result.kind``.

    The brief is stored under both ``ctx['bug_brief']`` (legacy key
    that Development/QA/Failure read) and ``ctx['work_brief']``
    (forward-compat name).
    """

    def __init__(self, *, redis_url: str,
                 name: str = "intent_classifier") -> None:
        super().__init__()
        self._name = name
        self._init_node(name)
        self._redis_url = redis_url
        self._redis: Any = None
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> WorkBrief:
        brief = self._load_brief(prompt, ctx)
        self._validate(brief)
        run_id = ctx.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        ctx["bug_brief"] = brief         # legacy key
        ctx["work_brief"] = brief        # forward-compat
        self.logger.info(
            "Intake validated: kind=%s, criteria=%d",
            brief.kind, len(brief.acceptance_criteria),
        )
        return brief

    # _load_brief, _validate, _ensure_redis: copy verbatim from
    # BugIntakeNode and adjust _emit_validated_event's event_kind to
    # "flow.intake_validated" with the new payload shape.
```

### Key Constraints

- Validation MUST be a literal copy of `BugIntakeNode._validate`.
  Don't refactor or relax it in this task — TASK-899 is what removes
  the duplicate from BugIntakeNode.
- Event is emitted at most once per call; on `_ensure_redis` failure,
  log a warning and proceed (mirrors current bug_intake behaviour).
- `_load_brief` accepts the same shapes (`ctx['bug_brief']` /
  `ctx['work_brief']` as `WorkBrief` instance / dict / JSON prompt).
  Add a `ctx['work_brief']` source to `_load_brief` so callers can
  use the new key.

### References in Codebase

- `parrot/flows/dev_loop/nodes/bug_intake.py` — source of the
  validation + event-emission patterns.
- `parrot/flows/dev_loop/__init__.py` — public-export pattern.

---

## Acceptance Criteria

- [ ] `IntentClassifierNode` exists at
  `parrot/flows/dev_loop/nodes/intent_classifier.py`.
- [ ] `parrot.flows.dev_loop.IntentClassifierNode` resolves (added to
  package `__all__`).
- [ ] `execute()` returns the validated `WorkBrief`; `ctx['bug_brief']`
  and `ctx['work_brief']` are both populated.
- [ ] Allowlist + path-traversal validation rejects the same inputs
  the existing `BugIntakeNode._validate` rejects (verified by tests).
- [ ] Exactly one `XADD` to `flow:{run_id}:flow` per dispatch with
  `event_kind == "flow.intake_validated"` and payload containing
  `kind`.
- [ ] Tests in `test_intent_classifier.py` pass.
- [ ] Pre-existing dev_loop suite stays green.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_intent_classifier.py
import pytest
from unittest.mock import AsyncMock
from parrot.flows.dev_loop import IntentClassifierNode
# Note: WorkBrief / ShellCriterion / FlowtaskCriterion imported from
# the same package (post-TASK-896).


class TestValidation:
    async def test_rejects_disallowed_shell_head(self, sample_kwargs):
        from parrot.flows.dev_loop import WorkBrief, ShellCriterion
        brief = WorkBrief(
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="bad", command="rm -rf /"),
            ],
        )
        node = IntentClassifierNode(redis_url="redis://localhost:6379/0")
        with pytest.raises(ValueError):
            await node.execute("", {"bug_brief": brief, "run_id": "r1"})

    async def test_accepts_task_head(self, sample_kwargs):
        from parrot.flows.dev_loop import WorkBrief, ShellCriterion
        brief = WorkBrief(
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="task", command="task etl/x.yaml"),
            ],
        )
        node = IntentClassifierNode(redis_url="redis://localhost:6379/0")
        result = await node.execute("", {"bug_brief": brief, "run_id": "r1"})
        assert result is brief


class TestEmission:
    async def test_emits_one_xadd_per_call(self, monkeypatch, sample_brief):
        node = IntentClassifierNode(redis_url="redis://localhost:6379/0")
        fake = AsyncMock()
        fake.xadd = AsyncMock(return_value=b"1-0")

        async def _ensure():
            return fake

        monkeypatch.setattr(node, "_ensure_redis", _ensure)
        await node.execute("", {"bug_brief": sample_brief, "run_id": "r1"})
        assert fake.xadd.call_count == 1
        args, kwargs = fake.xadd.call_args
        assert args[0] == "flow:r1:flow"
        # The payload is JSON-encoded under fields["event"]; decode and
        # assert the kind appears.

    async def test_does_not_emit_without_run_id(self, sample_brief):
        node = IntentClassifierNode(redis_url="redis://localhost:6379/0")
        # No run_id in ctx; should not even attempt redis.
        await node.execute("", {"bug_brief": sample_brief, "run_id": ""})


class TestContextPropagation:
    async def test_writes_both_legacy_and_new_keys(self, sample_brief):
        node = IntentClassifierNode(redis_url="redis://localhost:6379/0")
        ctx = {"bug_brief": sample_brief, "run_id": ""}
        await node.execute("", ctx)
        assert ctx["bug_brief"] is sample_brief
        assert ctx["work_brief"] is sample_brief

    async def test_returns_kind_for_routing(self, sample_kwargs):
        from parrot.flows.dev_loop import WorkBrief, ShellCriterion
        brief = WorkBrief(
            kind="enhancement",
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="ok", command="ruff check ."),
            ],
        )
        node = IntentClassifierNode(redis_url="redis://localhost:6379/0")
        result = await node.execute("", {"bug_brief": brief, "run_id": ""})
        assert result.kind == "enhancement"
```

`sample_kwargs` and `sample_brief` are fixtures in `conftest.py`;
extend if missing.

---

## Agent Instructions

1. Read `nodes/bug_intake.py` end-to-end first — your node mirrors
   its structure with the validation kept and the event renamed.
2. Implement, register in `__init__.py`, write tests, run them.
3. Commit; move file to `sdd/tasks/done/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
