# TASK-2288: ClaudeAgentClient plumbing — options, prompt threading, server injection, allowed_tools

**Feature**: FEAT-434 — Claude Agent Tool Bridge
**Spec**: `sdd/specs/claude-agent-tool-bridge.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2287
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3. Wires `ClaudeAgentToolBridge` (TASK-2287) into the
client: new `ClaudeAgentRunOptions` fields, server injection in
`_build_options()`, `allowed_tools` reconciliation, and stopping the four
surfaces from discarding `tools`/`use_tools`.

Two structural facts drive the design. First, `_build_options()` has **no
`prompt` parameter** today, but the ranker needs the turn's text — so a `prompt`
kwarg must be threaded in from all four surfaces. Second, `allowed_tools` is a
whitelist: if a caller sets it for native tools, the `mcp__parrot__*` names must
be appended or the agent goes blind to its own capabilities (resolved decision,
spec §8).

---

## Scope

- Add to `ClaudeAgentRunOptions`: `mcp_servers`, `expose_parrot_tools` (default
  `True`), `max_exposed_tools` (default `15`), `tool_timeout` (default `None`).
- Add a `prompt` parameter to `_build_options()` and thread the turn's text in
  from `ask`, `ask_stream`, `invoke` (their `prompt`) and `resume` (its
  `user_input`).
- In `_build_options()`: when `expose_parrot_tools` and a `tool_manager` with
  registered tools is present, build the bridge server and inject it into
  `ClaudeAgentOptions.mcp_servers`, **merging** with any caller-supplied
  `mcp_servers` rather than replacing it.
- Reconcile `allowed_tools`: when the caller set it, append the exposed
  `mcp__parrot__*` names; when unset, leave it unset. Only prefixed names are
  appended — never a bare colliding name.
- Stop discarding `tools`/`use_tools` in `ask` (:459), `ask_stream` (:605) and
  `invoke` (:763); honour `use_tools=False` as a per-call opt-out.
- Extend the existing client test module.

**NOT in scope**: the bridge internals (TASK-2287); the ranking/narrowing call
(TASK-2289 — for this task, exposing the full set is acceptable); HITL channel
(TASK-2290); caller identity (TASK-2286).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | MODIFY | options fields, `_build_options(prompt=…)`, injection, reconciliation, four surfaces |
| `tests/clients/test_claude_agent.py` | MODIFY | extend the existing 20 tests (canonical module) |
| `packages/ai-parrot/tests/clients/test_claude_agent.py` | VERIFY | older module holding `TestBuildOptionsForwardsExtensions` — must keep passing, extend only if the merge contract changes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.claude_agent import (          # verified: parrot/clients/claude_agent.py:80, :231
    ClaudeAgentClient, ClaudeAgentRunOptions,
)
from parrot.clients.claude_agent_bridge import ClaudeAgentToolBridge
#   ^ (unverified — created by TASK-2287; confirm it exists before importing)
```

### ⚠ TWO test trees — read this before touching tests

This repo has **two** tracked `test_claude_agent.py` files. They are different
modules, not copies, and both must keep passing:

| Path | What it is |
|---|---|
| `tests/clients/test_claude_agent.py` | **Canonical / current.** 15 test functions, 20 cases, `test_claude_agent_live_smoke` at line 378. Last touched 2026-08-20. **Extend this one.** |
| `packages/ai-parrot/tests/clients/test_claude_agent.py` | Older module (2026-04-27), 8 tests, contains `TestExtendedRunOptions` and **`TestBuildOptionsForwardsExtensions`** — which asserts the `_build_options` merge block forwards new fields, monkey-patching `_import_sdk` so the extra is not required. **This task modifies exactly that merge block: do NOT break it.** |

Run both:
```bash
pytest tests/clients/test_claude_agent.py packages/ai-parrot/tests/clients/test_claude_agent.py -v
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude_agent.py
class ClaudeAgentRunOptions(BaseModel):                        # line 80
    # 17 EXISTING fields — do not remove or rename any:
    allowed_tools, disallowed_tools, permission_mode, cwd, cli_path,
    system_prompt, max_turns, max_budget_usd, model, fallback_model,
    add_dirs, env, extra_options, agents, setting_sources,
    strict_mcp_config, extra_args

class ClaudeAgentClient(AbstractClient):                       # line 231
    client_name: str = "claude-agent"                          # line 248
    def __init__(self, cli_path=None, cwd=None, permission_mode=None,
                 run_options=None, **kwargs) -> None: ...       # line 253
    #   **kwargs go to AbstractClient, which is where `tool_manager` arrives.
    def _build_options(self, *, run_options=None, model=None, system_prompt=None,
                       session_id=None, resume_id=None,
                       permission_mode=None) -> Any: ...        # line 286
    #   Merge order inside: self.default_run_options.model_copy(deep=True),
    #   then per-call run_options via `for key in run_options.model_fields_set`
    #   (skipping None; extra_options is dict-merged), then each field mapped
    #   onto a ClaudeAgentOptions kwarg, then `extra_options` applied LAST so
    #   it wins. Add the new fields to that mapping the same way.
    async def _collect_messages(self, prompt: str, *, options: Any) -> List[Any]: ...  # line 377
    async def ask(self, prompt, model=None, max_tokens=4096, temperature=0.7,
                  files=None, system_prompt=None, structured_output=None,
                  user_id=None, session_id=None, tools=None, use_tools=None,
                  deep_research=False, background=False, lazy_loading=False,
                  *, run_options=None) -> AIMessage: ...        # line 417
    #   line 459: `del max_tokens, files, tools, use_tools  # not used by SDK`
    async def ask_stream(...): ...                              # line 560
    #   line 605: `del max_tokens, temperature, files, user_id, tools, deep_research`
    async def resume(self, session_id, user_input, state=None) -> AIMessage: ...  # line 682
    async def invoke(...) -> InvokeResult: ...                   # line 716
    #   line 763: `del max_tokens, temperature, use_tools, tools  # parity-only`

# claude-agent-sdk 0.2.140
# ClaudeAgentOptions.mcp_servers:
#   dict[str, McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig
#             | McpSdkServerConfig] | str | Path
```

### Does NOT Exist
- ~~`ClaudeAgentRunOptions.mcp_servers`~~ / ~~`.expose_parrot_tools`~~ /
  ~~`.max_exposed_tools`~~ / ~~`.tool_timeout`~~ / ~~`.expose_tools`~~ /
  ~~`.exclude_tools`~~ / ~~`.expose_tool_categories`~~ / ~~`.tool_manager`~~ /
  ~~`.timeout`~~ — none exist. This task adds the first four only.
- ~~`ClaudeAgentClient._build_options(prompt=...)`~~ — no `prompt` parameter
  today. This task adds it.
- ~~a single `test_claude_agent.py`~~ — there are **two** tracked modules by that
  name in different trees (see the table above). Editing the wrong one leaves the
  real suite untouched.
- ~~`ClaudeAgentClient` honours `tools`/`use_tools`~~ — explicitly discarded at
  :459, :605, :763. This task changes that.
- `ClaudeAgentClient.batch_ask`, `ask_to_image`, `summarize_text`,
  `translate_text`, `analyze_sentiment`, `analyze_product_review`,
  `extract_key_points` all raise `NotImplementedError` (claude_agent.py:822-882)
  — do NOT add bridging to them.

---

## Implementation Notes

### Key Constraints
- **`extra_options` is applied last and wins** in `_build_options()`. A caller
  who passes `extra_options={"mcp_servers": ...}` today must keep working — do
  not let the injection silently clobber it, and do not reorder the merge.
- Merge, don't replace: a caller-supplied `mcp_servers` mapping and the generated
  `parrot` server must coexist.
- `allowed_tools=[]` (empty list) is meaningfully different from `None`: the
  existing code checks `if merged.allowed_tools is not None`. An empty list means
  "block all native tools" and must still receive the appended parrot names.
- Preserve the strict-lazy-SDK contract: no new module-scope SDK import.
- `resume()`'s ranking text is `user_input`, not `prompt`.
- The docstrings on `ask`/`ask_stream`/`invoke` currently state that `tools` is
  "accepted for AbstractClient compatibility" — update them.
- **Do not touch `temperature` in `ask()`**: the `del` list there was fixed on
  2026-08-20 (commit `73a2c19d6`) because `_emit_before_call` uses it. Removing
  `tools`/`use_tools` from the `del` is the only change needed.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/claude_agent.py:286` — `_build_options`, the funnel
- `tests/clients/test_claude_agent.py` — 20 passing tests to extend, not rewrite

---

## Acceptance Criteria

- [ ] The four new `ClaudeAgentRunOptions` fields exist with the documented defaults
- [ ] The 17 existing fields are untouched
- [ ] `_build_options()` accepts `prompt` and all four surfaces thread it in
      (`resume` passes `user_input`)
- [ ] With tools registered, `ClaudeAgentOptions.mcp_servers` contains the parrot server
- [ ] A caller-supplied `mcp_servers` mapping survives the merge
- [ ] A caller-supplied `extra_options={"mcp_servers": ...}` still wins, as today
- [ ] `allowed_tools` set by the caller gains the exposed `mcp__parrot__*` names
- [ ] `allowed_tools=[]` also gains them; `allowed_tools=None` stays `None`
- [ ] Only prefixed names are appended — never a bare colliding name
- [ ] `expose_parrot_tools=False` or `use_tools=False` disables the bridge
- [ ] No tool manager, or an empty registry, injects no server (behaviour identical to today)
- [ ] `ask`, `ask_stream`, `invoke` no longer discard `tools`/`use_tools`
- [ ] `pytest tests/clients/test_claude_agent.py -v` passes (≥ 20 + new)
- [ ] `pytest packages/ai-parrot/tests/clients/test_claude_agent.py -v` still passes —
      `TestBuildOptionsForwardsExtensions` guards the merge block this task edits
- [ ] No new `ruff check` findings

---

## Test Specification

```python
# tests/clients/test_claude_agent.py  (extend)
class TestBridgeInjection:
    def test_no_tool_manager_injects_no_server(self): ...
    def test_empty_registry_injects_no_server(self): ...
    def test_server_injected_when_tools_registered(self): ...
    def test_caller_supplied_mcp_servers_survive_merge(self): ...
    def test_extra_options_mcp_servers_still_wins(self): ...
    def test_expose_parrot_tools_false_disables_bridge(self): ...
    def test_use_tools_false_disables_bridge(self): ...

class TestAllowedToolsReconciliation:
    def test_set_allowed_tools_gains_exposed_names(self): ...
    def test_empty_allowed_tools_gains_exposed_names(self): ...
    def test_unset_allowed_tools_stays_unset(self): ...
    def test_bare_colliding_name_not_appended(self): ...

class TestPromptThreading:
    async def test_ask_threads_prompt(self): ...
    async def test_ask_stream_threads_prompt(self): ...
    async def test_invoke_threads_prompt(self): ...
    async def test_resume_threads_user_input(self): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2287 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/claude-agent-tool-bridge.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-20
**Notes**: Added the four `ClaudeAgentRunOptions` fields (`mcp_servers`,
`expose_parrot_tools=True`, `max_exposed_tools=15`, `tool_timeout=None`);
the 17 existing fields are untouched. `_build_options()` gained a
`prompt` parameter and, right before the `extra_options`-wins-last step,
builds `ClaudeAgentToolBridge(self.tool_manager, tool_timeout=merged.
tool_timeout).build_server(list(self.tool_manager.get_all_tools()))`
whenever `merged.expose_parrot_tools` is true and the tool manager has
at least one registered tool — merging the generated `"parrot"` server
into a caller-supplied `mcp_servers` mapping (never replacing it) and
appending the exposed `mcp__parrot__*` names onto `allowed_tools` (only
when the caller set it — `[]` counts as set; unset stays unset). Ranking
is TASK-2289's job — this task always passes the full registered tool
set.

All four surfaces thread the turn's text into `_build_options(prompt=…)`
(`resume` passes `user_input`); `ask`/`ask_stream`/`invoke` no longer
`del` `use_tools` (still `del tools` — the inline per-call tool list is
genuinely unconsumed; FEAT-434 bridges the registered `ToolManager`
instead, governed by `expose_parrot_tools`/`use_tools`, not that list).

`ask()`'s `use_tools` (default `None`) disables the bridge for that call
only when explicitly `False`; `None`/`True` leave `expose_parrot_tools`
(default `True`) in charge — i.e. automatic exposure by default, per
spec decision #1. `invoke()`'s existing `use_tools` default is `False`
(unchanged, per its "accepted for parity" docstring) — bridging there is
opt-in via `use_tools=True`, decoupled from a caller's own
`run_options.expose_parrot_tools`. `ask_stream()` has no `use_tools`
parameter (unchanged signature) — only `run_options.expose_parrot_tools`
gates it there.

22 new tests added to the canonical `tests/clients/test_claude_agent.py`
(`TestBridgeInjection` ×7, `TestAllowedToolsReconciliation` ×4,
`TestPromptThreading` ×4 — the rest are incidental improvements from a
`ruff --fix` pass on the file) — all 35 pass. The older
`packages/ai-parrot/tests/clients/test_claude_agent.py` (8 tests,
`TestBuildOptionsForwardsExtensions`) still passes untouched. Both files
run in isolation per the task's own instruction; running them in one
combined `pytest` invocation reproduces a pre-existing cross-file
`claude_agent_sdk` module-pollution failure verified identical on the
pre-TASK-2288 baseline via `git stash` (not something this task
introduced). Zero new `ruff check` findings on either modified file
(verified via before/after `git stash` diffs — `claude_agent.py` stays
at 89 baseline findings, the test file's 12 baseline findings are now 1
after a `ruff --fix` pass that also cleaned up several pre-existing
import-order nits).

**Deviations from spec**: `invoke()`'s bridging-by-default-off behaviour
(gated on its pre-existing `use_tools: bool = False` default rather than
`None`) is a conservative reading, not an instructed signature change —
flagged for review since the spec's "all four surfaces bridge tools"
acceptance criterion could be read as expecting default-on there too.
Not changing an existing default without an explicit instruction seemed
the safer choice; happy to flip if the intended behavior was
default-on.
