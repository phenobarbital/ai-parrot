# TASK-3986: Server-managed fill — per-call drop/inject in AbstractTool.execute and constructor fill in apply_tooling_specs (M4, part 2)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3979, TASK-3985
**Assigned-to**: unassigned
**Wave**: 3 (spec §9) · **Module**: M4 server-managed-params (fill)

---

## Context

Spec §2 "Scope enforcement" → "Server-managed arguments", per call: in `AbstractTool.execute` any supplied kwarg
whose name is server-managed is dropped with a warning (LLM path); after `validate_args`, scope values are injected
into the resolved kwargs handed to `_execute` (`tenant` → `str`, `caller` → `CallerView`, `agent` →
`AgentScopeView | None`). Build: §2 "Server-managed rules" constructor params — drop any stored value, then fill
(`app` → `app[key]`; `server` → bespoke builder). Fill order decided in TASK-3985's design pass.

---

## Scope

- `AbstractTool.execute`: before `validate_args`, drop kwargs named in the tool's method server-managed params
  (owning toolkit's for a `ToolkitTool`) with one `self.logger.warning`; after `validate_args`, inject values from
  `require_tool_scope(tool_name=self.name)` into `resolved_kwargs` (helpers `_drop_server_managed(kwargs)`,
  `_inject_server_managed(resolved_kwargs)`).
- `ToolkitTool._execute` unknown-kwarg filter (`toolkit.py:184-191`) keeps injected names because they are in the
  bound method's signature — verify, no edit expected.
- `apply_tooling_specs`: after `hydrate_params`, strip every declared server-managed key with a warning; for a
  non-DatasetManager class fill constructor params with `source="app"` from `self.app.get(key)`; leave
  `source="server"` unfilled (bespoke builders only).
- Tests `test_server_managed_method_param_hidden_and_llm_value_dropped`, `test_stored_server_managed_key_stripped_on_build`,
  `test_app_source_filled_at_build`.

**NOT in scope**: the structured `tool_scope_unavailable` result and the gate (TASK-3989 — until then a
missing scope during injection surfaces as the generic error ToolResult); server handlers (TASK-3987).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | execute: drop LLM-supplied server-managed kwargs; inject scope values after validate_args |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | apply_tooling_specs: strip stored keys; fill app-sourced ctor params |
| `packages/ai-parrot/tests/tools/test_server_managed_per_call.py` | CREATE | per-call drop/inject tests |
| `packages/ai-parrot/tests/interfaces/test_apply_tooling_server_managed.py` | CREATE | build-time strip/fill tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.server_params import ServerParam, constructor_server_params, method_server_params  # TASK-3985
from parrot.tools.scope import require_tool_scope  # TASK-3976
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
            validated_args = self.validate_args(**kwargs)  # :982 ← anchor (occurrences: 1)
            if hasattr(validated_args, "model_dump"):      # :985
                resolved_kwargs = self._shallow_dump(validated_args)  # :986
            else:
                resolved_kwargs = dict(kwargs)              # :988
# packages/ai-parrot/src/parrot/interfaces/tools.py
                params = await hydrate_params(spec)  # :205 (before TASK-3978/TK-05 edits; re-verify)
                if spec.slug.lower() == "dataset_manager":  # :206
                filtered = {name: value for name, value in params.items() if name in accepted}  # :241
                instance = cls(**filtered)  # :242 ← anchor (occurrences: 1)
# packages/ai-parrot/src/parrot/bots/abstract.py:1515-1517 — configure() sets self.app before apply_tooling_specs (:1524)
```

### Does NOT Exist
- ~~a kwarg-based way for the LLM to set a server-managed value~~ — always dropped.
- ~~storing the scope on the tool instance~~ — never; read it per call (spec AC "Nothing is stored on a toolkit instance").

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
      "path": "packages/ai-parrot/src/parrot/interfaces/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_server_managed_per_call.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/interfaces/test_apply_tooling_server_managed.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.execute",
    "sym:packages/ai-parrot/src/parrot/interfaces/tools.py#ToolInterface.apply_tooling_specs"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Use the TASK-3985 design-pass order verbatim.
- Scope fixture in core tests: a Protocol-conforming frozen dataclass set into a real `RequestContext(request=make_mocked_request(...), studio_scope=...)`
  via `_current_ctx.set/reset`; the FEAT-605 real-type fixture is asserted end-to-end in TASK-3992.

### Cross-feature ordering
- `interfaces/tools.py`: after TASK-3978 (merged before FEAT-621 W2) and TASK-3979; serialise after any FEAT-621 W2
  builder edit on that file (X16 "then TOOLKITS M2/M4 serialise").

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
1. Add `_drop_server_managed` before `validate_args` and `_inject_server_managed` after `resolved_kwargs` — *why*: the LLM never sets them; the scope does.
2. Strip + fill in `apply_tooling_specs` — *why*: §7 "stripped on load, with a warning"; app deps come from `self.app`.
3. Tests; mutation: skip the drop ⇒ `tenant="other"` reaches the method ⇒ RED.

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'validated_args = self.validate_args(\*\*kwargs)' abstract.py)
# BEFORE — insert above `            validated_args = self.validate_args(**kwargs)` (verified: abstract.py:982)
            kwargs = self._drop_server_managed(kwargs)
# AFTER the resolved_kwargs if/else (abstract.py:985-988):
            resolved_kwargs = self._inject_server_managed(resolved_kwargs)
# FILL IN: _server_param_owner() (owning toolkit class for ToolkitTool else type(self)); _drop_server_managed;
#   _inject_server_managed using require_tool_scope(tool_name=self.name): tenant→str, caller→scope.caller, agent→scope.agent
```

### `packages/ai-parrot/src/parrot/interfaces/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'instance = cls(\*\*filtered)' interfaces/tools.py)
# BEFORE — insert above `                instance = cls(**filtered)` (verified: interfaces/tools.py:242)
                filtered.update(self._fill_server_params(cls))
# and directly after `params = await hydrate_params(spec)`:
                params = self._strip_server_params(cls, spec.slug, params)
# FILL IN: _strip_server_params (warning per stripped key) and _fill_server_params (source="app" from self.app.get(key);
#   "server" left to bespoke builders) — bounded by TASK-3985 design pass items 3–4
```

### FILL IN checklist
- [ ] `abstract.py` helpers — bounded by spec "Server-managed arguments, generated and custom schemas" (per call).
- [ ] `interfaces/tools.py` helpers — bounded by the TASK-3985 design pass and spec §7 "Stored specs with a now-server-managed key".

---

## Acceptance Criteria

- [ ] An LLM-supplied `tenant="other"` is dropped (warning logged) and the scope's caller tenant reaches the method.
- [ ] A stored spec carrying a constructor server-managed key builds with the key stripped (warning) and the app value filled.
- [ ] Existing `test_apply_tooling_specs.py` and `test_configure_applies_tooling.py` pass unchanged.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_server_managed_per_call.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_apply_tooling_server_managed.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_apply_tooling_specs.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_server_managed_per_call.py
async def test_server_managed_method_param_hidden_and_llm_value_dropped(host_plugins): ...
# packages/ai-parrot/tests/interfaces/test_apply_tooling_server_managed.py
async def test_stored_server_managed_key_stripped_on_build(host_plugins): ...
async def test_app_source_filled_at_build(host_plugins): ...
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

**Completed by**: sdd-worker (tramo B1, sequential fallback)
**Date**: 2026-10-02
**Notes**: AbstractTool: _drop_server_managed (LLM-supplied method server-managed kwargs dropped with one warning, before validate_args), _resolve_call_kwargs/_inject_server_managed (tenant/caller/agent from require_tool_scope after validation; tools without method server params never touch the scope); execute complexity 27->26 (if/else replaced by helper). ToolInterface._strip_server_params / _fill_server_params (source=app from self.app; server left to bespoke builders). A missing scope surfaces as the generic error ToolResult until TASK-3989 (as scoped). Verified ToolkitTool._execute kwarg filter keeps injected names (they are in the bound method signature): no edit. Spec Files table lists test_apply_tooling_server_managed.py twice: created once.
**Mutation evidence**: drop removed => hidden_and_dropped RED; inject removed => 4 tests RED; strip removed => stripped_on_build RED; fill removed => app_source_filled RED; restored.

**Deviations from spec**: none (handler modules are now packages; edit sites re-anchored)
