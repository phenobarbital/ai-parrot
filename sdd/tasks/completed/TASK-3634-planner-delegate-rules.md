# TASK-3634: Planner prompt — delegate authoring rules (opt-in)

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 8 (planner half), AC13. The planner LLM must learn the
`"type": "delegate"` node **only** when the toolkit has delegates configured.
Otherwise it could emit nodes the validator will reject with
`no_delegate_configured`. This task adds a keyword-only opt-in to `PlanPlanner`.
TASK-3635 passes it from the toolkit.

---

## Scope

- Add a `_DELEGATE_RULES` constant next to `_PLANNING_RULES`. It covers:
  - when to use a delegate node (a small runtime choice among ≤ N tools) and when not (args known at plan time → tool node)
  - the node shape: `type`, `instruction`, `facts`, `tools`, `min_confidence`, `accept_when`, `on_reject`, `allow_side_effects`
  - the placeholder rules (same as `args`)
  - a note that setting `min_confidence` rejects unscored proposals
  - a list of the `delegate_safe` tool names
- Change `PlanPlanner.__init__(planner_llm, catalog, *, delegate_safe_tools: Optional[Sequence[str]] = None, delegate_max_tools: int = 5)`. With `None` (the default), prompts are byte-identical to today.
- `_authoring_prompt` / `_repair_prompt` append the rules block after `_PLANNING_RULES` when enabled.
- Write tests.

**NOT in scope**: the toolkit passing the kwargs (TASK-3635); the delta prompt (`_DELTA_RULES`), because delegate nodes are not repairable in v1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` | MODIFY | Rules constant + opt-in kwargs |
| `packages/ai-parrot/tests/tools/execution_plan/test_planner_delegate_rules.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.execution_plan.planner import PlanPlanner   # verified: planner.py:40 (__all__), class at ~line 139
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/planner.py
_PLANNING_RULES = """\ ... """                                  # line 42  <-- anchor
_DELTA_RULES = """\ ... """                                     # line 58
class PlanPlanner:
    def __init__(self, planner_llm, catalog: Sequence[ToolCatalogEntry]) -> None   # line 148
        # self.client = resolve_planner_client(planner_llm); self.catalog = list(catalog); self.logger = ...
    def _authoring_prompt(self, objective: str) -> str           # line 324: f"{_PLANNING_RULES}\n\n" f"Tool catalog:..."
    def _repair_prompt(self, plan_json, report) -> str           # line 334: same prefix
```
Look at `tests/tools/execution_plan/test_planner.py` to see how a `PlanPlanner` is built with a fake client. Mirror it.

### Does NOT Exist
- ~~`PlanPlanner(delegates=...)`~~: the planner takes plain data (tool names, max tools), never live delegate objects.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/planner.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_planner_delegate_rules.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/planner.py#PlanPlanner"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Default behaviour is byte-identical (the existing `test_planner.py` passes unmodified).
- Keep the rules ≤ ~20 lines. They go into every authoring and repair prompt.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_DELEGATE_RULES` below `_PLANNING_RULES` — *why*: prompt text lives next to its sibling.
2. Add the kwargs and a `_rules()` helper; use it in both prompts — *why*: one switch point.
3. Write the tests.

### `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_PLANNING_RULES = """\\' planner.py)
# AFTER the closing of _PLANNING_RULES (before `_DELTA_RULES`), insert:
_DELEGATE_RULES = """\
Delegate nodes (`"type": "delegate"`) — a tiny local model picks ONE tool call at run time:
- Use one ONLY when the arguments cannot be written as templates at plan time (choose among
  a few tools from an upstream result, derive args from a short text, per-item triage).
  If args are known now, use a normal tool node — it is cheaper and cannot fail.
- Fields: `instruction` (short text; same placeholders as `args`), optional `facts`
  (string-to-string map), `tools` (1..{max_tools} names from the list below), optional `min_confidence`
  (0..1; when set, proposals without a confidence score are REJECTED), optional `accept_when`
  (CEL over `ctx.proposal.name` / `ctx.proposal.arguments`), `on_reject`
  (`fail` | `retry_backend` | `escalate`), and `store_as` / `depends_on` / `for_each` as usual.
- Delegate-safe tools: {safe_tools}. Any other tool needs `allow_side_effects: true` AND host permission.
- Never put a delegate node's `tools` above {max_tools}; split the step instead."""

# PlanPlanner.__init__ (line 148): add keyword-only params
#     *, delegate_safe_tools: Optional[Sequence[str]] = None, delegate_max_tools: int = 5
#   store them; document ("None disables delegate rules — prompts unchanged").
    def _rules(self) -> str:
        """Planning rules, plus delegate rules when delegates are enabled."""
        if self._delegate_safe_tools is None:
            return _PLANNING_RULES
        # FILL IN: format _DELEGATE_RULES with max_tools and ", ".join(sorted(safe)) or "(none)";
        #   return f"{_PLANNING_RULES}\n\n{formatted}"
        raise NotImplementedError
# _authoring_prompt (line 324) and _repair_prompt (line 334): replace f"{_PLANNING_RULES}\n\n" with f"{self._rules()}\n\n"
```
**Why**: `str.format` is safe here because `_DELEGATE_RULES` contains no other braces. Keep it that way: backticks, not braces, around JSON examples.

### `packages/ai-parrot/tests/tools/execution_plan/test_planner_delegate_rules.py` (CREATE)
```python
"""FEAT-590 AC13: delegate rules only when delegates are configured."""
from __future__ import annotations

from parrot.tools.execution_plan.planner import PlanPlanner


def test_planner_rules_only_with_delegates() -> None: ...     # FILL IN: default prompt has no '"type": "delegate"'
def test_delegate_rules_list_safe_tools() -> None: ...        # FILL IN: names + max_tools rendered
def test_repair_prompt_also_carries_rules() -> None: ...      # FILL IN
```

### FILL IN checklist
- [ ] `_rules` formatting
- [ ] Tests (build the planner the way `test_planner.py` does)

---

## Acceptance Criteria

- [ ] AC13 holds; the existing `test_planner.py` passes unmodified
- [ ] `ruff check` is clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/execution_plan/test_planner_delegate_rules.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_planner.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard.

---

## Completion Note

Implemented by coder seat `gpt-5.6-terra` (codex), dispatched via the `parrot-sdd-coder`
MCP orchestrator, attempt_uid `9eac7302ccfb417b8ce6507173976fbd`. Merged clean on the
first attempt; `black` lint reported 0 errors/residuals. Reviewed and recorded
(`coder-review:26f944c2854be3a08bcedc67`, no corrections needed).

**Validation**: re-verified directly by the orchestrator post-merge —
`pytest packages/ai-parrot/tests/tools/execution_plan/test_planner_delegate_rules.py
packages/ai-parrot/tests/tools/execution_plan/test_planner.py -q` → 15 passed (planner
suite unmodified per its own AC).

**Merge-tier validation deviation (disclosed):** same as TASK-3625/3626's note — the
feature-wide `coder_run_validation` (tier=merge) sweep could not reach a clean
`completed` outcome due to a confirmed pre-existing, unrelated environment defect (25
collection errors + an integrations-suite hang, neither touching `planner.py`). Filed as
`issue:c3c59277ef77` (critical). This task is closed on its own directly-verified scoped
test evidence.
