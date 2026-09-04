# TASK-2846: Hard-cut every provider-enum import outside parrot/clients/ and delete emptied parrot/models files

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2842, TASK-2843, TASK-2844, TASK-2845
**Assigned-to**: unassigned
**Parallel**: false — Sequential: touches conf.py and bots/agent.py which FEAT-525 may also touch — rebase-check.

---

## Context

Spec §3 Module 2 and §6 'Enum consumers outside parrot/clients/'. After TASK-2841..2845 every enum lives under `parrot/clients/<provider>/models.py`; core and the satellites must stop importing them at module scope so a client can leave core (AC-3).

---

## Scope

- Replace each import in the hard-cut list with a string literal or a `"provider:model"` spec: `conf.py:433,435` (`DEFAULT_LLM_MODEL` fallback → `"gemini-flash-latest"`), `loaders/abstract.py:27,1038,1073,1115,1180`, `bots/agent.py`, `bots/jira_specialist.py`, `bots/github_reviewer.py`, `bots/flows/result_agent.py`, `interfaces/images/plugins/{analisys,classify,classifybase}.py`, `parrot_tools/code_toolkit.py`, `parrot_loaders/{imageunderstanding,videounderstanding}.py`, `parrot_pipelines/abstract.py`, `parrot_pipelines/planogram/{plan,legacy}.py`, `parrot_pipelines/planogram/types/*.py`.
- Re-grep: `grep -rnE "clients\.\w+\.models import|from parrot\.clients\.(openai|anthropic|google|amazon|groq|grok|zai|nvidia|moonshot|openrouter|local|vllm|gemma4|hf|meta)" packages/*/src` outside `parrot/clients/` and `handlers/llm.py` must be empty (the handler is TASK-2848).
- Delete any `parrot/models/<provider>.py` left behind by the move tasks; final `parrot/models/__init__.py` exports no provider enum.
- Add `tests/unit/clients/test_core_independence.py` with a `block_satellites` fixture (spec §4) proving `parrot.conf`, `parrot.loaders.abstract`, `parrot.bots.agent` import with every `parrot.clients.<provider>` blocked.

**NOT in scope**: Factory/discovery (TASK-2847). Server handler (TASK-2848). Media models in `parrot/models/google.py` (stay).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | string default |
| `packages/ai-parrot/src/parrot/loaders/abstract.py` | MODIFY | string specs |
| `packages/ai-parrot/src/parrot/bots/{agent,jira_specialist,github_reviewer}.py, bots/flows/result_agent.py` | MODIFY | hard cut |
| `packages/ai-parrot/src/parrot/interfaces/images/plugins/{analisys,classify,classifybase}.py` | MODIFY | hard cut |
| `packages/ai-parrot-tools/src/parrot_tools/code_toolkit.py` | MODIFY | hard cut |
| `packages/ai-parrot-loaders/src/parrot_loaders/{imageunderstanding,videounderstanding}.py` | MODIFY | hard cut |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/**` | MODIFY | hard cut |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | final cleanup |
| `packages/ai-parrot/tests/unit/clients/test_core_independence.py` | CREATE | block_satellites test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/conf.py
from .models.google import GoogleModel  # noqa: E402                                   # :433  → delete
DEFAULT_LLM_MODEL = config.get("LLM_MODEL", fallback=GoogleModel.GEMINI_FLASH_LATEST.value)  # :435 → fallback="gemini-flash-latest"
# packages/ai-parrot/src/parrot/loaders/abstract.py
from ..models.google import GoogleModel                    # :27
model=GoogleModel.GEMINI_2_5_FLASH_LITE,                   # :1038
llm=f"google:{GoogleModel.GEMINI_2_5_FLASH_LITE.value}",   # :1073
model=GoogleModel.GEMINI_2_5_FLASH_LITE_PREVIEW,           # :1115
model=GoogleModel.GEMINI_2_5_FLASH_LITE_PREVIEW.value      # :1180
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS   # unchanged, used for validation in parrot_pipelines/abstract.py
```

### Existing Signatures to Use
```python
# The enum VALUES you will inline — read them from the new models.py files, do not guess:
#   parrot/clients/google/models.py  GoogleModel.GEMINI_FLASH_LATEST / GEMINI_2_5_FLASH_LITE / GEMINI_2_5_FLASH_LITE_PREVIEW
# Where a call already flows through LLMFactory, prefer llm="google:<id>" over a bare model literal.
```

### Does NOT Exist
- ~~`parrot.models.GoogleModel` / `parrot.models.google.GoogleModel`~~ — gone since TASK-2841.
- ~~`parrot.models.{openai,claude,groq,localllm,moonshot,nvidia,openrouter,zai,bedrock_models,vllm}`~~ — deleted by TASK-2842..2845.
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
Hard cuts are policy (no shims, no deprecation warnings). Where a bot hard-codes a Google model, keep the same model id as a string so behaviour does not change. FEAT-525 (per-turn compaction) is active in `bots/` — check `git log origin/dev -- packages/ai-parrot/src/parrot/bots/agent.py` before editing and rebase-check before merge.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] Grep from Scope step 2 returns nothing outside `parrot/clients/` and `handlers/llm.py`
- [ ] `test_core_independence.py` passes with all 15 providers blocked in `sys.modules`
- [ ] `DEFAULT_LLM_MODEL` unchanged in value for an unset `LLM_MODEL`
- [ ] `pytest packages/ai-parrot/tests/unit -q` (wrap in `timeout -s KILL 600`) green; `ruff` clean

---

## Test Specification

```python
# tests/unit/clients/test_core_independence.py
import importlib, sys, pytest
PROVIDERS = ["openai","anthropic","google","amazon","groq","grok","zai","nvidia","moonshot","openrouter","local","vllm","gemma4","hf","meta"]
@pytest.fixture
def block_satellites(monkeypatch):
    for name in PROVIDERS:
        monkeypatch.setitem(sys.modules, f"parrot.clients.{name}", None)
        for m in list(sys.modules):
            if m.startswith(f"parrot.clients.{name}."): monkeypatch.delitem(sys.modules, m)
@pytest.mark.parametrize("mod", ["parrot.conf", "parrot.loaders.abstract", "parrot.bots.agent"])
def test_core_imports_without_providers(block_satellites, mod, monkeypatch):
    monkeypatch.delitem(sys.modules, mod, raising=False)
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
7. **Move this file** to `sdd/tasks/completed/TASK-2846-core-callsite-hard-cut.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
