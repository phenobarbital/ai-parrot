# TASK-5142: Agent HTTP handler: AGENT_LLM, AGENT_<P>_API_KEY, AGENT usage tag

**Feature**: FEAT-796 — Per-Component LLM Defaults
**Spec**: `sdd/specs/per-component-llm-defaults.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5138, TASK-5139
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (+M7). The agent handler hardcodes `_use_llm='google'` / `_use_model='gemini-2.5-pro'`. Default them to `None`, resolve `AGENT_LLM` when a subclass set nothing, pass `AGENT_<P>_API_KEY`, and tag requests `AGENT`.

---

## Scope

- Class attrs `_use_llm: Optional[str] = None`, `_use_model: Optional[str] = None`.
- In `_create_agent`, resolve `resolve_component_llm('AGENT', builtin='google:gemini-2.5-pro')` for any attr left None; add `api_key` when `resolve_component_api_key(('AGENT',), provider)` is set.
- Wrap `await agent.ask(` in `ask_agent` (line 885) with `usage_component('AGENT')`.
- Tests.

**NOT in scope**: Other handlers under `handlers/`. UI model selector.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` | MODIFY | env-driven model/key + tagging |
| `packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Verify anything not listed
> before using it. Anchors verified at dev `e179aba02f`.

### Verified Imports
```python
from ...llm_defaults import resolve_component_llm, resolve_component_api_key  # TASK-5138 (relative, like `from ...conf import AGENTS_DIR` at line 42)
from ...observability.context import usage_component  # TASK-5139
```

### Existing Signatures to Use
```python
# handlers/agents/abstract.py
    _use_llm: str = 'google'  # 179
    _use_model: str = 'gemini-2.5-pro'  # 180
    async def _create_agent(self, app: web.Application) -> BasicAgent:  # 789
            agent = self._agent_class(name=self.agent_name, tools=self._tools, llm=self._use_llm, model=self._use_model)  # 795-800
    async def ask_agent(...)  # 832
            response = await agent.ask(  # 885
```

### Does NOT Exist
- ~~`AbstractAgentHandler.resolve_llm`~~ — no such method; inline
- ~~a BOT_LLM variable~~ — out of scope (spec Non-Goals)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py#AbstractAgentHandler"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Verify the class name at line ~169 before using it in tests/symbols (the docstring says 'Abstract class for chatbot/agent handlers').
- Subclasses setting `_use_llm`/`_use_model` must keep winning (AC).
- Server tests need `PYTHONPATH` with both ai-parrot and ai-parrot-server `src` (absolute).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path the blueprint fixes.

### Steps (in order)
1. Change the two class attrs — *why*: None means 'use env'.
2. Resolve in `_create_agent` — *why*: lazy, per instance.
3. Tag `agent.ask` — *why*: AC10.
4. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` (MODIFY)
```python
# occurrences: 1 each — lines 179-180 become:
    _use_llm: Optional[str] = None
    _use_model: Optional[str] = None  # None -> AGENT_LLM / DEFAULT_LLM / google:gemini-2.5-pro (FEAT-796)

# in _create_agent, before `agent = self._agent_class(` (line ~795):
            resolved = resolve_component_llm("AGENT", builtin="google:gemini-2.5-pro")
            llm = self._use_llm or resolved.provider
            model = self._use_model or resolved.model
            extra: dict[str, Any] = {}
            api_key = resolve_component_api_key(("AGENT",), llm)
            if api_key:
                extra["api_key"] = api_key
# and the call becomes llm=llm, model=model, **extra
# FILL IN: if a subclass sets _use_model but not _use_llm, the env provider is used —
#          acceptable? keep: provider from env only when _use_llm is None — bounded by spec §3 M5

# line 885:
            with usage_component("AGENT"):
                response = await agent.ask(
                    ...  # unchanged args
                )
```

### FILL IN checklist
- [ ] mixed subclass override case; bounded by spec §3 M5
- [ ] confirm BasicAgent accepts api_key kwarg

---

## Acceptance Criteria

- [ ] No env + no subclass override → google / gemini-2.5-pro as today
- [ ] `AGENT_LLM` honoured when subclass sets nothing
- [ ] Subclass `_use_model` beats env
- [ ] `AGENT_GOOGLE_API_KEY` passed as api_key
- [ ] `ask_agent` calls tagged `AGENT`

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py -q`

---

## Test Specification

```python
async def test_handler_agent_llm_env(monkeypatch): ...  # fake _agent_class capturing kwargs
async def test_handler_subclass_override_wins(monkeypatch): ...
async def test_handler_api_key_passed(monkeypatch): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-component-llm-defaults --feature-id FEAT-796`), never on `dev`.
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/per-component-llm-defaults.json`.
3. Verify the Codebase Contract (re-run the `grep -c` of every anchor) before writing code.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH` set to the changed packages' absolute `src` dirs; `ruff check` the touched files.
7. Commit only the listed files; close with `parrot sdd task close TASK-5142 per-component-llm-defaults verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
