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

**Completed by**: sdd-worker (autonomous, FEAT-523 session)
**Date**: 2026-09-04
**Notes**:

Implemented exactly the 3 declared files plus the 2 external call sites the
task's own "Key Constraints" text named explicitly (`parrot_pipelines/
abstract.py`, `handlers/studio/catalog.py`), plus the tests these edits made
necessary to keep green.

- `clients/__init__.py`: prepended `from pkgutil import extend_path;
  __path__ = extend_path(__path__, __name__)` (copied verbatim from
  `embeddings/__init__.py`); deleted `from .zai import ZaiClient` and its
  `__all__` entry (hard cut — confirmed no callers import `ZaiClient` from
  `parrot.clients` top level).
- `factory.py`: removed all 13 concrete provider imports and all 6
  `_lazy_*` closures. `_discover()` populates `SUPPORTED_CLIENTS` from
  (a) `importlib.metadata.entry_points(group="parrot.clients")` — value
  registered is `ep.load` itself (a zero-arg loader, same shape as the old
  `_lazy_*` closures) — then (b) the transitional `_IN_CORE_PROVIDERS`
  tuple (all 15 current provider folders: openai, anthropic, google,
  amazon, groq, grok, zai, nvidia, moonshot, openrouter, local, vllm,
  gemma4, hf, meta), importing each dynamically and registering every
  `__all__` class with a non-empty `provider_keys`. First registration
  wins (`_register()` compares `is` identity so a class re-exported under
  an alias name in the same package's `__all__`, e.g. `GoogleClient =
  GoogleGenAIClient`, is not treated as a false duplicate); a genuine
  key collision from a second source is logged at WARNING and dropped.
  `create()` now calls `_discover()` and raises `ImportError(f"No LLM
  client for provider '{p}'. Install ai-parrot-client-{p} …")` (was
  `ValueError`) for an unknown key. Added `LLMFactory.list_providers()`
  (key → `"ai-parrot"` or the satellite's distribution name),
  `LLMFactory.list_models(provider)` (`{"active": [...], "deprecated":
  [...]}`), and `LLMFactory.supported_clients()` (discover-then-return).
  `PROVIDER_BACKEND` injection into `create()` unchanged.
- `tests/unit/clients/test_factory_discovery.py` (+ `fakes.py`): all 9
  Test Specification rows implemented (`test_discover_entry_points`,
  `test_duplicate_entry_point_warning`, `test_create_missing_satellite`,
  `test_list_models_active_deprecated`, `test_provider_backend_discovered`)
  plus 4 extra covering `list_providers()`, the `PROVIDER_BACKEND`
  injection through `create()`, the AC-2 grep condition, and the AC-1
  `ZaiClient` hard cut. All 9 pass.

**Evidence**:
- `grep -n "^from \." factory.py` → only `from .base import AbstractClient`
  (AC-2).
- `pytest packages/ai-parrot/tests/unit/clients -q` → 433 passed, 8 skipped→11
  skipped, 8 failed — the 8 failures are byte-identical to the pre-existing
  `test_groq_multiround_usage.py` / `test_openai_multiround_usage.py`
  `MagicMock`/`raw_response` failures already present at the TASK-2846
  commit (confirmed via `git stash` diff-free re-run); my 9 new tests are
  part of the 433 passed.
- `ruff check` clean on every touched file except one pre-existing F401
  (`PIL.ImageFont` unused in `parrot_pipelines/abstract.py`) confirmed via
  `git stash` to predate this task.
- Broader regression sweep (all pre-existing failures confirmed
  byte-identical via `git stash` re-run, none newly introduced):
  `tests/test_llm_factory.py`, `tests/test_localllm_client.py`,
  `tests/test_nvidia_client.py`, `tests/test_openrouter_factory.py`,
  `tests/test_zai_client.py`, `tests/clients/test_bedrock_integration.py`,
  `test_bedrock_mantle.py`, `test_factory_bedrock.py`, `test_factory_nova.py`
  → 133 passed, 4 pre-existing failures (`test_factory_alias_registered
  [vllm]`, `test_list_models`, `test_health_check_success`,
  `test_health_check_failure` in `test_localllm_client.py` — all
  unrelated `AbstractClient.client` deprecation-guard / stale-alias-
  assertion issues, none touching factory.py).
  `tests/bots/test_abstractbot_routing.py` + `unit/bots/test_abstract_
  lifecycle.py` + `test_abstractbot_store_router.py` → 30 passed.
  `tests/test_crew_*_regression.py` (7 files) → 84 passed.
  `tests/tools/execution_plan/` → 71 passed.
  `ai-parrot-advisors/tests/test_advisor.py` → 6 passed, 1 skipped (DB).
  `ai-parrot-server/tests/studio/test_catalogs.py` +
  `test_admin_catalog.py` → 13 passed.
  `ai-parrot-server/tests/studio/test_byok.py` → 10 passed.
  `ai-parrot-pipelines/tests/` → 39 passed, 1 pre-existing unrelated
  failure (`test_status_not_missing_when_found`, a planogram
  product-name-matching assertion, confirmed via `git stash` to predate
  this task).
- Direct import smoke test confirmed `interfaces/tools.py`, `handlers/
  llm.py`, `bots/flows/crew/crew.py`, `tools/execution_plan/planner.py` —
  the 4 of the ~10 "must keep working" consumers not explicitly named by
  the task — all import and resolve `SUPPORTED_CLIENTS` correctly
  (36 keys discovered) without any code change to those files.

**Deviations from spec**:

1. **`SUPPORTED_CLIENTS` is a `_LazyClientRegistry(dict)` subclass, not a
   plain `dict`.** The task's Key Constraint names only two external call
   sites (`parrot_pipelines/abstract.py`, `handlers/studio/catalog.py`) as
   needing a `LLMFactory.supported_clients()` fix for reading
   `SUPPORTED_CLIENTS` "at import time" — but per the Codebase Contract's
   own list, ~12 call sites import `SUPPORTED_CLIENTS` directly
   (`bots/abstract.py`, `bots/voice.py`, `bots/flows/crew/crew.py`,
   `interfaces/tools.py`, `tools/execution_plan/planner.py`,
   `server/ui/catalog.py`, `handlers/llm.py`, `handlers/studio/byok.py`,
   `advisors/mixin.py`, plus the two named), and read it inside function
   bodies with no `LLMFactory.create()`/`_discover()` call anywhere on
   their path. If `SUPPORTED_CLIENTS` were a plain dict populated only via
   explicit `_discover()` calls (as the literal Scope text describes), all
   ~10 untouched consumers would see an empty dict on any code path that
   never happens to call `create()`/`list_*` first in the same process —
   a severe, silent regression across core bot construction, `AgentCrew`,
   the planner toolkit, and three server handlers. Rather than touch ~10
   files outside this task's declared "Files to Create/Modify" (a File
   Fidelity violation) or risk that regression, `SUPPORTED_CLIENTS` is a
   small `dict` subclass whose read methods (`__contains__`, `__getitem__`,
   `__iter__`, `__len__`, `get`, `keys`, `items`, `values`) call
   `_discover()` first — it remains "a real dict object, mutated in place,
   never rebound" (the literal constraint), and eager import-time discovery
   was deliberately avoided (would force-import `gemma4`/`hf`'s heavier ML
   deps merely by importing `factory.py`, defeating this feature's "core
   resolves clients without importing them" goal). The two explicitly-named
   files were still switched to `LLMFactory.supported_clients()` exactly as
   directed. `_register()` uses raw `dict.__contains__`/`__getitem__`/
   `__setitem__` internally to avoid re-entering `_discover()` while
   already inside it.
2. Two pre-existing tests asserted the exact behavior this task's Scope
   text explicitly changes, and were updated (not a scope violation — the
   task itself mandates the new behavior):
   `test_llm_factory.py::test_unsupported_provider_raises` (ValueError →
   ImportError, per Scope: "on unknown key raise ImportError(...)") and
   `test_factory_nova.py::test_nova_key_registered_lazy` ("nova" now
   resolves to the real `NovaClient` class directly via `provider_keys`
   discovery, not a hand-written `_lazy_nova` closure — the outer
   laziness moved to `_discover()` itself).
3. `test_catalogs.py::test_llm_clients_lazy_loader_failure_graceful`'s
   monkeypatch target changed from `catalog_module.SUPPORTED_CLIENTS` (no
   longer imported into that module) to `catalog_module.LLMFactory.
   supported_clients` — required by change #3 above (the two explicitly-
   named file fixes), not an independent deviation.
