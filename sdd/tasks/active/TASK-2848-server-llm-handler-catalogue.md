# TASK-2848: Server LLM handler lists models via LLMFactory.list_models (no enum imports)

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-2847
**Assigned-to**: unassigned
**Parallel**: false — Sequential after the factory API exists; disjoint files from the satellite tasks, but keep it before them so the server never imports a moved module.

---

## Context

Spec §2 Integration Points row `parrot/handlers/llm.py` and AC-6. The server (ai-parrot-server) try/except-imports four provider enums and hand-dispatches per provider; it must use the catalogue so it stops depending on any client package being importable.

---

## Scope

- Delete the four try/except enum imports (`handlers/llm.py:19-39`) and the per-provider `if` chain (`:72-83`); implement the models lookup as `LLMFactory.list_models(provider)`, returning `{"active", "deprecated"}` for every provider (was: dict only for openai/azure, list otherwise — keep the public JSON shape backwards compatible if a test pins it; otherwise return the dict uniformly and note it).
- Handle `ImportError` from a missing satellite as an empty list plus a `logger.warning`.
- Add a unit test in `packages/ai-parrot-server/tests/` asserting the module has no `parrot.clients.<provider>` / `parrot.models.<provider>` import and that the lookup delegates to `LLMFactory.list_models`.

**NOT in scope**: Any other handler. Studio catalog/byok (they use `SUPPORTED_CLIENTS`, unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/llm.py` | MODIFY | use LLMFactory.list_models |
| `packages/ai-parrot-server/tests/unit/handlers/test_llm_models_catalogue.py` | CREATE | test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS   # handlers/llm.py:14 (keep)
# handlers/llm.py:19-39 — try/except imports of OpenAIModel+DEPRECATIONS, GroqModel, ClaudeModel (from parrot.clients.claude), GoogleModel → DELETE
LLMFactory.list_models(provider: str) -> dict[str, list[str]]   # introduced by TASK-2847
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/llm.py:59-83
def <models method>(self, provider: str) -> Union[List[str], Dict[str, List[str]]]:
    provider = provider.lower()
    if provider in ['openai', 'azure'] and OpenAIModel: return {"active": [...], "deprecated": [...]}
    elif provider == 'groq' and GroqModel: return [...]
    elif provider in ['anthropic', 'claude'] and ClaudeModel: return [...]
    elif provider == 'google' and GoogleModel: return [...]
    return []
# :86 async def get(self): ... if 'models' in self.request.path: ...
```

### Does NOT Exist
- ~~`parrot.clients.claude`~~ — renamed to `parrot.clients.anthropic` by TASK-2844; do not re-import it here.
- ~~`_ParrotClientsRedirector`~~ — never existed (v0.2 idea, dropped in v0.3). Do NOT add a MetaPathFinder.
- ~~`AbstractClient.conversation_memory`, `create_conversation_memory()`~~ — removed by FEAT-524; clients are memory-less.
- ~~`parrot/clients/openai.py`~~ — the OpenAI client file is `gpt.py` today.
- ~~`parrot.clients.registry`~~ — no registry module; `SUPPORTED_CLIENTS` in `factory.py` is the only registry.

---

## Implementation Notes

### Folder convention (normative, spec §2)
```
parrot/clients/<provider>/
├── __init__.py   # re-exports client class(es) + model enum, __all__
├── client.py     # AbstractClient / OpenAIBaseClient subclass(es)
└── models.py     # <Provider>Model(str, Enum) + capability sets + DEPRECATIONS; pure data
```
Every client class gets: `provider_keys: tuple[str, ...]` (primary key first, every factory alias),
`models: type[Enum]`, optional `deprecated_models: Mapping[str, str] | None = None`.
`models.py` must not import `client.py`. Use `git mv` so history follows the file.
Enum members/values are moved **byte-identical**. Any caller of a renamed module path
(inside `packages/*/src`, `tests/`, `examples/`) is updated in THIS task — the tree must be
green (import-clean, `pytest packages/ai-parrot/tests/unit/clients -q`) when the task ends.

### Key Constraints
`azure` is an alias the handler accepts for `openai`; map it before calling `list_models`. Check whether any e2e/UI test pins the flat-list shape for non-OpenAI providers (`grep -rn "models" packages/ai-parrot-server/tests`) before changing the response shape.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] `grep -n "Model\b" handlers/llm.py` shows no provider enum names
- [ ] Models endpoint returns the catalogue for `openai`, `google`, `anthropic`, `groq` via `list_models`
- [ ] Server unit tests green; `ruff` clean

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/handlers/test_llm_models_catalogue.py
import inspect, parrot.handlers.llm as h
def test_no_enum_imports():
    src = inspect.getsource(h); assert "parrot.models.openai" not in src and "parrot.clients.claude" not in src
def test_delegates(monkeypatch):
    called = {}
    monkeypatch.setattr(h.LLMFactory, "list_models", staticmethod(lambda p: called.setdefault(p, {"active": ["m"], "deprecated": []})))
    assert h.<HandlerClass>.<models method>(object.__new__(h.<HandlerClass>), "openai")["active"] == ["m"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import/signature still exists; if a prior task moved it, update the contract FIRST
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, contract and notes above — hard cuts, no shims
6. **Verify** all acceptance criteria are met (run the commands, paste evidence in the note)
7. **Move this file** to `sdd/tasks/completed/TASK-2848-server-llm-handler-catalogue.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
