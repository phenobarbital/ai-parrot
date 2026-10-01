# TASK-3989: Scope enforcement in core — gate in AbstractTool.execute, config_options wrapper, custom-schema and executor refusals; lift resolver rule 5 (M3b, part 1)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3975, TASK-3985, TASK-3986
**Assigned-to**: unassigned
**Wave**: 4 (spec §9) · **Module**: M3b scope-enforcement (core)

---

## Context

Spec P5 / review R6: the scope gate must run before any resource acquisition on every entry point.
`ToolkitTool._execute` acquires resources (`_ensure_open`, `toolkit.py:168`) before `_pre_execute` (`:179`);
standalone `AbstractTool`s never run `ToolkitTool._execute`; the options handler calls `config_options()` directly.
Spec §2 "Scope enforcement": the gate runs in `AbstractTool.execute` immediately after the special kwargs are popped
and **before** the permission resolver, lifecycle events, `_ensure_open`, `validate_args`, the credential seam, the
executor dispatch and `_execute`; `AbstractToolkit.__init_subclass__` wraps a tenant-bound subclass's
`config_options` so `require_tool_scope()` runs first; custom schemas exposing a server-managed name are a
`TypeError`; a tenant-bound tool with `executor` set is refused (`TypeError`). This lifts resolver rule 5.

---

## Scope

- `abstract.py`: add `_enforce_scope_and_approval(kwargs) -> ToolResult | None` = scope gate (when
  `is_tenant_bound(self)`) **then** the TASK-3982 approval check; call it where TASK-3982 calls `_check_approval`
  (replace that call). Refusal: `ToolResult(status="error", metadata={"tool_name", "error_type": "ToolScopeUnavailable",
  "error_code": "tool_scope_unavailable", "reason": exc.reason})`. Also map a `ToolScopeUnavailable` raised inside the
  `try` (e.g. from injection) to the same structured result at the generic error path (`:1201-1206`).
- `AbstractTool.__init_subclass__`: a custom `args_schema` declaring a server-managed method name → `TypeError`.
- Remote executors: a tenant-bound tool constructed with `executor` set → `TypeError` (in `AbstractTool.__init__`
  after `self.executor` is assigned, `abstract.py:385`; and in `AbstractToolkit.__init__` when it carries one).
- `toolkit.py`: `AbstractToolkit.__init_subclass__` wraps `config_options` defined by a tenant-bound subclass
  (`functools.wraps`; gate first, then the original); `_create_tool_from_method` refuses a method `_args_schema`
  that declares a server-managed name (`TypeError`).
- `resolver.py`: delete the rule-5 branch in `resolve()`.
- Tests: replace `test_tenant_bound_host_entry_unavailable_before_enforcement` with
  `test_tenant_bound_host_entry_resolves_after_enforcement`; add the M3b unit tests.

**NOT in scope**: handler pre-construction checks (TASK-3990); binding (TASK-3991); `host_tenant_mismatch`
(host code raises it in `_pre_execute`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | _enforce_scope_and_approval gate; structured refusal; __init_subclass__ custom-schema refusal; executor TypeError |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | config_options wrapper; _args_schema refusal; executor TypeError |
| `packages/ai-parrot/src/parrot/tools/resolver.py` | MODIFY | lift rule 5 |
| `packages/ai-parrot/tests/tools/test_toolkit_resolver.py` | MODIFY | replace the rule-5 test |
| `packages/ai-parrot/tests/tools/test_scope_enforcement.py` | CREATE | M3b unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.scope import ToolScopeUnavailable, is_tenant_bound, require_tool_scope  # TASK-3976
from parrot.tools.server_params import method_server_params  # TASK-3985
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py (line numbers drift after TASK-3982/11/12 — re-verify)
        pctx = kwargs.pop("_permission_context", None)  # :904 (occurrences: 1)
        refused = self._check_approval(kwargs)          # added by TASK-3982 right after the pops (:917)
        if pctx is not None and resolver is not None:   # :919 permission check — gate goes ABOVE
        self.events.emit_nowait(BeforeToolCallEvent(...))  # :955 — must not fire on refusal
            if self.auto_open and self.executor is None:  # :976 (occurrences: 1)
            return ToolResult(status="error", result=None, error=error_msg,
                metadata={"tool_name": self.name, "error_type": type(e).__name__},)  # :1201-1206 (occurrences: 1)
        self.executor: Optional["AbstractToolExecutor"] = executor  # :385
# packages/ai-parrot/src/parrot/tools/toolkit.py
        self.executor = kwargs.get("executor")  # :351
    async def config_options(self, param: str) -> list["ConfigOption"]:  # :710
        args_schema = getattr(bound_method, "_args_schema", None)  # :663 (occurrences: 1)
```

### Does NOT Exist
- ~~a gate inside `ToolkitTool._execute`~~ — none; the inherited `execute` gates first (spec Integration Points).
- ~~a new `ToolManager` status for scope refusals~~ — refusal is a `ToolResult` (spec §7 "Structured refusal").
- ~~`_current_pctx`-style instance state for the scope~~ — forbidden (`abstract.py:59-75`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/resolver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_toolkit_resolver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_scope_enforcement.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.execute",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.config_options",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._create_tool_from_method"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Structured refusal like the permission refusal (`abstract.py:924-934`) and `AuthorizationRequired`.
- The wrapper must not double-wrap (mark the wrapped function, e.g. `__feat622_gated__ = True`).
- `BeforeToolCallEvent` must not be emitted on refusal (test asserts it).

### Cross-feature ordering
- **Wave 4 needs FEAT-605 W2.1 (`build_tool_scope`, `StudioAgentRef`, tenant partitions) and FEAT-621 W2 (runtime identity: `bot._studio_key`, `bot._tooling_ref`) merged** (X16 cross-spec waits); the asserted test-chat / meta-agent bindings need FEAT-605 W3.4 / W3.5.
- Core-only files; release gate: no release is tenant-ready until Waves 1–4 and every sibling gate are met (X16).

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
1. Add `_enforce_scope_and_approval` and swap TASK-3982's call — *why*: one helper keeps `execute` within R4 and fixes the order (scope, then approval).
2. Map `ToolScopeUnavailable` at the generic error path — *why*: injection failures are structured too.
3. `__init_subclass__` refusals + executor refusal — *why*: custom schemas and remote workers would bypass the contract.
4. `config_options` wrapper — *why*: a direct call is gated without host code.
5. Lift rule 5 and update tests; mutation: move the gate below `_ensure_open` ⇒ `opened == 0` assertions RED.

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# REPLACE the TASK-3982 lines `refused = self._check_approval(kwargs)` with:
        refused = self._enforce_scope_and_approval(kwargs)
        if refused is not None:
            return refused

    def _enforce_scope_and_approval(self, kwargs: dict) -> Optional[ToolResult]:
        """FEAT-622: scope gate (tenant-bound) then the approval token — before any side effect."""
        if is_tenant_bound(self):
            try:
                require_tool_scope(tool_name=self.name)
            except ToolScopeUnavailable as exc:
                return self._scope_refusal(exc)
        return self._check_approval(kwargs)
# FILL IN: _scope_refusal(exc) -> ToolResult (status="error", metadata error_type/error_code/reason/tool_name);
#   generic error path: `if isinstance(e, ToolScopeUnavailable): return self._scope_refusal(e)` before :1201
```

### `packages/ai-parrot/src/parrot/tools/toolkit.py` (MODIFY)
```python
# Extend the __init_subclass__ added by TASK-3985:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "server_managed_params" in cls.__dict__:
            validate_server_params(cls)
        if "config_options" in cls.__dict__ and is_tenant_bound(cls):
            cls.config_options = _gate_options(cls.__dict__["config_options"])
# FILL IN: module-level _gate_options(fn) — functools.wraps; require_tool_scope(tool_name=f"{cls.__name__}.config_options")
#   before awaiting fn; idempotent marker
# FILL IN: in _create_tool_from_method after `args_schema = getattr(bound_method, "_args_schema", None)` (:663):
#   TypeError when args_schema declares any name in method_server_params(type(self))
```

### `packages/ai-parrot/src/parrot/tools/resolver.py` (MODIFY)
```python
# DELETE the rule-5 branch in ToolkitResolver.resolve (tenant-bound host entry → None)
```

### FILL IN checklist
- [ ] `_scope_refusal` metadata — bounded by spec §2 "Error surface".
- [ ] `_gate_options` — bounded by `test_options_provider_refuses_on_direct_call`.
- [ ] custom-schema + executor refusals — bounded by the two TypeError tests.

---

## Acceptance Criteria

- [ ] `ProbeTool.execute()` with no/mismatched scope → `tool_scope_unavailable`; `opened == 0`, `_execute` count 0, no `BeforeToolCallEvent`.
- [ ] `whoami` refuses; `opened == 0`; `_pre_execute` never called.
- [ ] `ProbeToolkit(...).config_options("x")` outside a scope raises `ToolScopeUnavailable`; `options_calls == 0`.
- [ ] Custom `args_schema` / `_args_schema` containing `tenant` → `TypeError`; tenant-bound tool with `executor` → `TypeError`.
- [ ] Refusal `ToolResult`: `status="error"`, `metadata.error_code="tool_scope_unavailable"`, `metadata.reason`.
- [ ] `resolve("tp_probe")` returns the class now (rule 5 lifted).
- [ ] `pytest packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py -q` (FEAT-391) passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_scope_enforcement.py -q`
- `pytest packages/ai-parrot/tests/tools/test_toolkit_resolver.py -q`
- `pytest packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_scope_enforcement.py
async def test_standalone_tool_refuses_before_side_effects(host_plugins): ...
async def test_toolkit_gate_runs_before_ensure_open_and_pre_execute(host_plugins): ...
async def test_options_provider_refuses_on_direct_call(host_plugins): ...
def test_custom_args_schema_exposing_server_managed_is_typeerror(): ...
def test_remote_executor_on_tenant_bound_is_typeerror(): ...
async def test_scope_error_is_structured_tool_result(host_plugins): ...
# packages/ai-parrot/tests/tools/test_toolkit_resolver.py — replaces test_tenant_bound_host_entry_unavailable_before_enforcement
def test_tenant_bound_host_entry_resolves_after_enforcement(host_plugins): ...
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
