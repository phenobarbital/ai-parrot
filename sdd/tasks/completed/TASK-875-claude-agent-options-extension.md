# TASK-875: Extend `ClaudeAgentRunOptions` with `agents`, `setting_sources`, `extra_args`, `system_prompt`

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §7 Risk **R1**: this feature is a **hard consumer** of FEAT-124's
`ClaudeAgentClient` / `ClaudeAgentRunOptions`. The dispatcher (TASK-878)
needs four additional run-options fields that FEAT-124 has not yet
exposed:

1. `agents: dict[str, AgentDefinition]` — programmatic subagent binding
   (the primary mechanism for `sdd-research`, `sdd-worker`, `sdd-qa`),
   `claude_agent_sdk/types.py:1389`.
2. `setting_sources: list[Literal["user","project","local"]]` — loads
   `.claude/agents/` from the project as a fallback,
   `claude_agent_sdk/types.py:1391`.
3. `extra_args: dict[str, str | None]` — passes arbitrary CLI flags such
   as `--output-format=json` and `--json-schema=<path>` for structured
   output (resolves spec §8 open question — JSON-schema in v1).
4. `system_prompt: Optional[str]` — required for the
   `subagent=None, system_prompt_override="..."` generic-session path
   (spec §3 Module 2 + Test `test_dispatch_profile_generic_session_fallback`).

This is a **small, additive extension** to FEAT-124 — no behavior change
for callers that don't pass the new fields. Per spec R1: "coordinate any
extension needed as small additions to FEAT-124 rather than forking."

---

## Scope

- Add four new optional fields on `ClaudeAgentRunOptions` (model in
  `parrot/clients/claude_agent.py`):
  - `agents: Optional[Dict[str, "AgentDefinition"]] = None`
  - `setting_sources: Optional[List[Literal["user","project","local"]]] = None`
  - `extra_args: Optional[Dict[str, Optional[str]]] = None`
  - `system_prompt: Optional[str] = None`
- Wire each field through to `ClaudeSDKClient` / `ClaudeAgentOptions` in
  `ClaudeAgentClient.ask_stream` (or the equivalent merge function around
  `claude_agent.py:236-269` — match the existing pattern).
- Keep the `AgentDefinition` import lazy to preserve the spec §7 R1
  invariant that `import parrot.clients.claude_agent` does NOT require
  `claude-agent-sdk` to be installed unless the user actually calls into
  the client. Use a string forward-reference ("AgentDefinition") in
  the model field annotation and resolve via
  `if TYPE_CHECKING: from claude_agent_sdk.types import AgentDefinition`.
- Add unit tests covering field defaults and option merging.

**NOT in scope**:
- Any new public method on `ClaudeAgentClient`.
- The dispatcher itself (TASK-878).
- Re-exporting `ClaudeAgentRunOptions` outside its current location.
- Changing the `__init__` signature of `ClaudeAgentClient`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | MODIFY | Add four fields + merge logic |
| `packages/ai-parrot/tests/clients/test_claude_agent.py` | MODIFY (or CREATE if missing) | Unit tests for the new fields |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing in claude_agent.py
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

# At runtime ClaudeSDKClient / ClaudeAgentOptions are imported lazily.
# Add for type-checking only — DO NOT import unconditionally:
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from claude_agent_sdk.types import AgentDefinition
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/claude_agent.py
class ClaudeAgentRunOptions(BaseModel):                 # line 62
    allowed_tools: Optional[List[str]]                  # line 91
    disallowed_tools: Optional[List[str]]               # line 95
    permission_mode: Optional[str]                      # line 99
    cwd: Optional[str]                                  # line 103
    # ← NEW fields go here, then through to kwargs in ask_stream:
    # agents, setting_sources, extra_args, system_prompt

class ClaudeAgentClient(AbstractClient):                # line 173
    def __init__(self, *, cwd=None, permission_mode=None, ...):  # line 198
    async def ask_stream(self, prompt, *, options=None, ...):     # ~line 230
        # The merge block at lines 256-269 builds `kwargs` for
        # ClaudeAgentOptions. EXTEND that block — copy the pattern:
        # if merged.allowed_tools is not None:
        #     kwargs["allowed_tools"] = merged.allowed_tools
```

```python
# claude_agent_sdk/types.py — relevant fields on ClaudeAgentOptions:
class ClaudeAgentOptions:
    allowed_tools: list[str]                            # line 1346
    permission_mode: PermissionMode | None              # line 1349
    cwd: str | Path | None                              # line 1361
    extra_args: dict[str, str | None]                   # exists (CLI passthrough)
    agents: dict[str, AgentDefinition] | None           # line 1389
    setting_sources: list[SettingSource] | None         # line 1391
    system_prompt: str | None                           # exists
```

### Does NOT Exist

- ~~`ClaudeAgentRunOptions.subagent`~~ — there is no `subagent` field on
  the run options. Subagent binding is per-dispatch via the `agents=...`
  dict (the dispatcher in TASK-878 owns that mapping).
- ~~`ClaudeAgentRunOptions.json_schema`~~ — no first-class JSON-schema
  field. Pass via `extra_args={"output-format": "json", "json-schema":
  "<path>"}`.
- ~~`AbstractClient.complete_async`~~ — base method is `complete()`
  (spec §6 "Does NOT Exist").
- ~~Top-level `from claude_agent_sdk import AgentDefinition`~~ — would
  break `import parrot.clients.claude_agent` in environments without
  the `[claude-agent]` extra. Always guard behind `TYPE_CHECKING` or
  do a runtime import inside the method body.

---

## Implementation Notes

### Pattern to Follow

Match the EXACT shape of the existing fields. For each new field add:

1. A `Field(default=None, description="...")` declaration on
   `ClaudeAgentRunOptions`.
2. A merge clause inside `ask_stream` (around line 256-269):

```python
if merged.agents is not None:
    kwargs["agents"] = merged.agents
if merged.setting_sources is not None:
    kwargs["setting_sources"] = merged.setting_sources
if merged.extra_args is not None:
    kwargs["extra_args"] = merged.extra_args
if merged.system_prompt is not None:
    kwargs["system_prompt"] = merged.system_prompt
```

### Key Constraints

- Backward compatible: all four fields default to `None`. Existing
  callers continue to work unchanged.
- Type annotation on `agents` uses `Dict[str, "AgentDefinition"]` with
  the string forward-reference. Add
  `model_config = ConfigDict(arbitrary_types_allowed=True)` ONLY if
  Pydantic complains; otherwise prefer the forward-ref approach so the
  model stays lazy.
- `setting_sources` accepts the same literal set the SDK accepts:
  `Literal["user", "project", "local"]`.
- `extra_args` allows `None`-valued entries (`Optional[str]`) because
  the SDK uses `None` to mean "boolean flag with no value" (e.g.,
  `--verbose`).
- Tests MUST not require a working `claude-agent-sdk` install: mock
  `ClaudeSDKClient` the same way existing FEAT-124 tests do.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/claude_agent.py:62-103` — the
  existing `ClaudeAgentRunOptions` field block.
- `packages/ai-parrot/src/parrot/clients/claude_agent.py:256-269` — the
  existing merge block.

---

## Acceptance Criteria

- [ ] `ClaudeAgentRunOptions` exposes `agents`, `setting_sources`,
  `extra_args`, `system_prompt` — all `Optional[...] = None`.
- [ ] `ask_stream` forwards each non-None field into the
  `ClaudeAgentOptions` constructor kwargs.
- [ ] `ClaudeAgentRunOptions().model_dump(exclude_none=True) == {}`
  (no defaults leak out).
- [ ] `import parrot.clients.claude_agent` succeeds in an environment
  WITHOUT `claude-agent-sdk` installed (the model definition does not
  trigger the SDK import). Verify by mocking absence in the test.
- [ ] No existing test in `tests/clients/test_claude_agent.py` breaks.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/claude_agent.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_claude_agent.py (add to existing file)
from parrot.clients.claude_agent import ClaudeAgentRunOptions


class TestExtendedRunOptions:
    def test_new_fields_default_none(self):
        opts = ClaudeAgentRunOptions()
        assert opts.agents is None
        assert opts.setting_sources is None
        assert opts.extra_args is None
        assert opts.system_prompt is None

    def test_setting_sources_literal_validated(self):
        opts = ClaudeAgentRunOptions(setting_sources=["project", "user"])
        assert opts.setting_sources == ["project", "user"]

    def test_extra_args_accepts_none_values(self):
        opts = ClaudeAgentRunOptions(extra_args={"verbose": None,
                                                 "output-format": "json"})
        assert opts.extra_args["verbose"] is None
        assert opts.extra_args["output-format"] == "json"


# Additionally extend the existing ask_stream test suite to assert that
# non-None values flow through to the patched ClaudeSDKClient mock.
```

---

## Agent Instructions

1. Read `parrot/clients/claude_agent.py` end-to-end first. Mirror the
   existing field/merge pattern.
2. Update index → `"in-progress"`.
3. Implement; ensure existing tests still pass:
   `pytest packages/ai-parrot/tests/clients/ -v`.
4. Move file to completed; update index; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-27
**Notes**: Added 3 new fields to `ClaudeAgentRunOptions` (`agents`,
`setting_sources`, `extra_args`); `system_prompt` was already present and is
covered by tests for parity. Wired all three through `_build_options`.
`AgentDefinition` is forward-referenced via `TYPE_CHECKING` plus a
`Dict[str, Any]` runtime alias so the module stays importable without the
`[claude-agent]` extra. 8 unit tests cover defaults, literal validation, dict
acceptance, and merge-into-kwargs behavior.
**Deviations from spec**: The task scope mentions adding `system_prompt` as
new — but it already existed at `claude_agent.py:111`. Tests assert its
default-None behavior for parity. Pure additive change; no breaking changes.
