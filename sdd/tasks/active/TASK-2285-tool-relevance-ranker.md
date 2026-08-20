# TASK-2285: ToolManager.rank_tools() — real relevance ranker

**Feature**: FEAT-434 — Claude Agent Tool Bridge
**Spec**: `sdd/specs/claude-agent-tool-bridge.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. The bridge must bound how many tools it hands to
the Claude Code sub-agent, because Claude Code loads every exposed MCP tool
eagerly (measured: 25 exposed → 25 listed at `init`; see spec §6 "Verified
Behavioural Measurements"). Selecting *which* tools requires a relevance
ranking, and none exists: `ToolManager.search_tools()` is a substring match
sorted alphabetically that returns a JSON **string**, not tool objects.

This task adds the ranker and refactors `search_tools()` into a thin formatter
over it, so the debt is paid for every caller instead of being routed around.

---

## Scope

- Implement `ToolManager.rank_tools(query: str, limit: int = 15) -> list[tuple[float, Any]]`
  returning scored tool objects, best score first.
- Use **lexical** scoring (token overlap over tool name + description), not
  embeddings — spec §8 open question notes embeddings would pull
  `ai-parrot-embeddings` into the core layer, which package boundaries
  discourage. Keep the scoring function small and unit-testable.
- Refactor `search_tools()` to call `rank_tools()` and format its output as the
  same JSON string it produces today.
- Preserve exactly: the return type (`str`), the `indent=2` JSON shape with
  `name`/`description` keys, the no-match message
  `f"No tools found matching '{query}'. Try a different search term."`, and the
  exclusion of the tool literally named `search_tools`.
- Write unit tests.

**NOT in scope**: the bridge module, the `max_exposed_tools` option, any
`claude_agent.py` change (TASK-2287/2288/2289), embedding-based scoring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | add `rank_tools()`; refactor `search_tools()` into a wrapper |
| `packages/ai-parrot/tests/test_toolmanager_ranker.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolManager       # verified: parrot/tools/manager.py
from parrot.tools.abstract import AbstractTool     # verified: parrot/tools/abstract.py:234
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def search_tools(self, query: str, limit: int = 15) -> str: ...    # line 524
    #   CURRENT body: lowercases query; iterates self._tools.items();
    #   skips name == "search_tools" (line 530); reads tool.description via
    #   hasattr, else dict.get('description', ''); matches with
    #   `query in name.lower() or query in desc.lower()`; appends
    #   {"name", "description"}; matches.sort(key=lambda x: x['name']);
    #   truncates to `limit`; returns json.dumps(matches, indent=2), or the
    #   no-match sentence when empty.
    def get_all_tools(self) -> List[Union[ToolDefinition, AbstractTool]]: ...  # line 1155
    def all_tools(self) -> Generator[Any, Any, Any]: ...               # line 1159
    def list_tools(self) -> List[str]: ...                             # line 1147
    def get_tool(self, tool_name: str) -> Optional[Any]: ...           # line 1127

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):                            # line 234
    name: str = None                                                   # line 249
    description: str = None                                            # line 250
```

`ToolManager._tools` is the private `Dict[str, AbstractTool | ToolDefinition]`
that `search_tools()` already iterates; `rank_tools()` may use it the same way,
or go through `get_all_tools()`.

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
- ~~`ToolManager.rank_tools()`~~ — this task creates it.
- ~~`ToolManager.search_tools()` returns ranked tools~~ — today it returns a
  JSON **string**, substring-matched, **alphabetically** sorted.
- **`ToolManager.get_tools()` is mis-annotated**: declared `-> Dict[str, Any]`
  at manager.py:1151 but it `return self._tools.values()` — a values view, not
  a dict. NEVER write `for name, tool in manager.get_tools().items()`.
- ~~a relevance/scoring helper anywhere in `parrot/tools/`~~ — none exists.

---

## Implementation Notes

### Key Constraints
- `search_tools()` is itself a **registered tool exposed to LLMs** (it skips its
  own name at manager.py:530). Changing its ordering changes what models see, so
  the return type and the no-match message must stay byte-identical; only the
  order changes (relevance instead of alphabetical). Note the change in the
  changelog.
- Ties must break deterministically (e.g. by name) so tests and prompt caches
  are stable.
- A `ToolDefinition` entry may not have `.description` as an attribute — mirror
  `search_tools()`'s existing `hasattr` / `dict.get` handling.
- Google-style docstrings + strict type hints (CLAUDE.md).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/manager.py:524` — the code being refactored
- `packages/ai-parrot/src/parrot/tools/manager.py:1033` — `get_tool_schemas()`, for how the manager already walks tools

---

## Acceptance Criteria

- [ ] `rank_tools()` returns relevance-ordered scored tool objects (not strings)
- [ ] `rank_tools()` respects `limit`
- [ ] `rank_tools()` excludes the tool named `search_tools`
- [ ] Ordering is deterministic for equal scores
- [ ] `search_tools()` still returns a JSON string with `name`/`description` keys
- [ ] `search_tools()` no-match message is unchanged, verbatim
- [ ] `search_tools()` delegates to `rank_tools()` (no duplicated matching logic)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_toolmanager_ranker.py -v`
- [ ] No new `ruff check` findings in `packages/ai-parrot/src/parrot/tools/manager.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_toolmanager_ranker.py
import json
import pytest


class TestRankTools:
    def test_orders_by_relevance_not_alphabetically(self, manager): ...
    def test_respects_limit(self, manager): ...
    def test_excludes_search_tools_itself(self, manager): ...
    def test_deterministic_tie_break(self, manager): ...
    def test_handles_tool_without_description_attribute(self, manager): ...

class TestSearchToolsCompat:
    def test_still_returns_json_string(self, manager): ...
    def test_keys_are_name_and_description(self, manager): ...
    def test_no_match_message_verbatim(self, manager):
        out = manager.search_tools("zzzz-nothing")
        assert out == "No tools found matching 'zzzz-nothing'. Try a different search term."
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/claude-agent-tool-bridge.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
