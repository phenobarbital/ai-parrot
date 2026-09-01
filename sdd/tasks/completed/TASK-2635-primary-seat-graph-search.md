# TASK-2635: Graph search and configurable model for the primary Claude seat

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2633
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 6** (§8 Q11) plus the `DEV_FLOW_IDEATION_MODEL` key
from §8 Q13.

Two changes to the primary `sdd-ideation` seat:

1. **Graph search.** The seat currently gets a one-shot `graph_context` string. Q11
   resolved that it should get interactive wiki tools too — it does most of the
   research, so it benefits most.
2. **Configurable model.** `ideation.py:338` hardwires `claude-sonnet-4-6`. Q13
   resolved this to a `DEV_FLOW_IDEATION_MODEL` key defaulting to `claude-opus-5`.

**The non-obvious part:** allow-listing `mcp__wikitoolkit__*` is **not sufficient**.
`ClaudeCodeDispatchProfile.strict_mcp_config` defaults to `True`
(`models/claude.py:33`), which makes the dispatched headless CLI **ignore the
filesystem `.mcp.json`** — and there is **no `mcp_servers` field** on the profile
today. The servers must be passed explicitly.

⚠️ **FEAT-479 also edits `dispatchers/claude.py`.** Keep this additive; coordinate
before merging.

---

## Scope

- Add `mcp_servers: Optional[Dict[str, Any]] = None` to
  `ClaudeCodeDispatchProfile` (`models/claude.py:10`).
- Pass it into `ClaudeAgentRunOptions` in
  `ClaudeCodeDispatcher._resolve_run_options()` (`claude.py:440-451`).
- In `IdeationNode._dispatch` (`ideation.py:286`): register the `wikitoolkit` stdio
  server and extend `allowed_tools` (`ideation.py:331`) with
  `mcp__wikitoolkit__wiki_query`, `mcp__wikitoolkit__wiki_page`,
  `mcp__wikitoolkit__wiki_related`.
- **Keep `strict_mcp_config=True`.** Do not flip it.
- Replace the hardwired `model="claude-sonnet-4-6"` (`ideation.py:338`) with
  `conf.DEV_FLOW_IDEATION_MODEL` (default `claude-opus-5`); add the conf key.
- Unit tests.

**NOT in scope**: giving the partner MCP tools (it uses FEAT-484's toolkit); any
change to `ResearchNode`'s profile; write-capable MCP tools
(`wiki_remember` / `wiki_note` are **not** in the allow-list).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py` | MODIFY | Add `mcp_servers` field |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | Pass `mcp_servers` through |
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` | MODIFY | Server + tools + configurable model |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_FLOW_IDEATION_MODEL` |
| `packages/ai-parrot/tests/flows/dev_flow/test_ideation_graph_search.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Dict, Optional
from parrot import conf
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py
class ClaudeCodeDispatchProfile(BaseModel):                          # line 10
    subagent: Optional[...]                                          # line 18
    system_prompt_override: Optional[str] = None                     # line 28
    allowed_tools: List[str] = Field(default_factory=list)           # line 29
    permission_mode: Literal[...] = "default"                        # line 30
    setting_sources: List[Literal["user","project","local"]] = Field(
        default_factory=lambda: ["project"])                         # line 31
    strict_mcp_config: bool = Field(default=True, ...)               # line 32-44
        # "When True (the default), the dispatched headless CLI ignores
        #  claude.ai account connectors and filesystem .mcp.json, using
        #  only MCP servers explicitly provided. ... Set False only when a
        #  dispatch genuinely needs the inherited MCP surface."
    allow_project_root_cwd: bool = Field(...)                        # line 45
    # NO mcp_servers field exists. This task adds it.

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
    return ClaudeAgentRunOptions(                                    # line 440
        cwd=cwd,
        permission_mode=profile.permission_mode,
        allowed_tools=list(profile.allowed_tools) or None,           # line 443
        agents=agents_dict,
        setting_sources=list(profile.setting_sources) if profile.setting_sources else None,  # line 445
        strict_mcp_config=profile.strict_mcp_config,                 # line 446
        env=self._resolve_dispatch_env() or None,
        extra_args=extra_args,
        system_prompt=system_prompt,
        model=profile.model,
    )                                                                # ends line 451

# packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
    async def _dispatch(...)                                         # line 286
        profile = ClaudeCodeDispatchProfile(
            subagent=None,
            system_prompt_override=load_subagent_definition("sdd-ideation"),
            permission_mode="acceptEdits",                           # line 329
            allowed_tools=["Read","Grep","Glob","Bash","Write","Edit"],  # line 331
            allow_project_root_cwd=True,                             # line 336
            model="claude-sonnet-4-6",                               # line 338  <- REPLACE
        )

# Repo MCP server registration (the shape to pass explicitly) — .mcp.json:
#   "wikitoolkit": {"command": "<venv>/bin/wikitoolkit", "args": ["mcp"], "env": {}}
# Tools it exposes: wiki_query, wiki_page, wiki_related, wiki_remember,
#   wiki_note, wiki_status  (parrot/knowledge/wiki/tools.py:155-409)
```

### Does NOT Exist

- ~~`ClaudeCodeDispatchProfile.mcp_servers`~~ — **does not exist today.** This task
  adds it. Verify by reading `models/claude.py` before assuming otherwise.
- ~~filesystem `.mcp.json` reaching a dispatched run~~ — **it does not**, because
  `strict_mcp_config` defaults to `True` (`models/claude.py:33`). Allow-listing
  `mcp__wikitoolkit__*` alone will silently do nothing.
- ~~`strict_mcp_config=False` as the fix~~ — the field's own docstring records that
  inheriting the operator's connector/OAuth surface makes non-interactive runs exit
  with an **empty error result**. Do not flip it.
- ~~`claude-sonnet-4-6` remaining hardwired~~ — Q13 replaces it with
  `conf.DEV_FLOW_IDEATION_MODEL`, default `claude-opus-5`.
- ~~`claude-opus-5-20260101`-style dated ids~~ — model ids are complete as-is; never
  append a date suffix.
- ~~`wiki_remember` / `wiki_note` in the allow-list~~ — write tools; deliberately excluded.

---

## Implementation Notes

### Key Constraints

- **Default `None` ⇒ unchanged behavior.** A profile without `mcp_servers` must
  produce the same `ClaudeAgentRunOptions` as today.
- Keep `strict_mcp_config=True` and pass servers explicitly — that combination is
  the isolation property the field exists to provide.
- Read-only MCP tools only.
- Resolve the `wikitoolkit` command robustly (the `.mcp.json` entry hardcodes an
  absolute venv path; do not copy that literal into source).
- Async throughout; `self.logger`; Pydantic.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py:32-44` — read the
  `strict_mcp_config` docstring in full before touching MCP behavior.
- `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:155-409` — the tools being exposed.

---

## Acceptance Criteria

- [ ] `mcp_servers` defaults to `None`; omitted ⇒ `ClaudeAgentRunOptions.mcp_servers is None`
- [ ] Provided ⇒ passed through to `ClaudeAgentRunOptions` unchanged
- [ ] `strict_mcp_config` remains `True` for the ideation dispatch (explicit guard test)
- [ ] `allowed_tools` gains only the three read-only wiki tools; no write tools
- [ ] `DEV_FLOW_IDEATION_MODEL` defaults to `claude-opus-5`; `claude-fable-5` selectable with no code change
- [ ] No hardwired `claude-sonnet-4-6` remains in `ideation.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/ -v`
- [ ] Existing dispatcher tests still pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -k claude -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/`

---

## Test Specification

```python
class TestPrimarySeatGraphSearch:
    def test_profile_mcp_servers_defaults_none(self):
        """Omitted => ClaudeAgentRunOptions.mcp_servers is None (unchanged behavior)."""

    def test_mcp_servers_passed_through(self):
        """Provided servers reach ClaudeAgentRunOptions unchanged."""

    def test_strict_mcp_config_remains_true(self):
        """GUARD: the ideation profile never flips strict_mcp_config to False."""

    def test_allowed_tools_readonly_wiki_only(self):
        """wiki_query/page/related present; wiki_remember/wiki_note absent."""

    def test_ideation_model_configurable(self, monkeypatch):
        """Defaults to claude-opus-5; DEV_FLOW_IDEATION_MODEL overrides it."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 6, §8 Q11 and Q13).
2. **Check dependencies** — TASK-2633 in `sdd/tasks/completed/` (both touch `ideation.py`).
3. **Verify the Codebase Contract** — especially that `mcp_servers` still does not
   exist and `strict_mcp_config` still defaults to `True`. **FEAT-479 is editing
   `dispatchers/claude.py`**, so re-read `claude.py:435-455` before editing.
4. **Confirm the `mcp_servers` shape** `ClaudeAgentRunOptions` expects from the
   Claude Agent SDK before writing it. Do not guess the structure.
5. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
6. **Implement** — additive; default `None` preserves today's behavior.
7. **Verify** all acceptance criteria.
8. **Move this file** to `sdd/tasks/completed/TASK-2635-primary-seat-graph-search.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-01
**Notes**: Re-verified the Codebase Contract before writing anything, per
the task's own warning about FEAT-479 touching `dispatchers/claude.py`
(already merged, per TASK-2634's note). One correction found and applied
to the contract: `ClaudeAgentRunOptions` (`parrot/clients/claude_agent.py`)
**already has** an `mcp_servers: dict[str, Any] | None` field (added by
FEAT-434, unrelated prior work) — the task's "NO mcp_servers field exists"
claim is true only for `ClaudeCodeDispatchProfile`, not for
`ClaudeAgentRunOptions`. This *simplified* the task: no changes needed to
`clients/claude_agent.py` at all, just (1) add the field to the profile,
(2) forward `profile.mcp_servers` into the already-existing
`ClaudeAgentRunOptions(mcp_servers=...)` slot in `_resolve_run_options()`.
Confirmed the exact stdio MCP server config shape
(`McpStdioServerConfig` in `claude_agent_sdk.types`: `command: str`,
`args: NotRequired[list[str]]`, `env: NotRequired[dict[str,str]]`, `type`
optional) directly from the installed SDK before writing the
`.mcp.json`-shaped dict.

`_resolve_wikitoolkit_command()` resolves the CLI robustly (`shutil.which`
first, then a `sys.executable`-sibling fallback) rather than copying the
repo's `.mcp.json`'s hardcoded absolute venv path. `DEV_FLOW_IDEATION_MODEL`
added to `conf.py` (default `claude-opus-5`); the previously-hardwired
`model="claude-sonnet-4-6"` in `ideation.py`'s `_dispatch()` now reads it.
`allowed_tools` gained exactly the three read-only wiki tools
(`wiki_query`/`wiki_page`/`wiki_related`); `wiki_remember`/`wiki_note`
deliberately excluded. `strict_mcp_config` was NOT touched — stays at its
`True` default, with the server passed explicitly per the field's own
docstring warning.

9 new tests in `test_ideation_graph_search.py`: profile field defaults,
`_resolve_run_options()` pass-through (both the None-default and an
explicit-servers case), the `strict_mcp_config=True` guard, wikitoolkit
server registration, the read-only-tools-only assertion, default/
configurable model, and a source-inspection guard that the literal
`"claude-sonnet-4-6"` string no longer appears in `_dispatch`'s source.
All pre-existing `test_ideation_node.py` (25 tests) and dev_loop
`-k claude` (17 tests) tests still pass unmodified — the profile/model/
tool-list assertions there use membership checks, not exact-list
equality, so they were compatible with the additions by construction.
Full `pytest packages/ai-parrot/tests/flows/dev_flow/` (225 passed) and
`pytest packages/ai-parrot/tests/flows/dev_loop/` (1129 passed, the same
3 pre-existing `sdd-secondopinion`-parity failures reproduced on
unmodified `dev`) both show zero regressions. `ruff check` shows only
pre-existing debt (verified via line-by-line diff against `dev` — the
`dispatchers/claude.py` diff is a pure line-number shift, and
`models/claude.py`'s 2 new findings are the new field's own `Optional[...]`
annotation, matching the file's existing style).

**Deviations from spec**: none beyond the Codebase Contract correction
above (which simplified rather than complicated the implementation).
