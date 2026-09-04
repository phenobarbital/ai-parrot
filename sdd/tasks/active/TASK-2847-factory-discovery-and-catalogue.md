# TASK-2847: LLMFactory: extend_path, entry-point discovery, list_providers/list_models, transitional registry

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2846
**Assigned-to**: unassigned
**Parallel**: false — Sequential: rewrites factory.py and clients/__init__.py which every satellite task then relies on.

---

## Context

Spec §2 'Discovery', 'New Public Interfaces' and §3 Module 3. Core must resolve clients without importing them: `extend_path` merges satellite folders into `parrot.clients`; entry points (`parrot.clients` group) feed `SUPPORTED_CLIENTS`; `list_models()` replaces enum imports for UIs/servers. Until TASK-2849..2853 ship entry points, a transitional in-core registry keeps `create()` working for the folders still inside core.

---

## Scope

- `parrot/clients/__init__.py`: prepend `from pkgutil import extend_path; __path__ = extend_path(__path__, __name__)`; delete `from .zai import ZaiClient` (`:17`) and its `__all__` entry (hard cut).
- `factory.py`: remove every concrete import (`:2-13`) and `_lazy_*` closure; make `SUPPORTED_CLIENTS` a lazily-populated dict. `_discover()`: (a) `importlib.metadata.entry_points(group="parrot.clients")` → `{ep.name: lazy(ep.load)}`; (b) transitional `_IN_CORE_PROVIDERS = (...)` tuple — for each, `importlib.import_module(f"parrot.clients.{p}")`, iterate `__all__` classes with `provider_keys`, register each key. Entry-point keys win over in-core keys? No: **first registration wins, duplicates log a warning** (spec §4 `test_duplicate_entry_point_warning`). Idempotent; guarded by a module flag.
- `create()`: unchanged signature; on unknown key raise `ImportError(f"No LLM client for provider '{p}'. Install ai-parrot-client-{p} …")` listing `list_providers()`; keep `PROVIDER_BACKEND` injection (`:155`).
- Add `LLMFactory.list_providers() -> dict[str, str]` (key → distribution name from `ep.dist.name`, or `"ai-parrot"` for in-core) and `LLMFactory.list_models(provider) -> dict[str, list[str]]` (`{"active": [m.value for m in cls.models], "deprecated": list(cls.deprecated_models or {})}`).
- Tests from spec §4 M3 rows (mock entry points fixture in spec §4).

**NOT in scope**: Editing the server handler (TASK-2848). Creating satellites. Removing the transitional registry (TASK-2854).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/__init__.py` | MODIFY | extend_path; drop ZaiClient |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | discovery + catalogue |
| `packages/ai-parrot/tests/unit/clients/test_factory_discovery.py` | CREATE | M3 tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from pkgutil import extend_path                       # parrot/embeddings/__init__.py:1-2 — copy verbatim
from importlib.metadata import entry_points, EntryPoint  # stdlib 3.11+
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS, PROVIDER_BACKEND  # factory.py:107, :155, class :161
from parrot.clients import AbstractClient, OpenAIBaseClient, LLM_PRESETS, StreamingRetryConfig  # clients/__init__.py:6-7 (keep)
```

### Existing Signatures to Use
```python
# parrot/clients/factory.py (today)
SUPPORTED_CLIENTS = {...}            # :107-149 static dict, mixes classes and _lazy_* closures
PROVIDER_BACKEND = {"bedrock": "bedrock", "anthropic-aws": "aws"}   # :155
class LLMFactory:                    # :161
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...   # ~:171
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None, **kwargs) -> AbstractClient: ...  # ~:193
        # :234-241  if provider not in SUPPORTED_CLIENTS: raise ...; client_class = SUPPORTED_CLIENTS[provider]
# Consumers of SUPPORTED_CLIENTS that must keep working (spec §2 Integration Points): bots/abstract.py, bots/voice.py,
#   bots/flows/crew/crew.py, interfaces/tools.py, tools/execution_plan/planner.py, server/ui/catalog.py,
#   handlers/llm.py, handlers/studio/{catalog,byok}.py, advisors/mixin.py, parrot_pipelines/abstract.py
# Existing lazy pattern to reuse for ep.load(): _lazy_bedrock_converse (:24-35)
```

### Does NOT Exist
- ~~`[project.entry-points."parrot.clients"]`~~ — no distribution declares it yet; discovery must tolerate an empty group.
- ~~`LLMFactory.list_models()` / `list_providers()` / `_discover()`~~ — introduced here.
- ~~`ai-parrot-embeddings` entry points~~ — that satellite uses `extend_path` only; it is the pattern for merging, not for discovery.
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
`SUPPORTED_CLIENTS` is imported by name in ~12 places — keep it a real `dict` object (mutate in place inside `_discover()`, never rebind) so those imports see the discovered keys. Any module that iterates `SUPPORTED_CLIENTS` at import time (check `parrot_pipelines/abstract.py`, `handlers/studio/catalog.py`) needs `LLMFactory._discover()` called first — add a `LLMFactory.supported_clients()` helper that discovers-then-returns and use it there.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] `parrot/clients/__init__.py` starts with `extend_path`; `from parrot.clients import ZaiClient` fails
- [ ] `factory.py` has no `from .<provider>` import at module scope (`grep -n "^from \." factory.py` shows only `.base`)
- [ ] `LLMFactory.create()` works for every key in every in-core `provider_keys` (transitional registry); unknown key → ImportError naming `ai-parrot-client-<p>`
- [ ] `list_models("openai")` returns `{"active": [...], "deprecated": [...]}`; `list_providers()` lists all in-core keys
- [ ] `pytest packages/ai-parrot/tests/unit/clients -q` green; `ruff` clean

---

## Test Specification

```python
# tests/unit/clients/test_factory_discovery.py
import importlib.metadata as md, pytest
from parrot.clients import factory
def _reset(monkeypatch):
    monkeypatch.setattr(factory, "_DISCOVERED", False, raising=False); factory.SUPPORTED_CLIENTS.clear()
def test_discover_entry_points(monkeypatch):
    _reset(monkeypatch)
    ep = md.EntryPoint(name="test-provider", value="tests.unit.clients.fakes:FakeClient", group="parrot.clients")
    monkeypatch.setattr(md, "entry_points", lambda group=None: [ep])
    factory.LLMFactory._discover(); assert "test-provider" in factory.SUPPORTED_CLIENTS
def test_duplicate_entry_point_warning(monkeypatch, caplog): ...
def test_create_missing_satellite(monkeypatch):
    _reset(monkeypatch); monkeypatch.setattr(md, "entry_points", lambda group=None: [])
    monkeypatch.setattr(factory, "_IN_CORE_PROVIDERS", ())
    with pytest.raises(ImportError, match="ai-parrot-client-claude"): factory.LLMFactory.create("claude:x")
def test_list_models_active_deprecated():
    out = factory.LLMFactory.list_models("openai"); assert set(out) == {"active", "deprecated"} and out["active"]
def test_provider_backend_discovered():
    from parrot.clients.factory import PROVIDER_BACKEND; assert PROVIDER_BACKEND["bedrock"] == "bedrock"  # + create() injection test with a stub
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
7. **Move this file** to `sdd/tasks/completed/TASK-2847-factory-discovery-and-catalogue.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
