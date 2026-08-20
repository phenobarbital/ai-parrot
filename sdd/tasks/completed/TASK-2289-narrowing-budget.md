# TASK-2289: Narrowing budget — rank-and-bound the exposed tool set

**Feature**: FEAT-434 — Claude Agent Tool Bridge
**Spec**: `sdd/specs/claude-agent-tool-bridge.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2285, TASK-2287, TASK-2288
**Assigned-to**: unassigned

---

## Context

Claude Code performs **no** narrowing of its own: every exposed MCP tool is
loaded eagerly at session `init` (measured — 1 exposed → 1 listed, 25 exposed →
25 listed; spec §6). Context and cost therefore grow one-for-one with what the
bridge hands over, and bounding it is parrot's job.

This task connects `ToolManager.rank_tools()` (TASK-2285) to
`ClaudeAgentToolBridge` (TASK-2287) so only the top `max_exposed_tools` tools,
ranked against the turn's prompt, reach the sub-agent.

---

## Scope

- Implement `ClaudeAgentToolBridge.select(query: str, limit: int) -> list[AbstractTool]`
  using `ToolManager.rank_tools()`.
- Call it from the `_build_options()` injection path with the threaded prompt and
  `max_exposed_tools`.
- Log what was dropped — count plus the dropped tool names — at WARNING when the
  registry exceeds the budget. Silent truncation is explicitly forbidden: it
  reads as "covered everything" when it didn't.
- Cover the boundary cases: registry smaller than the budget (expose all, no
  warning), budget of 0, and an empty or whitespace-only prompt (fall back to a
  stable order rather than an empty selection).
- Write unit tests.

**NOT in scope**: the ranker itself (TASK-2285); the bridge's conversion and
handlers (TASK-2287); the options fields (TASK-2288); calibrating the default
budget value (spec §8 open question — telemetry decides later).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py` | MODIFY | add `select()` |
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | MODIFY | call `select()` in the injection path |
| `tests/clients/test_claude_agent_bridge.py` | MODIFY | extend with selection tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.claude_agent_bridge import ClaudeAgentToolBridge   # TASK-2287
from parrot.tools.manager import ToolManager                           # verified
from parrot.tools.abstract import AbstractTool                         # verified: parrot/tools/abstract.py:234
```

### Existing Signatures to Use
```python
# From TASK-2285 (must be completed first):
def rank_tools(self, query: str, limit: int = 15) -> list[tuple[float, Any]]: ...
#   returns scored tool objects, best first, deterministic tie-break

# packages/ai-parrot/src/parrot/tools/manager.py — verified today
class ToolManager:
    def get_all_tools(self) -> List[Union[ToolDefinition, AbstractTool]]: ...  # line 1155
    def list_tools(self) -> List[str]: ...                             # line 1147
    def list_categories(self) -> List[str]: ...                        # line 1139
    def get_tools_by_category(self, category: str) -> List[str]: ...    # line 1143

# From TASK-2288:
class ClaudeAgentRunOptions(BaseModel):
    max_exposed_tools: int = 15
    expose_parrot_tools: bool = True
```

### Verified measurement backing this task
| parrot tools exposed | tools at `init` | of which `mcp__parrot__*` | `ToolSearch` present |
|---|---|---|---|
| 1 | 33 | 1 | yes |
| 25 | 57 | 25 | yes |

Claude Code loads them all; `ToolSearch` is always present but searches an
**already-loaded** set, so it complements this narrowing rather than replacing it.

### ⚠ Two test trees — migration residue, check before you write

`ai-parrot` was a single package with its tests at the repo root, then became a
uv monorepo; many tests were **copied or moved** into `packages/*/tests/` and the
originals were left in place. So a given module can exist in BOTH trees, and
**which copy is authoritative differs per file** — the monorepo path is not
automatically the current one.

For this feature specifically:

| Path | Status |
|---|---|
| `tests/clients/test_claude_agent.py` | **Canonical.** 15 test functions / 20 cases, `test_claude_agent_live_smoke` at line 378, last touched 2026-08-20. Extend this one. |
| `packages/ai-parrot/tests/clients/test_claude_agent.py` | Separate, older module (2026-04-27, 8 tests): `TestExtendedRunOptions`, `TestBuildOptionsForwardsExtensions`. Still tracked, still runs. Do not break it. |
| `packages/ai-parrot/tests/test_toolmanager_*.py` | Where `ToolManager` tests live (flat, not under `tests/tools/`) — e.g. `test_toolmanager_confirmation.py`, `test_toolmanager_load_tool.py`. |
| `packages/ai-parrot-integrations/tests/agentd/` | Where agentd tests live. Unambiguous — no root duplicate. |
| `tests/integration/` | Root integration tree; exists and is where the live tests go. |

**Before creating or editing a test file**, check whether a same-named module
exists in the other tree (`git ls-files | grep <name>`) and compare mtimes /
content. Editing the stale copy leaves the real suite untouched and the task
looks green while nothing was verified.

### Does NOT Exist
- ~~`ToolManager.rank_tools()`~~ — created by TASK-2285. Verify it exists before
  coding; do not reimplement scoring here.
- ~~`ToolManager.search_tools()` returns tool objects~~ — it returns a JSON
  string. Do not use it for selection.
- ~~Claude Code defers or narrows MCP tools~~ — it does not; see the table above.
- ~~`ClaudeAgentRunOptions.expose_tool_categories`~~ — not a field; category-based
  narrowing was NOT the chosen signal (spec §8: the ranker is).

---

## Implementation Notes

### Key Constraints
- Do not reimplement relevance scoring — delegate to `rank_tools()`.
- An empty/whitespace prompt must not produce an empty exposure; fall back to a
  stable order (e.g. the first `limit` from `get_all_tools()`) and log it.
- The dropped-tools log must name what was dropped, not just a count, so an
  operator can tell whether a missing capability was a narrowing decision.
- `self.logger` for all of it; no prints.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/manager.py:524` — how the manager already handles a query + limit

---

## Acceptance Criteria

- [ ] `select()` returns at most `limit` tools, ranked by `rank_tools()`
- [ ] The injection path passes the threaded prompt and `max_exposed_tools`
- [ ] A registry smaller than the budget exposes everything and logs no warning
- [ ] A registry larger than the budget logs the dropped count AND the dropped names
- [ ] `limit=0` exposes nothing and injects no server
- [ ] An empty or whitespace-only prompt falls back to a stable order, logged
- [ ] Nothing is silently truncated
- [ ] All tests pass: `pytest tests/clients/test_claude_agent_bridge.py -v`
- [ ] No new `ruff check` findings

---

## Test Specification

```python
class TestSelection:
    def test_returns_at_most_limit(self): ...
    def test_uses_rank_tools_order(self, monkeypatch): ...
    def test_registry_smaller_than_budget_exposes_all_without_warning(self, caplog): ...
    def test_dropped_names_are_logged(self, caplog): ...
    def test_limit_zero_injects_no_server(self): ...
    def test_blank_prompt_falls_back_to_stable_order(self, caplog): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2285, TASK-2287, TASK-2288 must be in `sdd/tasks/completed/`
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
**Notes**: Added `ClaudeAgentToolBridge.select(query, limit)`, delegating
scoring entirely to `ToolManager.rank_tools()` (never reimplemented
here). Treats the tool literally named `search_tools` as structurally
excluded from the "registry" population (mirroring `rank_tools()`'s own
exclusion) so it never shows up as a false "dropped by narrowing" entry.
`limit <= 0` returns `[]` (warns only if the registry was non-empty);
a blank/whitespace query falls back to registration order
(`get_all_tools()[:limit]`) instead of an empty selection; when the
registry exceeds `limit`, logs one WARNING naming both the dropped count
and every dropped tool's name — nothing is silently truncated.

Wired into `claude_agent.py`'s `_build_options()` injection path: it now
always calls `bridge.select(prompt or "", merged.max_exposed_tools)`
when `expose_parrot_tools` is true (regardless of registry size — an
empty selection naturally skips server injection, which also covers the
`limit=0` "no server" acceptance criterion for free), replacing the
TASK-2288 placeholder that passed the full `get_all_tools()` list
unranked.

7 new tests in `TestSelection` (`tests/clients/test_claude_agent_bridge.py`):
respects limit, delegates to `rank_tools()` (spied), registry-smaller-
than-budget silence, dropped-names-in-log content, `limit=0`, blank-
prompt stable-order fallback (compares empty vs whitespace-only), and
`search_tools` never counted as dropped. All 57 tests in
`tests/clients/test_claude_agent.py` + `test_claude_agent_bridge.py`
pass; the older `packages/ai-parrot/tests/clients/test_claude_agent.py`
(8 tests) still passes untouched. Zero new `ruff check` findings
(`claude_agent.py` stays at its 89-finding baseline; one `UP037`
quoted-annotation nit on the new `select()` signature was introduced and
immediately auto-fixed).

**Deviations from spec**: none
