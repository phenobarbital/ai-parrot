# TASK-3662: AgentTalk._apply_user_toolkit_overrides on the session ToolManager

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3645, TASK-3654, TASK-3661
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (7), §3 Module 9; design research S2 + S11; AC9, AC10, AC11 (always on — no flag).
The ask path swaps `agent.tool_manager` for the session TM wholesale (agent.py:1683-1686), so the
override view MUST start from `agent.tool_manager.clone()` and replace only the overridden
toolkit's tools. A session marker `(tooling_revision, overrides_revision)` avoids rebuilding every request.

---

## Scope

- Add `async def _apply_user_toolkit_overrides(self, agent, request_session, tool_manager) -> ToolManager | None`.
  - user_id: same extraction as `_restore_user_mcp_servers` (attrs `user_id`/`id`/`username` on the session).
  - overrides = `await ToolkitConfigService().load(user_id, agent.name)`; none → return input unchanged.
  - marker key `f"{agent.name}_toolkit_overrides_rev"`; value `f"{agent._tooling_revision}:{await svc.revision(...)}"`;
    equal to stored AND a session TM exists → return it unchanged.
  - Agent defaults: the specs the bot was built with — read `getattr(agent, "_pending_toolkit_specs", [])`
    (the list TASK-3654 recorded). Only slugs present there can be overridden.
  - Merge: `defaults_params = await hydrate_params(default_spec)`; override params filtered to
    `default_spec.user_overridable` (stale keys ignored — AC10); user secrets via
    `retrieve_vault_credential(user_id, ref)`.
  - base = `tool_manager if tool_manager is not None else agent.tool_manager.clone()`; for every tool name
    in `base.list_tools()` whose `get_toolkit_owner(base.get_tool(name))` is an instance of the resolved class
    → `base.remove_tool(name)`; register `cls(**filtered)`.
  - Store `request_session[f"{agent.name}_tool_manager"] = base` and the marker; return base.
  - Any failure → WARNING (slug + exception type), return the input TM.
- Call sites: POST path — inside the `if request_session and not is_user_bot:` block, after
  `user_tool_manager = request_session.get(session_key)`, set
  `user_tool_manager = await self._apply_user_toolkit_overrides(agent, request_session, user_tool_manager)`
  BEFORE the PBAC filter (:1558). PATCH path — after the `enable_mcp_restore` block (:1007-1012).

**NOT in scope**: storing overrides (TASK-3661); changing the pre-existing PATCH TM construction.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Add _apply_user_toolkit_overrides; call it in POST and PATCH paths |
| `packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.handlers.toolkit_persistence import ToolkitConfigService  # TASK-3661
from parrot.tools.spec import hydrate_params  # TASK-3645
from parrot.tools.manager import ToolManager, get_toolkit_owner  # verified: tools/manager.py:53; ToolManager already imported in agent.py
from parrot.security.vault_utils import retrieve_vault_credential  # vault_utils.py:135
from parrot.tools.discovery import discover_from_registry, resolve_class  # tools/discovery.py:31/:139
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py  (AgentTalk)
    async def _filter_tools_for_user(self, tool_manager: "ToolManager") -> None:  # :219
    async def _setup_agent_tools(self, agent, data, request_session):  # :975 (PATCH)
        # `        if getattr(agent, "enable_mcp_restore", False):` (:1007) → await self._restore_user_mcp_servers(...) (:1008-1012)
    async def _restore_user_mcp_servers(self, tool_manager, request_session, agent_name) -> None:  # :1076
        # user_id extraction loop over ("user_id", "id", "username") on request_session (:1107-1112)
    # POST path (:1538-1560):
    #   agent_or_response, is_user_bot = await self._resolve_bot(data)       # :1538
    #   if request_session and not is_user_bot:
    #       session_key = f"{agent.name}_tool_manager"                        # :1552
    #       user_tool_manager = request_session.get(session_key)             # :1553
    #   if user_tool_manager is not None and isinstance(user_tool_manager, ToolManager):
    #       await self._filter_tools_for_user(user_tool_manager)             # :1558 ← anchor
    #   ... swap agent.tool_manager = user_tool_manager (:1683-1686), restore at :1936-1937
# packages/ai-parrot/src/parrot/tools/manager.py
def get_toolkit_owner(tool) -> Optional[AbstractToolkit]  # :53
class ToolManager:
    def get_tool(self, tool_name) -> Optional[Any]  # :1287
    def list_tools(self) -> List[str]  # :1307
    def remove_tool(self, tool_name: str) -> None  # :1342
    def clone(self, *, include_search_tool=False) -> "ToolManager"  # :2632 — shares tool instances by reference
    def register_toolkit(self, toolkit, **kwargs) -> List[AbstractTool]  # :1104
```

### Does NOT Exist
- ~~`ToolManager.replace_toolkit` / `remove_toolkit`~~ — use get_toolkit_owner + remove_tool.
- ~~`enable_toolkit_overrides` flag~~ — overrides are always on (user decision, AC11).
- ~~`agent.toolkit_specs` public attribute~~ — the recorded list is `_pending_toolkit_specs` (TASK-3654).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._setup_agent_tools",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._restore_user_mcp_servers",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.clone",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#get_toolkit_owner",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.remove_tool"
  ]
}
```

---

## Implementation Notes

- Never mutate a shared toolkit instance (clone shares references) — always build a new instance.
- Class resolution: reuse the same TOOL_REGISTRY + resolve_class approach as TASK-3654
  (`ToolInterface._resolve_spec_class` is a staticmethod on the bot — you may call `agent._resolve_spec_class(slug)`).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the method near `_restore_user_mcp_servers` — *why*: sibling restore logic.
2. Wire the POST call before the PBAC filter — *why*: PBAC must filter the final view.
3. Wire the PATCH call after MCP restore.
4. Tests: replace-not-duplicate, stale key ignored, marker short-circuit, rebuild on revision change, no overrides → unchanged.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — method)
```python
# FILL IN: insert right before `    async def _restore_user_mcp_servers(` (verified: agent.py:1076; occurrences: 1)
    async def _apply_user_toolkit_overrides(
        self, agent: AbstractBot, request_session: Any, tool_manager: Optional[ToolManager],
    ) -> Optional[ToolManager]:
        """Build the effective session ToolManager with the user's toolkit overrides (FEAT-593).

        Always on (no opt-in flag). Returns ``tool_manager`` unchanged when the user has no
        overrides or the stored revision marker is current. Never raises.
        """
        user_id = None
        for attr in ("user_id", "id", "username"):
            if hasattr(request_session, attr):
                user_id = getattr(request_session, attr)
                break
        if not user_id or request_session is None:
            return tool_manager
        svc = ToolkitConfigService()
        try:
            overrides = await svc.load(str(user_id), agent.name)
            if not overrides:
                return tool_manager
            marker_key = f"{agent.name}_toolkit_overrides_rev"
            marker = f"{getattr(agent, '_tooling_revision', '')}:{await svc.revision(str(user_id), agent.name)}"
            if tool_manager is not None and request_session.get(marker_key) == marker:
                return tool_manager
            base = tool_manager if tool_manager is not None else agent.tool_manager.clone()
            defaults = {s.slug: s for s in (getattr(agent, "_pending_toolkit_specs", None) or [])}
            for ov in overrides:
                # FILL IN: skip slugs not in defaults; allowed = set(defaults[slug].user_overridable);
                #   params = await hydrate_params(defaults[slug]); params |= {k: v for k, v in ov.params.items() if k in allowed};
                #   user secrets: for key, ref in ov.secret_refs.items() if key in allowed → retrieve_vault_credential(user_id, ref)[key];
                #   cls = agent._resolve_spec_class(slug); drop base tools owned by an instance of cls;
                #   base.register_toolkit(cls(**<ctor-filtered params>))
                pass
            request_session[f"{agent.name}_tool_manager"] = base
            request_session[marker_key] = marker
            return base
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Toolkit override application failed for '%s': %s", agent.name, type(exc).__name__)
            return tool_manager
```

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — POST call)
```python
# occurrences: 1 (verified: grep -c '            await self._filter_tools_for_user(user_tool_manager)' agent.py)
# FILL IN: insert immediately BEFORE the `if user_tool_manager is not None and isinstance(user_tool_manager, ToolManager):`
#   line that guards that call (verified: agent.py:1557-1558), inside the same scope:
        if request_session and not is_user_bot:
            user_tool_manager = await self._apply_user_toolkit_overrides(agent, request_session, user_tool_manager)
```

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — PATCH call)
```python
# occurrences: 1 (verified: grep -c '        if getattr(agent, "enable_mcp_restore", False):' agent.py)
# AFTER the whole `if getattr(agent, "enable_mcp_restore", False):` block (verified: agent.py:1007-1012) insert:
        # FEAT-593: per-user toolkit overrides (always on)
        tool_manager = await self._apply_user_toolkit_overrides(agent, request_session, tool_manager)
```

### FILL IN checklist
- [ ] Override merge loop; bounded by AC9/AC10 (only currently overridable keys)
- [ ] Owner-matched tool removal + fresh instance; bounded by S2 (replace, never duplicate)
- [ ] Verify `Optional`, `AbstractBot`, `Any` are imported in agent.py

---

## Acceptance Criteria

- [ ] With an override, the session TM holds exactly one instance of the toolkit's tools, built from defaults ⊕ override; `agent.tool_manager` is untouched (AC9).
- [ ] A stored key no longer in `user_overridable` is ignored (AC10).
- [ ] Runs for every non-user-bot session with overrides; no flag (AC11).
- [ ] Unchanged marker → no rebuild; changed `_tooling_revision` → rebuild.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.handlers import agent as agent_module
from parrot.handlers.agent import AgentTalk
from parrot.handlers.toolkit_persistence import UserToolkitOverride
from parrot.tools.manager import ToolManager
from parrot.tools.spec import ToolkitSpec
from parrot.tools.toolkit import AbstractToolkit


class _Kit(AbstractToolkit):
    def __init__(self, prefix: str = "", **kwargs):
        super().__init__(**kwargs)
        self.prefix = prefix

    async def echo(self, text: str) -> str:
        """Echo."""
        return self.prefix + text


class _Session(dict):
    user_id = "7"


@pytest.fixture
def agent():
    tm = ToolManager()
    tm.register_toolkit(_Kit(prefix="agent"))
    return SimpleNamespace(name="a1", tool_manager=tm, _tooling_revision="r1",
                           _pending_toolkit_specs=[ToolkitSpec(slug="kit", params={"prefix": "agent"}, user_overridable=["prefix"])],
                           _resolve_spec_class=lambda slug: _Kit)


@pytest.mark.asyncio
async def test_replace_not_duplicate(agent, monkeypatch):
    svc = SimpleNamespace(load=AsyncMock(return_value=[UserToolkitOverride(user_id="7", agent_id="a1", slug="kit",
                                                                            params={"prefix": "user"})]),
                          revision=AsyncMock(return_value="t1"))
    monkeypatch.setattr(agent_module, "ToolkitConfigService", lambda: svc)
    talk = AgentTalk.__new__(AgentTalk)
    talk.logger = logging.getLogger("t")
    tm = await talk._apply_user_toolkit_overrides(agent, _Session(), None)
    assert tm is not agent.tool_manager
    # FILL IN: assert exactly one echo tool in tm and its owner.prefix == "user"; agent TM owner prefix still "agent"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
