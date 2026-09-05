# TASK-2842: Convert gpt.py + Codex to parrot/clients/openai/ with OpenAIModel and DEPRECATIONS

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2841
**Assigned-to**: unassigned
**Parallel**: false — Sequential: edits parrot/models/__init__.py, factory.py import lines and the shared conformance test.

---

## Context

Spec §2 map row `ai-parrot-client-openai`. `OpenAIClient` (`gpt.py`), `OpenAICodexClient` (`codex_agent.py`) and `codex_tool_bridge.py` become the `openai/` folder; `OpenAIModel` and the `DEPRECATIONS` table leave `parrot/models/openai.py`. This is a **renamed** module path (`gpt` → `openai`): callers are hard-cut in this task.

---

## Scope

- `git mv gpt.py openai/client.py`, `codex_agent.py openai/codex_agent.py`, `codex_tool_bridge.py openai/codex_tool_bridge.py`; `git mv parrot/models/openai.py parrot/clients/openai/models.py` (content byte-identical, only imports adjusted).
- `openai/__init__.py` exports `OpenAIClient`, `OpenAICodexClient`, `OpenAIModel`, `DEPRECATIONS`.
- `OpenAIClient`: `provider_keys = ("openai",)`, `models = OpenAIModel`, `deprecated_models = DEPRECATIONS`. `OpenAICodexClient`: `provider_keys = ("codex-agent", "openai-codex", "codex-code")`, `models = OpenAIModel`.
- `factory.py:5` `from .gpt import OpenAIClient` → `from .openai import OpenAIClient`; `_lazy_openai_codex` path → `.openai.codex_agent`.
- Update every importer of `parrot.clients.gpt`, `parrot.clients.codex_agent`, `parrot.clients.codex_tool_bridge`, `parrot.models.openai` across `packages/*/src`, `packages/*/tests`, `examples/` (grep first, list them in the completion note). `tests/unit/models/test_openai_deprecations.py` moves to `tests/unit/clients/openai/test_deprecations.py`.
- Append `"openai"` to `CONVERTED` in `test_folder_convention.py`.

**NOT in scope**: Server handler changes (TASK-2848). Other providers. Satellite packaging.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai/{__init__,client,codex_agent,codex_tool_bridge,models}.py` | CREATE/MOVE | folder |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | import paths only |
| `packages/ai-parrot/src/parrot/models/openai.py` | DELETE | moved |
| `packages/ai-parrot/tests/unit/clients/openai/test_deprecations.py` | MOVE | from tests/unit/models/test_openai_deprecations.py |
| `packages/ai-parrot/tests/unit/clients/test_folder_convention.py` | MODIFY | CONVERTED += openai |
| `callers of parrot.clients.gpt / codex_agent / parrot.models.openai` | MODIFY | hard cut |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from parrot.clients.gpt import OpenAIClient                    # clients/gpt.py:86        → parrot.clients.openai
from parrot.clients.codex_agent import OpenAICodexClient       # clients/codex_agent.py:69 → parrot.clients.openai.codex_agent
from parrot.models.openai import OpenAIModel, DEPRECATIONS     # models/openai.py          → parrot.clients.openai.models
from parrot.clients.openai_base import OpenAIBaseClient        # openai_base.py:65 (STAYS in core)
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS  # factory.py:107
```

### Existing Signatures to Use
```python
# parrot/clients/gpt.py:86
class OpenAIClient(OpenAIBaseClient): ...
# parrot/clients/codex_agent.py
class CodexAgentRunOptions: ...        # :38
class OpenAICodexClient(AbstractClient): ...  # :69
# parrot/clients/codex_tool_bridge.py
class CodexMCPBridgeConfig: ...  # :24
class CodexToolBridge: ...       # :38
# parrot/clients/factory.py
from .gpt import OpenAIClient                       # :5
"openai": OpenAIClient,                             # :128
"codex-agent"/"openai-codex"/"codex-code": _lazy_openai_codex   # :146-148
# packages/ai-parrot-server/src/parrot/handlers/llm.py:21  from parrot.models.openai import OpenAIModel, DEPRECATIONS
#   (inside try/except → keep it importing the NEW path so the server does not silently lose the list; TASK-2848 removes it)
```

### Does NOT Exist
- ~~`parrot/clients/openai/`~~ — does not exist yet.
- ~~`OpenAIClient.deprecated_models`~~ — introduced here.
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
**Name-shadowing gotcha**: inside `parrot/clients/openai/*.py`, `import openai` / `from openai import AsyncOpenAI` are absolute imports and resolve to the SDK, not to this folder (Python 3 has no implicit relative imports). Do NOT rename the SDK import; do add a one-line comment above it. Keep `gpt.py`'s Responses-API helpers untouched (FEAT-526 MetaClient re-implements them locally by design, D1).

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [x] `from parrot.clients.openai import OpenAIClient, OpenAICodexClient, OpenAIModel, DEPRECATIONS` works; `parrot/models/openai.py` is gone
- [x] `OpenAIClient.provider_keys == ("openai",)`, `OpenAIClient.deprecated_models is DEPRECATIONS`
- [x] `grep -rn "parrot.clients.gpt\|parrot.models.openai\|clients.codex_agent" packages/*/src packages/*/tests examples` → no hits
- [x] `pytest packages/ai-parrot/tests/unit/clients -q` green (incl. moved deprecations test); `ruff` clean

---

## Test Specification

```python
# tests/unit/clients/openai/test_layout.py
def test_exports():
    from parrot.clients.openai import OpenAIClient, OpenAICodexClient, OpenAIModel, DEPRECATIONS
    assert OpenAIClient.models is OpenAIModel and OpenAIClient.deprecated_models is DEPRECATIONS
    assert OpenAICodexClient.provider_keys == ("codex-agent", "openai-codex", "codex-code")
def test_old_paths_gone():
    import importlib, pytest
    for mod in ("parrot.clients.gpt", "parrot.models.openai"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod)
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
7. **Move this file** to `sdd/tasks/completed/TASK-2842-openai-folder.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-04
**Notes**:

Implemented per scope. Commit `6845bb8cb` on
`feat-FEAT-523-pep-420-llm-clients`.

- `git mv` for all four files; `models.py` (formerly `models/openai.py`)
  needed zero import edits (pure stdlib + pydantic, no parrot-internal
  imports). `client.py` and `codex_agent.py` had their relative-import
  depth adjusted for the extra folder level, plus the internal
  `codex_tool_bridge` cross-import fixed.
- `OpenAIClient` / `OpenAICodexClient` gained the folder-convention class
  attributes exactly as specified.
- `factory.py`'s single active import line + the `_lazy_openai_codex`
  closure both updated; `SUPPORTED_CLIENTS["openai"]` verified resolving
  to `parrot.clients.openai.client.OpenAIClient`.
- Moved `tests/unit/models/test_openai_deprecations.py` →
  `tests/unit/clients/openai/test_deprecations.py` per the task's Files
  table, **and its conftest.py** (not listed in the table, but the moved
  test's `upstream_current_models` fixture lives there and is used by no
  other test in the old directory — leaving it behind would have broken
  the moved test at collection).
- Blast radius: ~35 files across `ai-parrot`, `ai-parrot-server`, `tests/`,
  `examples/` — real imports, `mock.patch()` target strings,
  `importlib.import_module()` path tuples/lists, one file-grep exclusion
  path in `test_openai_deprecation_warning.py` (its "allow deprecated
  literals only in <path>" check had to move from `models/openai.py` to
  `clients/openai/models.py`), and docstring `:mod:`/`:class:` references.
  Full list in the commit diff.

**Deviations from spec**: none. The `handlers/llm.py` try/except import
was pointed at the new module path per the contract's explicit note
(TASK-2848 replaces it with `LLMFactory.list_models()`).

**Verification evidence**:
- `pytest packages/ai-parrot/tests/unit/clients -q` → 397 passed, 8
  pre-existing failures (same as TASK-2841, confirmed identical on `dev`).
- `pytest packages/ai-parrot/tests/unit/clients/openai/ -q` → 40/40 passed
  (deprecations test + its restored fixture).
- AC grep (`parrot.clients.gpt|parrot.models.openai|clients.codex_agent`
  over `packages/*/src packages/*/tests examples`) → zero hits.
- `ruff check` clean on every substantially-modified/new file; the one
  pre-existing `F401` (`InvokeResult` unused in `client.py`, inherited
  verbatim from `gpt.py`) confirmed identical on `dev`.
- `packages/ai-parrot/tests/{agents/test_obsidian.py,
  unit/clients/test_codex_agent.py,
  integration/test_openai_deprecation_warning.py}` → 84 passed.
- `packages/ai-parrot-server/tests/studio/test_catalogs.py` → 7 passed
  (run separately — cross-package conftest collisions are a pre-existing
  pytest limitation of invoking `ai-parrot` and `ai-parrot-server` tests
  in one process, unrelated to this change).
- Top-level `tests/clients` + `tests/integration` + `tests/unit`
  openai-touching files → 425 passed, 10 pre-existing failures (confirmed
  identical on `dev`: 3 unrelated `test_client_fallback.py` cases + 7
  google/anthropic/groq/grok `test_invoke.py` cases, none OpenAI-specific).
