# TASK-2855: Migration verification: import paths, factory create-all, editable install, convention conformance

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2854
**Assigned-to**: unassigned
**Parallel**: false — Sequential: final gate over all satellites.

---

## Context

Spec §3 Module 6, §4 Integration Tests, AC-1..AC-12. End-to-end proof that the extracted layout behaves: every documented import path resolves, every key creates, editable installs merge, no provider enum leaks back into core, and MetaClient moved by pure `git mv` (AC-11).

---

## Scope

- `tests/integration/clients/test_import_all_client_paths.py` — for each of the 15 providers import the package and every class in `__all__`.
- `test_factory_create_all_keys.py` — `LLMFactory._discover()`; for every key in `SUPPORTED_CLIENTS` assert the resolved class is an `AbstractClient` subclass and `key in cls.provider_keys`.
- `test_extend_path_merges_satellite.py` — build a temp dir `tmp/parrot/clients/fakeprov/{__init__,client,models}.py`, put `tmp` on `sys.path`, `importlib.invalidate_caches()`, reload `parrot.clients`, import `parrot.clients.fakeprov`.
- `test_editable_install.sh` (or a `subprocess` test marked `slow`): fresh `uv venv`, `uv pip install -e packages/ai-parrot -e packages/ai-parrot-client-groq`, `python -c "from parrot.clients.factory import LLMFactory; assert 'groq' in LLMFactory.list_providers()"`.
- Extend `test_folder_convention.py` to discover providers from `LLMFactory.list_providers()` instead of the hard-coded `CONVERTED` list.
- AC-11 check: `git log --follow --diff-filter=M --oneline -- packages/ai-parrot-client-meta/src/parrot/clients/meta/` shows no modification commits after FEAT-526's merge (only the rename).
- Update `docs/clients/openai-compatible.md` recipe step for 'add a new provider' to the folder + entry-point convention; append the enum move to `docs/migration/feat-523-llm-client-satellites.md`.

**NOT in scope**: New features. Fixing bugs found in a provider's own logic (open a separate task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/clients/test_import_all_client_paths.py` | CREATE |  |
| `packages/ai-parrot/tests/integration/clients/test_factory_create_all_keys.py` | CREATE |  |
| `packages/ai-parrot/tests/unit/clients/test_extend_path_merges_satellite.py` | CREATE |  |
| `scripts/tests/test_editable_install.sh` | CREATE | slow, opt-in |
| `packages/ai-parrot/tests/unit/clients/test_folder_convention.py` | MODIFY | discover via list_providers |
| `docs/clients/openai-compatible.md` | MODIFY | recipe step 7 → folder convention |
| `docs/migration/feat-523-llm-client-satellites.md` | MODIFY | enum move + renamed paths |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS   # discovery API from TASK-2847
from parrot.clients.base import AbstractClient
import importlib, pkgutil, sys
# docs/clients/openai-compatible.md — 7-step recipe (FEAT-438) referenced by FEAT-526 spec
```

### Existing Signatures to Use
```python
PROVIDERS = ["openai","anthropic","google","amazon","groq","grok","zai","nvidia","moonshot","openrouter","local","vllm","gemma4","hf","meta"]
# Renamed paths to document (old → new): parrot.clients.gpt → .openai ; .claude → .anthropic ; .localllm → .local ;
#   .bedrock/.nova → .amazon ; .live → .google.live ; parrot.models.<provider> → parrot.clients.<provider>.models
```

### Does NOT Exist
- ~~`parrot.clients.claude`, `.gpt`, `.localllm`, `.bedrock`, `.nova`, `.live`~~ — renamed; tests must assert they are GONE, not present.
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
Mark the editable-install test `@pytest.mark.slow` and skip unless `RUN_SLOW=1`. Follow the repo gotcha: wrap `pytest tests/unit` in `timeout -s KILL` (it can hang after the summary).

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] All 15 providers import and every key creates (AC-1, AC-4, AC-5)
- [ ] `test_extend_path_merges_satellite` and the editable-install script pass (AC-4)
- [ ] `git log --follow` shows `meta/` untouched since FEAT-526 (AC-11)
- [ ] Docs updated; `pytest packages/ai-parrot/tests -q` + all satellite test dirs green (AC-12)

---

## Test Specification

```python
# tests/integration/clients/test_factory_create_all_keys.py
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.base import AbstractClient
def test_every_key_resolves_to_declared_client():
    LLMFactory._discover()
    for key, entry in SUPPORTED_CLIENTS.items():
        cls = entry() if callable(entry) and not isinstance(entry, type) else entry
        assert issubclass(cls, AbstractClient) and key in cls.provider_keys, key
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
7. **Move this file** to `sdd/tasks/completed/TASK-2855-tests-migration-verification.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
