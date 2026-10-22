# TASK-4587: ComputerAgent: default gemini-3.8-flash and enable client computer_use

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4586
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements the agent half of spec §3 Module 6. `ComputerAgent` still defaults to the shut-down `gemini-2.5-computer-use-preview-10-2025`, so it is broken today.

---

## Scope

- Default `model` → `"gemini-3.8-flash"`; update the class docstring.
- In `configure()`, set `client.computer_use = True` next to the existing safety-handler wiring.
- Tests.

**NOT in scope**: client internals (TASK-4586); toolkit (TASK-4585).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py` | MODIFY | default + opt-in wiring |
| `packages/ai-parrot-tools/tests/computer/test_agent.py` | MODIFY | tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot_tools.computer.agent import ComputerAgent  # verified: agent.py:25
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/computer/agent.py
class ComputerAgent(Agent)                                                  # line 25
def __init__(self, *, model: str = "gemini-2.5-computer-use-preview-10-2025", ...)   # line 72-75
#   bare model strings get a "google:" prefix (:106-107)
async def configure(self, app: Any = None) -> None                         # line 131
#   client = getattr(self, "_llm", None); client._computer_use_safety_handler = self._safety_handler  # line 142
```

### Does NOT Exist
- ~~`ComputerAgent.computer_use`~~ — the switch lives on the client, not the agent

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/computer/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/computer/test_agent.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/computer/agent.py#ComputerAgent",
    "sym:packages/ai-parrot-tools/src/parrot_tools/computer/agent.py#ComputerAgent.configure"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).


---

## Implementation Blueprint

### Steps (in order)
1. Change the default — *why*: legacy model shut down 2026-07-28.
2. Set `client.computer_use = True` in the existing try block — *why*: explicit opt-in (resolved decision).
3. Tests.

### `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        model: str = "gemini-2.5-computer-use-preview-10-2025",' agent.py) — :75
        model: str = "gemini-3.8-flash",
```
```python
# occurrences: 1 (verified: grep -c '                client._computer_use_safety_handler = self._safety_handler' agent.py) — :142
                client._computer_use_safety_handler = self._safety_handler
                client.computer_use = True
```
**Why**: spec §2 — the agent, not the model name, opts the client into computer use.
# FILL IN: update the class docstring (line ~28) and the comment at ~103 that names the old model

### FILL IN checklist
- [ ] docstrings mentioning the old model — bounded by AC

---

## Acceptance Criteria

- [ ] `ComputerAgent().` default resolves to `google:gemini-3.8-flash`
- [ ] after `configure()` the client has `computer_use is True`

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/computer/test_agent.py -q`
- `pytest packages/ai-parrot-tools/tests/computer/test_integration.py -q`

---

## Test Specification

```python
def test_computer_agent_default_model():
    # FILL IN: construct with existing test fixtures; assert the llm string ends with "gemini-3.8-flash"


async def test_configure_enables_computer_use(configured_agent):
    assert configured_agent._llm.computer_use is True
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug model-deprecation-followups --feature-id FEAT-719`)
2. **Read the spec** at `sdd/specs/model-deprecation-followups.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/model-deprecation-followups.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint; a changed count means the
   anchor moved (re-locate it), a `0` means drift (stop and report)
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed
   signature or path
7. **Verify** — run the Validation Commands with `PYTHONPATH` pointing at the worktree's `packages/*/src`
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4587 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
