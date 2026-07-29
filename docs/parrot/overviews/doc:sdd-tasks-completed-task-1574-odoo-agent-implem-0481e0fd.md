---
type: Wiki Overview
title: 'TASK-1574: OdooAgent implementation + backstory (`agents/oddie.py`)'
id: doc:sdd-tasks-completed-task-1574-odoo-agent-implementation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Modules 4 & 5** of the spec — the registered `OdooAgent` ("Oddie")
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.confirmation
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.stores.kb.user
  rel: mentions
- concept: mod:parrot.tools.working_memory
  rel: mentions
- concept: mod:parrot.utils
  rel: mentions
- concept: mod:parrot.utils.parsers
  rel: mentions
- concept: mod:parrot_tools.odoo
  rel: mentions
---

# TASK-1574: OdooAgent implementation + backstory (`agents/oddie.py`)

**Feature**: FEAT-240 — Odoo PageIndex Documentation Agent
**Spec**: `sdd/specs/odoo-pageindex-documentation-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1571, TASK-1573
**Assigned-to**: unassigned

---

## Context

Implements **Modules 4 & 5** of the spec — the registered `OdooAgent` ("Oddie")
and its backstory contract. Wires every capability surface: OdooToolkit (RPC +
new shell tools from TASK-1571), PageIndexToolkit (over the store built by
TASK-1573), WorkingMemoryToolkit, ConfirmationGuard (HITL), UserInfo KB, and the
file/DB Skill Registry. Resolves G1, G3–G8 and most acceptance criteria.

---

## Scope

- Create `agents/oddie.py` defining
  `@register_agent(name="odoo_agent", at_startup=True) class OdooAgent(SkillRegistryMixin, Agent)`,
  `agent_id="odoo_agent"`, `model = GoogleModel.GEMINI_3_5_FLASH`.
- Class flags: `enable_skill_registry=True`, `skill_registry_expose_tools=True`,
  `skill_registry_inject_context=True`.
- `agent_tools()` returns `OdooToolkit.get_tools()` (built from `ODOO_TEST_*`,
  `verify_ssl=False`) **+** `PageIndexToolkit.get_tools()` (adapter + persisted
  `storage_dir = agents/odoo_agent/documentation/`, the per-version trees `odoo_16`/
  `odoo_18`/`odoo_19` built by TASK-1573).
- `configure()`:
  - register `WorkingMemoryToolkit()` via `self.tool_manager.register_toolkit(...)`.
  - **construct the HITL human channel + `ConfirmationGuard` here (OQ2 resolved)**:
    build the store + `ConfirmationConfig` + `HumanInteractionManager`, then attach via
    `self.tool_manager.set_confirmation_guard(guard)` so write/delete RPC tools and
    all shell tools (already flagged `requires_confirmation` by TASK-1571) are gated.
  - `self.register_kb(UserInfo())` (always-active → auto-injected into system prompt).
  - `await super().configure(...)` then `await self._configure_skill_registry()`
    (loads `agents/odoo_agent/skills/`).
- Author `BACKSTORY` constant: how/when to use OdooToolkit; write out-of-doc
  learnings into the documentation PageIndex (`pageindex_insert_content`/
  `insert_markdown`); document new operations as skills; use WorkingMemory for
  intermediate/presentable data; ground answers in the docs PageIndex and call out
  16 (XML-RPC) vs 18/19 (JSON-RPC/REST) differences; writes are HITL-confirmed.
- `cleanup()` releases the OdooToolkit transport (and any PageIndex resources).
- Tests under `packages/ai-parrot/tests/` (registry resolves, model value, env
  usage, tools include odoo_+pageindex_, UserInfo active, guard attached, skills
  discovered).

**NOT in scope**: the shell tools themselves (TASK-1571); PageIndex build
(TASK-1573); skill content (TASK-1575/1576) — but the agent must *load* them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/oddie.py` | CREATE | `OdooAgent` + `BACKSTORY` + all wiring |
| `packages/ai-parrot/tests/test_odoo_agent.py` | CREATE | Unit tests for the agent |

> Note: `/agents/` was un-ignored for FEAT-240 — `git add` works normally now.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import os
from parrot.bots import Agent                          # verified: agents/backup/odoo.py:3
from parrot.registry import register_agent             # verified: agents/porygon.py:6
from parrot.models.google import GoogleModel           # verified: models/google.py:9
from parrot.skills import SkillRegistryMixin           # verified: agents/porygon.py:5
from parrot_tools.odoo import OdooToolkit              # verified: agents/backup/odoo.py:5
from parrot.knowledge.pageindex import (               # verified: pageindex/__init__.py:1-43
    PageIndexToolkit, PageIndexLLMAdapter,
)
from parrot.tools.working_memory import WorkingMemoryToolkit  # verified: agents/porygon.py:9
from parrot.auth.confirmation import (                 # verified: examples/workday_checkin.py:107
    ConfirmationGuard, ConfirmationConfig, InMemoryConfirmationWindowStore,
)
from parrot.stores.kb.user import UserInfo             # verified: stores/kb/user.py:11
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/google.py
class GoogleModel(str, Enum):
    GEMINI_3_5_FLASH = "gemini-3.5-flash"               # line 16 (value, NOT member name, is "gemini-3.5-flash")

# packages/ai-parrot/src/parrot/bots/agent.py
class Agent(BasicAgent): ...                            # line 1256
class BasicAgent(Chatbot, NotificationMixin):           # line 37
    def __init__(self, name='Agent', agent_id='agent', use_llm='google', llm=None,
                 tools=None, system_prompt=None, ..., **kwargs): ...   # lines 80-109
    # `backstory` accepted via kwargs (abstract.py:386-388), rendered into system prompt.

# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:                               # line 27
    enable_skill_registry: bool = True                  # line 57
    skill_registry_expose_tools: bool = True            # line 58
    skill_registry_inject_context: bool = True          # line 59
    async def _configure_skill_registry(self) -> None   # loads agents/<agent_id>/skills/

# packages/ai-parrot/src/parrot/tools/manager.py
def set_confirmation_guard(self, guard) -> None         # line 338
@property
def confirmation_guard(self) -> Optional[ConfirmationGuard]  # line 356
def register_toolkit(self, toolkit)                     # used: agents/porygon.py:437

# packages/ai-parrot/src/parrot/auth/confirmation.py
class ConfirmationConfig(BaseModel):                    # line 66 (approval_timeout=120.0, default_channel="telegram")
class ConfirmationGuard:                                # line 378
    def __init__(self, store, human_manager=None, config=None)

# packages/ai-parrot/src/parrot/stores/kb/user.py
class UserInfo(AbstractKnowledgeBase):                  # line 11 (always_active=True, priority=10)

# packages/ai-parrot/src/parrot/bots/abstract.py
def register_kb(self, kb): ...                          # line 962 (always_active KBs auto-injected, 2807-2810)

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:
    def __init__(self, client, model="gemini-3.1-flash-lite-preview",
                 max_retries=3, retry_delay=1.0)        # lines 49-59
```

### Reference Implementation (verified, copy this structure)
```python
# agents/backup/odoo.py — minimal existing pattern
@register_agent(name="odoo_agent", at_startup=True)
class OdooAgent(Agent):
    agent_id: str = "odoo_agent"; model = GoogleModel.GEMINI_FLASH_LATEST
    def __init__(self, *args, **kwargs):
        super().__init__(*args, backstory=BACKSTORY, **kwargs)
        self._odoo_toolkit = None
    def agent_tools(self):
        self._odoo_toolkit = OdooToolkit(url=ODOO_TEST_URL, database=ODOO_TEST_DATABASE,
            username=ODOO_TEST_USERNAME, password=ODOO_TEST_PASSWORD, verify_ssl=False)
        return self._odoo_toolkit.get_tools()
    async def cleanup(self):
        if self._odoo_toolkit: await self._odoo_toolkit.cleanup()
        await super().cleanup()

# agents/porygon.py — verified mixin + WorkingMemory + skills wiring
class Porygon(SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent):   # line 253
    enable_skill_registry: bool = True
    async def configure(self, app=None, queries=None):
        wm = WorkingMemoryToolkit(); self.tool_manager.register_toolkit(wm)  # 436-437
        await super().configure(app=app, queries=queries)
        await self._configure_skill_registry()                              # 442
```

### Does NOT Exist
- ~~`enable_user_info` / `enable_userinfo` flag~~ — enablement is `register_kb(UserInfo())`.
- ~~`SkillRegistryMixin` already mixed into `Agent`~~ — must be added explicitly to bases.
- ~~`agent.register_pageindex()` / built-in PageIndex mixin~~ — attach via `agent_tools()`.
- ~~`GoogleModel.GEMINI_3_5_FLASH` being a raw string~~ — it's a str-enum member; `.value == "gemini-3.5-flash"`.
- ~~`OdooToolkit` shell tools pre-existing~~ — they come from TASK-1571 (verify merged before relying on them).

---

## Implementation Notes

### Key Constraints
- Mixin ordering: `class OdooAgent(SkillRegistryMixin, Agent)` (mixin first), per porygon.
- `OdooToolkit` from `os.getenv("ODOO_TEST_URL"/...)`, `verify_ssl=False` — NOT staging `ODOO_*`.
- The ConfirmationGuard needs a `store` (use `InMemoryConfirmationWindowStore`) and a
  `human_manager`. **OQ2 resolved**: construct the store + `ConfirmationConfig` +
  `HumanInteractionManager` + guard **inside `configure()`** and attach via
  `set_confirmation_guard`. Verify the exact `HumanInteractionManager` import path at
  implementation time (grep `parrot.auth`/`parrot.*human*`).
- async throughout; `self.logger`; Pydantic where structured.
- PageIndex `storage_dir` is `agents/odoo_agent/documentation/` (must match TASK-1573).

### References in Codebase
- `agents/backup/odoo.py`, `agents/porygon.py` — the two reference patterns above.
- `packages/ai-parrot/examples/workday_checkin.py:107-112` — ConfirmationGuard wiring.

---

## Acceptance Criteria

- [ ] `OdooAgent(SkillRegistryMixin, Agent)` registered as `odoo_agent`, `at_startup=True`.
- [ ] `OdooAgent.model` resolves to `"gemini-3.5-flash"` via `GoogleModel` enum.
- [ ] `OdooToolkit` constructed from `ODOO_TEST_*` (not `ODOO_*`), `verify_ssl=False`.
- [ ] `agent_tools()` returns both `odoo_*` and `pageindex_*` tools.
- [ ] `WorkingMemoryToolkit` registered in `configure()`.
- [ ] `tool_manager.confirmation_guard` is not None after `configure()`.
- [ ] `UserInfo` registered and `always_active is True`.
- [ ] Skills loaded from `agents/odoo_agent/skills/` (`_configure_skill_registry`).
- [ ] `BACKSTORY` covers: PageIndex grounding + write-back, skill documentation,
      WorkingMemory usage, version differences, HITL on writes.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/test_odoo_agent.py -v`
- [ ] No lint errors: `ruff check agents/oddie.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_odoo_agent.py
import pytest
from parrot.models.google import GoogleModel


@pytest.fixture(autouse=True)
def odoo_test_env(monkeypatch):
    monkeypatch.setenv("ODOO_TEST_URL", "http://prozac:8069")
    monkeypatch.setenv("ODOO_TEST_DATABASE", "odoo")
    monkeypatch.setenv("ODOO_TEST_USERNAME", "admin")
    monkeypatch.setenv("ODOO_TEST_PASSWORD", "admin")


def test_model_is_gemini_3_5_flash():
    from agents.oddie import OdooAgent
    assert str(OdooAgent.model) == GoogleModel.GEMINI_3_5_FLASH or \
        getattr(OdooAgent.model, "value", OdooAgent.model) == "gemini-3.5-flash"


def test_agent_registered():
    # registry lookup for "odoo_agent" resolves to OdooAgent
    ...


@pytest.mark.asyncio
async def test_userinfo_kb_active_after_configure():
    # after configure(), an always_active UserInfo KB is registered
    ...


@pytest.mark.asyncio
async def test_confirmation_guard_attached():
    # tool_manager.confirmation_guard is not None
    ...
```

---

## Agent Instructions

1. Read the spec (§2, §3 Modules 4/5, §6, §7, §8 OQ2).
2. Confirm TASK-1571 (shell tools) and TASK-1573 (PageIndex store) are completed.
3. Verify the Codebase Contract; adjust if signatures shifted.
4. Update index status → `in-progress`.
5. Implement per scope.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update index → `done`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Created `agents/oddie.py` with OdooAgent class (SkillRegistryMixin, Agent), model=GoogleModel.GEMINI_3_5_FLASH, registered as "odoo_agent" at_startup=True. Implements agent_tools() returning OdooToolkit + PageIndexToolkit tools. configure() wires WorkingMemoryToolkit, ConfirmationGuard (InMemoryConfirmationWindowStore), UserInfo KB, and _configure_skill_registry(). BACKSTORY covers PageIndex grounding, write-back learnings, skill documentation, WorkingMemory, HITL gate, version differences. Created test file `packages/ai-parrot/tests/test_odoo_agent.py` with 12 tests (all pass). Lint clean.

**Key implementation detail**: Tests use a `_load_oddie_module()` helper that (1) stubs `parrot.utils.types` / `parrot.utils.parsers` (Cython modules not compiled in worktree), (2) clears conftest's incomplete `_ToolManager` stub by removing `parrot.bots.*` entries from sys.modules before loading, (3) adds `agents/` to sys.path and imports `oddie` as a top-level module so `patch.object(module, "X")` targets the correct namespace.

**Deviations from spec**: none
