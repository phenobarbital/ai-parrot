# TASK-3982: Host-write confirmation — approval token set by ToolManager, checked by AbstractTool.execute, direct-execute refusal (M8)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3979, TASK-3981
**Assigned-to**: unassigned
**Wave**: 2 (spec §9) · **Module**: M8 host-write-confirmation

---

## Context

Spec P6 / review R7: `confirming_tools` is metadata only; `ToolManager` asks a `ConfirmationGuard` only if one is
installed and otherwise proceeds (`manager.py:1817`, `:2012`); `/tools/{slug}/execute` never goes through
`ToolManager`. Spec §2 "Host-write confirmation": after a guard decision `confirmed`, `ToolManager.execute_tool`
sets a ContextVar `(id(tool), compute_args_hash(final_parameters))` around `tool.execute(...)` and resets it;
`AbstractTool.execute` refuses a `confirmation_enforced` tool unless the token matches this tool and the hash of
the kwargs it received → `ToolResult(status="forbidden", metadata.error_code="confirmation_required")`. Direct
execute refuses with 403 `confirmation_required` before `_instantiate_tool`.

---

## Scope

- `parrot/auth/confirmation.py`: add the approval-token ContextVar, `current_confirmed_call() -> tuple[int, str] | None`
  and a private context manager `_approved_call(tool, parameters)` used only by `ToolManager`.
- `parrot/tools/manager.py`: in the `AbstractTool` dispatch (`:2012-2061`) wrap `tool.execute(**exec_kwargs)` in
  `_approved_call(tool, parameters)` **only** when the guard decision status is `"confirmed"`; nothing is set when
  no guard is installed or the decision is `not_required`. (The `ToolDefinition` branch `:1817-1849` does not
  dispatch through `AbstractTool.execute`; leave it.)
- `parrot/tools/abstract.py::execute`: after the special kwargs are popped (`:904-917`) and before the permission
  resolver / `_ensure_open`, refuse a tool whose `routing_meta.get("confirmation_enforced")` is True unless
  `current_confirmed_call() == (id(self), compute_args_hash(kwargs))`; refusal is a structured `ToolResult`
  (`status="forbidden"`, `metadata` with `error_type`, `error_code="confirmation_required"`, `reason`).
  Extract into `_check_approval(kwargs) -> ToolResult | None` (R4; TASK-3989 merges it into `_enforce_scope_and_approval`).
- `studio/testing.py` execute: a resolved class whose instance would be `confirmation_enforced` (host standalone
  write tool) → 403 `confirmation_required` before `_instantiate_tool`.
- Tests: the four M8 unit tests and `test_execute_refuses_host_write`.

**NOT in scope**: the scope gate (TASK-3989); installing `app["studio_confirmation_guard"]` on Studio bots
(FEAT-621 W2 builder, FEAT-605 test chat); a HITL UI (P-Q2, deferred).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/confirmation.py` | MODIFY | approval-token ContextVar, current_confirmed_call, _approved_call |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | set the token around tool.execute after a `confirmed` decision |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | execute: refuse confirmation_enforced without a matching token |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | execute: 403 confirmation_required for host write tools |
| `packages/ai-parrot/tests/tools/test_host_write_confirmation.py` | CREATE | M8 unit tests |
| `packages/ai-parrot-server/tests/studio/test_execute_host_write.py` | CREATE | test_execute_refuses_host_write |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.auth.confirmation import ConfirmationGuard, ConfirmationDecision, compute_args_hash  # confirmation.py:378, :88, :46
from parrot.tools.abstract import AbstractTool, ToolResult  # abstract.py:281, :250
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/confirmation.py
from parrot.tools.abstract import AbstractToolArgsSchema  # :40 — confirmation.py imports abstract.py at module top,
#   so abstract.py MUST import from confirmation lazily (inside the method) to avoid a cycle
def compute_args_hash(parameters: dict) -> str  # :46
class ConfirmationDecision(BaseModel):  # :88 — allowed; status ∈ confirmed|cancelled|timeout|not_required (:103); parameters
class ConfirmationGuard  # :378 — confirm(tool=, parameters=, permission_context=); no human_manager ⇒ cancelled (step 3)
# packages/ai-parrot/src/parrot/tools/manager.py
self._confirmation_guard: Optional["ConfirmationGuard"] = None  # :395; set_confirmation_guard :551
# AbstractTool branch: guard block :2012-2044 (confirm_decision; parameters replaced :2041-2043);
# exec_kwargs = dict(parameters) :2048
result = await self._observed(observation, tool_name, lambda: tool.execute(**exec_kwargs))  # :2061 ← anchor (occurrences: 1)
# packages/ai-parrot/src/parrot/tools/abstract.py
_resolver = kwargs.pop("_resolver", None)  # :905; pops end :917 (`_cred_user_id`)
if pctx is not None and resolver is not None:  # :919 — the permission check; the approval check goes ABOVE it
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py
instance = _instantiate_tool(cls, self.request.app)  # :372 ← anchor (occurrences: 1)
```

### Does NOT Exist
- ~~a confirmation requirement that holds without a guard~~ — `ToolManager` proceeds when `_confirmation_guard is None` (`manager.py:1817`, `:2012`).
- ~~`current_confirmed_call`~~ — created here.
- ~~a kwarg that grants approval~~ — `_confirmation` or any key in LLM args never counts; only the ContextVar.
- ~~`ConfirmationDecision.status == "approved"`~~ — the value is `"confirmed"`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/confirmation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_host_write_confirmation.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_execute_host_write.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/confirmation.py#compute_args_hash",
    "sym:packages/ai-parrot/src/parrot/auth/confirmation.py#ConfirmationGuard",
    "sym:packages/ai-parrot/src/parrot/auth/confirmation.py#ConfirmationDecision",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.set_confirmation_guard",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.execute",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioToolExecuteHandler.post"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- ContextVar set/reset exactly like `_CREDENTIAL_VAR` / `_A2UI_SURFACE_STATE_VAR` in `abstract.py:59-75`
  (token = var.set(...); try: ... finally: var.reset(token)). Never store approval on `self`.
- The hash must be computed over the same mapping on both sides: the manager hashes the **final** `parameters`
  (after the guard possibly edited them, `:2041-2043`), and `execute` hashes the tool kwargs **after** the special
  `_*` kwargs are popped — they are equal because `exec_kwargs` = `parameters` + popped specials.
- `ToolResult(status="forbidden")` mirrors the existing permission refusal at `abstract.py:924-934`.
- Direct execute decides "would be enforced" from the class: a host standalone tool with `access != "read"`
  (helper shared with TASK-3981's `_is_host_class`; FILL IN its location, no duplication).

### Cross-feature ordering
- `studio/testing.py`: merges after the FEAT-621 W3 task for `testing.py` (which itself rebases on FEAT-605 W1.3)
  and rebases on it (X16 per-file rule).
- Release: lands together with TASK-3981 (X16 "Wave 2 lands M6 together with M8").

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the token ContextVar + accessors to `confirmation.py` — *why*: only `ToolManager` may set it.
2. Wrap the dispatch at `manager.py:2061` when `confirm_decision.status == "confirmed"` — *why*: approval is per call, exact params.
3. Add `_check_approval` to `AbstractTool` and call it right after the pops — *why*: before `_ensure_open`, zero side effects.
4. Refuse host writes on direct execute before `_instantiate_tool` — *why*: no approval channel there.
5. Tests with counters (`bump`); mutation: skip the check ⇒ zero-write tests RED.

### `packages/ai-parrot/src/parrot/auth/confirmation.py` (MODIFY)
```python
# AFTER — insert below the `compute_args_hash` function (verified: confirmation.py:46-60)
_APPROVED_CALL: ContextVar[tuple[int, str] | None] = ContextVar("parrot_approved_tool_call", default=None)


def current_confirmed_call() -> tuple[int, str] | None:
    """``(id(tool), args_hash)`` of the call ToolManager approved, or ``None`` (FEAT-622 M8)."""
    return _APPROVED_CALL.get()


@contextmanager
def _approved_call(tool: Any, parameters: dict) -> Iterator[None]:
    """Bind the approval token for exactly one ``tool.execute`` (ToolManager only)."""
    token = _APPROVED_CALL.set((id(tool), compute_args_hash(parameters)))
    try:
        yield
    finally:
        _APPROVED_CALL.reset(token)
# FILL IN: add `from contextlib import contextmanager`, `from contextvars import ContextVar`, `Iterator` imports
```

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'lambda: tool.execute(\*\*exec_kwargs))' manager.py)
# REPLACE manager.py:2061 with:
                if approved:
                    with _approved_call(tool, parameters):
                        result = await self._observed(observation, tool_name, lambda: tool.execute(**exec_kwargs))
                else:
                    result = await self._observed(observation, tool_name, lambda: tool.execute(**exec_kwargs))
# FILL IN: `approved = False` before the guard block (:2012) and `approved = confirm_decision.status == "confirmed"`
#   inside it; import _approved_call lazily or at top (manager.py imports ConfirmationGuard only under TYPE_CHECKING :26)
```

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_cred_user_id: Optional\[str\] = kwargs.pop("_cred_user_id", None)' abstract.py)
# AFTER — insert below `        _cred_user_id: Optional[str] = kwargs.pop("_cred_user_id", None)` (verified: abstract.py:917)
        refused = self._check_approval(kwargs)
        if refused is not None:
            return refused
# FILL IN: def _check_approval(self, kwargs) -> Optional[ToolResult] — lazy import of current_confirmed_call /
#   compute_args_hash from parrot.auth.confirmation; only when (self.routing_meta or {}).get("confirmation_enforced")
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'instance = _instantiate_tool(cls, self.request.app)' testing.py)
# BEFORE — insert above the `try:` that precedes `instance = _instantiate_tool(cls, self.request.app)` (testing.py:371-372)
        if _requires_enforced_confirmation(cls):
            return self._error(
                f"Tool '{slug}' requires confirmation and cannot be executed directly.",
                status=403,
                code="confirmation_required",
            )
# FILL IN: _requires_enforced_confirmation(cls) — host standalone tool with access != "read" (reuse TK-07 helper)
```

### FILL IN checklist
- [ ] `manager.py` — `approved` flag scoping; bounded by "Only ToolManager sets it" and `test_host_write_approved_executes_once`.
- [ ] `abstract.py::_check_approval` — structured refusal metadata; bounded by spec §2 "Error surface".
- [ ] `testing.py::_requires_enforced_confirmation` — class-level decision without instantiation.

---

## Acceptance Criteria

- [ ] No guard on the `ToolManager`: the LLM calling `bump` → `confirmation_required`, counter 0.
- [ ] Guard with a scripted `human_manager` that approves → counter 1 with the approved parameters.
- [ ] Rejection and timeout → counter 0.
- [ ] LLM args carrying `_confirmation` / any key → refused; a token for another tool or other args hash → refused.
- [ ] `POST /tools/tp_probe_tool_write/execute` → 403 `confirmation_required`, zero writes.
- [ ] Built-ins (`access=None`) behave exactly as before (existing confirmation tests pass).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_host_write_confirmation.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_execute_host_write.py -q`
- `pytest packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_host_write_confirmation.py
async def test_host_write_without_guard_zero_writes(host_plugins): ...
async def test_host_write_approved_executes_once(host_plugins): ...   # scripted human_manager approves
async def test_host_write_rejected_executes_zero(host_plugins): ...   # scripted rejection and timeout
async def test_approval_token_not_forgeable(host_plugins): ...        # _confirmation kwarg; wrong tool; wrong hash

# packages/ai-parrot-server/tests/studio/test_execute_host_write.py
async def test_execute_refuses_host_write(host_plugins):
    """/tools/tp_probe_tool_write/execute → 403 confirmation_required, zero writes (R7 regression)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Mutation evidence**: <for each new assertion: the code reverted, the test that went RED>

**Deviations from spec**: none | describe if any
