# TASK-2843: Convert moonshot, openrouter, nvidia, local, vllm to folders with their enums

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2841
**Assigned-to**: unassigned
**Parallel**: false — Sequential: shares factory.py import block, parrot/models/__init__.py and the conformance test with siblings.

---

## Context

Spec §2 map rows nvidia/moonshot/openrouter/local/vllm — the five `OpenAIBaseClient` wrappers without their own SDK. Enums come from `parrot/models/{moonshot,openrouter,nvidia,localllm,vllm}.py`. `localllm` → `local/` is a **renamed** path (hard cut on callers). `parrot/models/vllm.py` is consumed only by `clients/vllm.py` and `models/__init__.py` (verified 2026-09-04), so the whole file becomes `vllm/models.py` and its `parrot.models` re-exports are dropped.

---

## Scope

- For each of moonshot, openrouter, nvidia: `git mv <x>.py <x>/client.py`, `git mv parrot/models/<x>.py parrot/clients/<x>/models.py`, add `__init__.py` re-exports, class attrs: Moonshot `("moonshot", "kimi")`, OpenRouter `("openrouter",)`, Nvidia `("nvidia",)`.
- `git mv localllm.py local/client.py`, `git mv parrot/models/localllm.py parrot/clients/local/models.py`; `LocalLLMClient.provider_keys = ("local", "localllm", "ollama", "llamacpp")`.
- `git mv vllm.py vllm/client.py`, `git mv parrot/models/vllm.py parrot/clients/vllm/models.py`; `vLLMClient` imports `LocalLLMClient` from `..local`; `provider_keys = ("vllm",)`; `models` = the vLLM model enum if one exists in `models/vllm.py`, otherwise `LocalLLMModel` (document the choice).
- Remove the vLLM block (`VLLMConfig … pydantic_to_guided_json`) and `NvidiaModel` from `parrot/models/__init__.py:97-107`.
- Update `factory.py:8-13` import paths; update all callers of the old module paths (`parrot.clients.localllm`, `parrot.models.{moonshot,openrouter,nvidia,localllm,vllm}`) in `packages/*/src`, tests, `examples/`.
- Append the five providers to `CONVERTED`.

**NOT in scope**: Zai, groq, grok, anthropic (TASK-2844). Meta (`meta/` already lands in the convention via FEAT-526 — do not touch).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/{moonshot,openrouter,nvidia,local,vllm}/{__init__,client,models}.py` | CREATE/MOVE | five folders |
| `packages/ai-parrot/src/parrot/models/{moonshot,openrouter,nvidia,localllm,vllm}.py` | DELETE | moved |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | drop NvidiaModel + vLLM re-exports |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | import paths |
| `packages/ai-parrot/tests/unit/clients/test_folder_convention.py` | MODIFY | CONVERTED += 5 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from parrot.clients.moonshot import MoonshotClient      # moonshot.py:74
from parrot.clients.openrouter import OpenRouterClient  # openrouter.py:26
from parrot.clients.nvidia import NvidiaClient          # nvidia.py:222
from parrot.clients.localllm import LocalLLMClient      # localllm.py:26   → parrot.clients.local
from parrot.clients.vllm import vLLMClient              # vllm.py:52 (subclasses LocalLLMClient)
from parrot.models.nvidia import NvidiaModel            # models/__init__.py:107 re-exports it
from parrot.models.vllm import (VLLMConfig, VLLMSamplingParams, VLLMLoRARequest, VLLMGuidedParams,
    VLLMBatchRequest, VLLMBatchResponse, VLLMServerInfo, pydantic_to_guided_json)  # models/__init__.py:97-106
```

### Existing Signatures to Use
```python
# parrot/clients/factory.py imports
from .openrouter import OpenRouterClient   # :8
from .localllm import LocalLLMClient       # :9
from .vllm import vLLMClient               # :10
from .nvidia import NvidiaClient           # :11
from .moonshot import MoonshotClient       # :13
# SUPPORTED_CLIENTS keys :134-142 — "openrouter","nvidia","moonshot","kimi","local","localllm","ollama","vllm","llamacpp"
# parrot/models/ sizes: localllm.py 1.1K, moonshot.py 2.2K, nvidia.py 7.3K, openrouter.py 3.3K, vllm.py 11.2K
```

### Does NOT Exist
- ~~`parrot/clients/ollama.py`~~ — Ollama is served by `LocalLLMClient`.
- ~~`parrot.models.vllm` consumers outside clients~~ — none (verified); dropping the re-exports is safe.
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
`vLLMClient(LocalLLMClient)` — do the `local/` move before `vllm/` so the relative import target exists. `NvidiaClient` sits at `nvidia.py:222` after ~200 lines of helpers: move the whole file, do not split.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [x] Five folders exist with the three canonical files; enums importable from `parrot.clients.<x>`
- [x] `parrot/models/{moonshot,openrouter,nvidia,localllm,vllm}.py` deleted; `parrot.models` no longer exports `NvidiaModel` or `VLLM*`
- [x] `LocalLLMClient.provider_keys == ("local", "localllm", "ollama", "llamacpp")`; `MoonshotClient.provider_keys == ("moonshot", "kimi")`
- [x] `pytest packages/ai-parrot/tests/unit/clients -q` green; `ruff` clean

---

## Test Specification

```python
# tests/unit/clients/test_wire_wrapper_layout.py
import importlib, pytest
@pytest.mark.parametrize("provider,cls,keys", [
    ("moonshot","MoonshotClient",("moonshot","kimi")), ("openrouter","OpenRouterClient",("openrouter",)),
    ("nvidia","NvidiaClient",("nvidia",)), ("local","LocalLLMClient",("local","localllm","ollama","llamacpp")),
    ("vllm","vLLMClient",("vllm",))])
def test_keys(provider, cls, keys):
    assert getattr(importlib.import_module(f"parrot.clients.{provider}"), cls).provider_keys == keys
def test_parrot_models_dropped_vllm():
    import parrot.models as m
    assert not hasattr(m, "VLLMConfig") and not hasattr(m, "NvidiaModel")
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
7. **Move this file** to `sdd/tasks/completed/TASK-2843-openai-wire-wrapper-folders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-04
**Notes**:

Implemented per scope. Commit `e31792176` on
`feat-FEAT-523-pep-420-llm-clients`.

- All five providers converted; `local/` did land before `vllm/` per the
  task's ordering constraint, and `vLLMClient` imports `LocalLLMClient`
  from `..local` cleanly.
- `vLLMClient.models = LocalLLMModel` — verified `models/vllm.py` has no
  dedicated model enum (only Pydantic config/request/response classes),
  documented the choice inline in the class attribute comment.
- `factory.py` needed only one rename (`.localllm` → `.local`); the
  other four keep their module name since the folder replaces the file
  under the same name.
- **Important lesson from this task**: grep-based sweeps for stale
  import paths miss `from parrot.clients import <provider> as
  <alias>_mod` module-alias patterns that then read/patch
  module-*level* globals (`_thinking_ctx`, `config`) via
  `<alias>_mod.<global>`. These only surface by *running* the affected
  test suites, not by grepping for the string `parrot.clients.<provider>`
  (the alias import itself greps clean; it's the downstream attribute
  access that breaks, with an `AttributeError` far from the import
  line). Found and fixed three: `dev_loop/dispatchers/moonshot.py`'s own
  test, and `test_nvidia_client.py` (×2, one is a fixture named
  `env_key` used across the init tests). Recommend later tasks in this
  feature (TASK-2844/2845/2854) explicitly re-run affected test suites,
  not just grep, before declaring green.
- `test_nvidia_client.py::test_nvidia_model_importable_from_parrot_models`
  encoded the pre-FEAT-523 contract directly and had to be inverted —
  not a deviation, a necessary correction: this feature's AC-2 requires
  `parrot.models` to stop exporting provider enums, and this test
  literally asserted the opposite.

**Deviations from spec**: none.

**Verification evidence**:
- `pytest packages/ai-parrot/tests/unit/clients -q` → 407 passed, 8
  pre-existing failures (identical to TASK-2841/2842).
- `pytest packages/ai-parrot/tests/unit/clients/test_folder_convention.py`
  → 19/19 passed (7 providers × conformance checks + relocation tests).
- Explicit AC assertions (`LocalLLMClient.provider_keys`,
  `MoonshotClient.provider_keys`, `parrot.models` no longer has
  `NvidiaModel`/`VLLMConfig`) → all pass.
- `ruff check` clean on every new/modified file under
  `clients/{moonshot,openrouter,nvidia,local,vllm}/`, `factory.py`,
  `models/__init__.py`, `test_folder_convention.py`.
- External provider-specific suites (`test_openrouter_{factory,client,
  models}.py`, `test_nvidia_client.py`, `test_localllm_client.py`,
  `test_vllm_{client,models}.py`, `test_moonshot_code_dispatcher.py`) →
  206 passed, 7 pre-existing failures confirmed byte-identical on `dev`
  (4 in `test_localllm_client.py`, 3 in `test_vllm_client.py`, all the
  same `AbstractClient.client` loop-local-property assignment issue,
  unconnected to this move).
