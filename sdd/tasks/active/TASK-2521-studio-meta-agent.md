# TASK-2521: AgentStudio meta-agent — assistant, skills, factory absorption

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2512, TASK-2513, TASK-2514, TASK-2515, TASK-2516
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13. The AgentStudio meta-agent lets users build agents,
skills, and KB files with natural language. Resolved decisions: default
`AnthropicClient` with `claude-opus-5`, overridable via NEW config setting
`STUDIO_AGENT_MODEL`; it **absorbs** `AgentFactoryHandler` — reusing the
`parrot/bots/factory/` builders and the HITL-gated
`finalize_agent_registration` — and `/api/v1/agents/factory` stays
routable as a thin alias; BYOK keys honored; its file-writing tools are
constrained to the draft store and asset directories (never live code).

---

## Scope

- Add `STUDIO_AGENT_MODEL` to `parrot/conf.py`
  (`config.get('STUDIO_AGENT_MODEL', fallback='claude-opus-5')`).
- Create `packages/ai-parrot/src/parrot/bots/studio/` — the
  `AgentStudioAgent(Agent)`:
  - LLM: `AnthropicClient` + `STUDIO_AGENT_MODEL` (per-user BYOK override
    when available).
  - Authored composite skills shipped with the agent (skills dir inside
    the package): `agent-builder` (how to scaffold a Python agent from
    the base-class catalog), `skill-writer` (frontmatter contract),
    `kb-writer`.
  - Tools (HITL/confirmation-gated like `finalize_agent_registration`):
    `save_agent_draft` (→ TASK-2513 draft save path),
    `create_yaml_agent` (→ registry + lossless persist),
    `write_identity_file` / `write_kb_file` / `write_skill_file`
    (→ TASK-2514 validated file paths),
    `publish_skill_to_catalog` (→ TASK-2515),
    plus read-only introspection (base classes, tools, existing agents).
  - Reuse `parrot/bots/factory/builders/` (rag/tool_agent/clone) and
    `finalize_agent_registration` for the YAML-agent flow.
- Implement `StudioAssistantHandler(StudioBaseView)` in
  `handlers/studio/meta_agent.py`: `POST /api/v1/astudio/assistant` —
  session-scoped conversation with the meta-agent (session instance
  pattern from TASK-2517).
- Re-point `/api/v1/agents/factory` (manager.py:1835) to delegate into the
  same orchestration path (alias — request/response contract of
  `AgentFactoryHandler.post` preserved).
- Tests: model/config resolution, write-boundary enforcement, alias
  contract, tool gating (LLM calls mocked).

**NOT in scope**: UI; autonomous multi-turn plans; removing
`AgentFactoryHandler` (alias only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `STUDIO_AGENT_MODEL` |
| `packages/ai-parrot/src/parrot/bots/studio/__init__.py` + `agent.py` + `skills/` | CREATE | meta-agent + authored skills |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | CREATE | gated file/agent tools |
| `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` | CREATE | assistant handler |
| `packages/ai-parrot-server/src/parrot/handlers/agents/factory.py` | MODIFY | thin-alias delegation |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add route |
| `packages/ai-parrot-server/tests/studio/test_meta_agent.py` | CREATE | boundary/alias/gating tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.claude import AnthropicClient       # claude.py:67
from parrot.bots.agent import Agent                     # agent.py:1236 (exported bots/__init__.py:9)
from parrot.tools import tool                           # decorators.py:55 (@tool)
from parrot.bots.factory.tools.finalize import finalize_agent_registration  # finalize.py:31
from parrot.conf import AGENTS_DIR                      # conf.py:175
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient):  # :67
    _default_model: str = 'claude-sonnet-4-5'  # :73
    def __init__(self, api_key: str = None, base_url="https://api.anthropic.com",
                 backend: AnthropicBackend = "direct", ..., **kwargs): ...  # :79
    # model flows via **kwargs → AbstractClient (clients/base.py:315
    #   self.model = kwargs.get('model', None))
    # api_key fallback: config.get('ANTHROPIC_API_KEY') (:120)

# Bot LLM declaration — bots/abstract.py
# llm kwarg :283 (instance | class | "provider:model" | provider+model | model_config);
# _resolve_llm_config :826; per-request llm override in ask :3817

# packages/ai-parrot/src/parrot/tools/decorators.py:55
def tool(_func=None, *, name=None, description=None, schema=None,
         auto_register=False, requires_confirmation=False,
         confirm_template=None, confirm_window_seconds=0, allow_edit=False):
# → use requires_confirmation=True for every writing tool (HITL gate)

# packages/ai-parrot/src/parrot/bots/factory/tools/finalize.py
async def write_agent_yaml(definition: AgentDefinition, category="general") -> Path: ...  # :18
async def finalize_agent_registration(definition: AgentDefinition,
                                      category: str = "general") -> Dict[str, Any]: ...  # :31
    # stamps origin="factory" (:41-46); writes YAML; re-scans dir (:51);
    # wrapped as HITL-gated @tool at :64
# Builders: parrot/bots/factory/builders/{rag_builder,tool_agent_builder,
#   clone_builder,base}.py + contracts.py, orchestrator.py

# packages/ai-parrot-server/src/parrot/handlers/agents/factory.py
class AgentFactoryHandler(BaseView):  # :107
    async def post(self) -> web.Response: ...  # :110
# helpers in same file: _AutoApproveChannel(HumanChannel) :48,
#   build_auto_approve_manager() :99
# route: manager/manager.py:1835 — POST /api/v1/agents/factory

# conf.py pattern (parrot/conf.py:175):
# SETTING = config.get('SETTING', fallback=<default>)

# Skills shipped with an agent: SkillRegistryMixin resolves
#   AGENTS_DIR/{agent_id}/skills/ (skills/mixin.py:141) OR class attr
#   skill_paths: List[Path] (mixin.py:57-75) — use skill_paths pointing at
#   the package's bundled skills dir
```

### Does NOT Exist
- ~~`STUDIO_AGENT_MODEL`~~ — THIS task adds it to conf.py.
- ~~`parrot/bots/studio/`~~ — greenfield package.
- ~~`AnthropicClient(model=...)` explicit param / `DEFAULT_MODEL`~~ —
  pass `model` through kwargs or use `llm="anthropic:<model>"` string form.
- ~~A meta-agent write path into live `AGENTS_DIR/*.py`~~ — forbidden by
  design: writing tools target ONLY `_drafts/` + asset dirs + the YAML
  factory flow (assert in tests).
- ~~`claude-opus-5` in the `ClaudeModel` enum~~ — enum has FABLE_5 /
  OPUS_4_5 / etc. (models/claude.py); pass the model id as a plain string,
  do NOT reference a nonexistent enum member.

---

## Implementation Notes

### Pattern to Follow
Agent shape: subclass `Agent`, override `agent_tools()` to return the
gated tools; skills via `skill_paths` class attr. The handler holds a
session-scoped instance (TASK-2517 pattern).

### Key Constraints
- Every mutating tool: `requires_confirmation=True` + docstring stating
  exactly what will be written where.
- Tool implementations call the SAME internal service functions the HTTP
  endpoints use (drafts save/validate, files write, catalog publish) — no
  duplicate logic; import them from the studio handler modules' service
  layer, not by making HTTP calls to self.
- BYOK: resolve the caller's anthropic key (TASK-2516 helper) at instance
  build; fall back to server `ANTHROPIC_API_KEY`.
- Alias: keep `AgentFactoryHandler.post`'s external contract byte-stable;
  internally delegate.

### References in Codebase
- `agents/porygon.py` — bundled identity/skills agent example.
- `parrot/bots/factory/orchestrator.py` — the flow being absorbed.

---

## Acceptance Criteria

- [ ] Meta-agent builds with `STUDIO_AGENT_MODEL` default `claude-opus-5`;
      env override respected; BYOK key used when stored.
- [ ] Writing tools are confirmation-gated and can only write to
      `_drafts/`, asset dirs, or the YAML factory flow (negative test:
      attempt to write `AGENTS_DIR/x.py` directly → refused).
- [ ] Assistant endpoint converses via session instance; scaffold→draft→
      validate flow produces a TASK-2513-valid draft.
- [ ] `/api/v1/agents/factory` request/response contract unchanged.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_meta_agent.py -v` passes.
- [ ] `ruff check` clean on touched paths.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_meta_agent.py
class TestMetaAgent:
    def test_model_resolution_default_and_override(self, monkeypatch): ...
    async def test_write_boundary_enforced(self, studio_app, tmp_agents_dir): ...
    async def test_tools_confirmation_gated(self): ...
    async def test_assistant_session_instance(self, studio_app): ...
    async def test_factory_alias_contract(self, studio_app): ...
    async def test_byok_key_used_when_present(self, studio_app, vault_keys): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2512, TASK-2513, TASK-2514, TASK-2515,
   TASK-2516 completed
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
