# TASK-4533: Dispatcher `run_validation` tool, validation capability and verdict-only `run_command` routing

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4525, TASK-4529
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (dispatcher half), codex S4 (verdict data only; runner binaries must pass `allowed_commands`,
which is checked before the guard at llm.py:1904) and S7 (inject a capability, never import the engine; absent
capability ⇒ hard tool error). Today `_run_guarded_invocations` merges stdout/stderr into the tool result — the
exact leak this feature closes.

---

## Scope

- Define `ValidationCapability` (Protocol) and `LLMCodeDispatcher.set_validation_runner(capability)` mirroring `set_event_registry_resolver` (llm.py:99).
- Add the `run_validation` function tool (`{targets?: [string]}`) to `_tool_schemas`; route it in `_run_tool`; `_tool_run_validation` returns `{ok, verdict}` or the hard error when unbound.
- `_tool_run_command`: when `guard_argv` returns `verdict`, call the capability (not the argv) and return `{ok, verdict}` only; delete `_run_guarded_invocations`.
- Run the runner-recognition check BEFORE the `allowed_commands` rejection so `pnpm exec vitest` / `cargo test` reach the capability even when the binary is not allow-listed.
- `models/llm.py`: document that the engine extends `allowed_commands` per attempt with the registry's binaries (no default list change).

**NOT in scope**: Building the capability (engine, TASK-4534); native hook (TASK-4534).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | tool + capability + routing |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py` | MODIFY | allowed_commands doc |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` | MODIFY | tool + routing tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.guard import GuardOutcome, guard_argv  # llm.py:59 (already imported)
from typing import Protocol, Sequence, Dict, Any, Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                                         # line 67
    def set_event_registry_resolver(self, resolver) -> None      # line 99 — pattern to mirror
    def _tool_schemas(self, output_model) -> List[Dict[str, Any]]   # line 1301 — "run_command" at :1423, "final_output" at :1453
    async def _run_tool(self, *, tool_name, tool_args, cwd, profile, ...)   # line 1474 — `if tool_name == "run_command":` :1495
    async def _tool_run_command(self, cwd, args, profile) -> Dict[str, Any]   # line 1894 — allowed_commands check :1904; guard_argv :1945
    async def _run_guarded_invocations(self, argvs, *, cwd, timeout, hint) -> Dict[str, Any]   # line 2135 — merges stdout/stderr (remove)
# packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py
class LLMCodeDispatchProfile: allowed_commands: List[str] = Field(default_factory=lambda: [ … "pytest", … ])   # line 51
```

### Does NOT Exist
- ~~`set_validation_runner`, `_tool_run_validation`, `ValidationCapability`~~ — added here
- ~~an engine import in dispatchers/llm.py~~ — forbidden (S7)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._tool_schemas",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._run_tool",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._tool_run_command",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._run_guarded_invocations",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher.set_event_registry_resolver"
  ]
}
```

---

## Implementation Notes

- The capability is per dispatch: store it in a ContextVar or on the instance under the same semaphore discipline as `_SESSION_HOST_CTX` (llm.py dispatch()) — FILL IN choice, bounded by "one dispatcher may serve concurrent dispatches" (check `max_concurrent`).
- Tool description must say: "Runs this task's validation and returns a structured verdict. Never returns raw test output."

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Protocol + setter — *why*: S7.
2. `run_validation` tool + routing — *why*: seat iteration surface.
3. `run_command` verdict branch + remove `_run_guarded_invocations` — *why*: S4 leak.
4. Tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            if tool_name == "run_command":' …/dispatchers/llm.py)
# INSERT above it (llm.py:1495):
            if tool_name == "run_validation":
                return await self._tool_run_validation(cwd, tool_args, profile)

# NEW method on LLMCodeDispatcher:
    async def _tool_run_validation(self, cwd: str, args: Dict[str, Any], profile: LLMCodeDispatchProfile) -> Dict[str, Any]:
        """Run the bound task-tier validation; verdict data only (FEAT-709)."""
        capability = self._current_validation_capability()
        if capability is None:
            return {"ok": False, "error": "validation capability not bound for this dispatch"}
        targets = [str(t) for t in (args.get("targets") or [])]
        verdict = await capability.run(targets=targets)
        return {"ok": verdict.get("status") == "passed", "verdict": verdict}

# occurrences: 1 (verified: grep -c '                "run_command",' …/dispatchers/llm.py)
# INSERT a new self._function_tool("run_validation", <description>, {"type":"object","properties":
#   {"targets":{"type":"array","items":{"type":"string"}}},"additionalProperties":False}) BEFORE the run_command tool.
```
**Why**: Placing the tool first nudges seats toward it; routing order puts it before run_command.

### FILL IN checklist
- [ ] capability storage (ContextVar vs instance) and `_current_validation_capability`
- [ ] `set_validation_runner`
- [ ] `_tool_run_command` verdict branch ordering vs allowed_commands
- [ ] remove `_run_guarded_invocations` and its tests
- [ ] tests

---

## Acceptance Criteria

- [ ] `run_validation` appears in `_tool_schemas`.
- [ ] Unbound capability ⇒ hard error dict.
- [ ] `run_command ["pytest"]` inside an attempt ⇒ capability called; result has `verdict`, no `stdout`/`stderr` keys.
- [ ] `run_command ["pnpm","exec","vitest","run"]` reaches the capability even though `pnpm` is not allow-listed.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_family_parity.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4533 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator); implemented by sonnet (native), 1 attempt; ValidationCapability held in a ContextVar
**Date**: 2026-10-20
**Notes**: Merge-tier validation: only the 5 pre-existing bwrap failures in test_llm_code_dispatcher.py remain. Closed via close_task.sh.

**Deviations from spec**: none
