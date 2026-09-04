# TASK-2845: Convert bedrock+nova→amazon/, gemma4/, hf/ folders with their enums

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2841
**Assigned-to**: unassigned
**Parallel**: false — Sequential: shares factory.py lazy closures and the conformance test with siblings.

---

## Context

Spec §2 map rows amazon/gemma4/hf. `amazon/` is the one multi-client folder (Bedrock Converse, Nova, Mantle share `parrot/models/bedrock_models.py`). `bedrock.py` and `nova/` are **renamed** paths (hard cut). `Gemma4Model` (`gemma4.py:38`) and `TransformersModel` (`hf.py:27`) leave their client files.

---

## Scope

- `amazon/`: `git mv bedrock.py amazon/bedrock.py`, `git mv nova amazon/nova`, `git mv parrot/models/bedrock_models.py amazon/models.py`; create `amazon/client.py` that re-exports `BedrockConverseClient`, `NovaClient`, `BedrockMantleClient` (the convention needs a `client.py`; keep the real code in `bedrock.py`/`nova/`). Keys: `BedrockConverseClient ("bedrock-converse",)`, `NovaClient ("nova",)`, `BedrockMantleClient ("bedrock-mantle", "mantle")`. `models` = the primary Bedrock catalogue enum from `bedrock_models.py` (inspect the file — it may expose constants rather than a single Enum; if so, add a thin `AmazonModel(str, Enum)` in `amazon/models.py` built from those constants and document it).
- `gemma4/`: `git mv gemma4.py gemma4/client.py`; cut `Gemma4Model` into `gemma4/models.py`; keys `("gemma4",)`.
- `hf/`: `git mv hf.py hf/client.py`; cut `TransformersModel` into `hf/models.py`; keys `("hf", "transformers")` — **new keys** (`TransformersClient` is not in `SUPPORTED_CLIENTS` today); do NOT add them to the factory here, TASK-2847's discovery picks them up.
- Update `_lazy_bedrock_converse`, `_lazy_nova`, `_lazy_bedrock_mantle`, `_lazy_gemma4` in `factory.py:17-60`; update callers of `parrot.clients.bedrock`, `parrot.clients.nova`, `parrot.models.bedrock_models`, `parrot.clients.gemma4`, `parrot.clients.hf` (tests `test_bedrock_*`, examples).
- Append amazon, gemma4, hf to `CONVERTED`.

**NOT in scope**: Anthropic's Bedrock *backend* (`anthropic/backends.py`, TASK-2844). Satellite packaging.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/amazon/{__init__,client,bedrock,models}.py + amazon/nova/` | CREATE/MOVE | folder |
| `packages/ai-parrot/src/parrot/clients/{gemma4,hf}/{__init__,client,models}.py` | CREATE/MOVE | folders |
| `packages/ai-parrot/src/parrot/models/bedrock_models.py` | DELETE | moved to amazon/models.py |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | lazy closure paths |
| `packages/ai-parrot/tests/unit/clients/test_folder_convention.py` | MODIFY | CONVERTED += 3 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from parrot.clients.bedrock import BedrockConverseClient   # bedrock.py:1649 (BedrockConverseBase at :140)
from parrot.clients.nova import NovaClient                  # nova/client.py:31  class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration)
from parrot.clients.nova.mantle import BedrockMantleClient  # nova/mantle.py:32 (OpenAIBaseClient subclass)
from parrot.clients.gemma4 import Gemma4Client, Gemma4Model # gemma4.py:50, :38
from parrot.clients.hf import TransformersClient, TransformersModel  # hf.py:51, :27
# parrot/models/bedrock_models.py — 17.5K; `grep -n '^class '` returned NOTHING on 2026-09-04 → constants/dicts, not classes. Inspect before deciding `models`.
```

### Existing Signatures to Use
```python
# parrot/clients/factory.py
def _lazy_bedrock_converse(...):  from .bedrock import BedrockConverseClient   # ~:33
def _lazy_nova(...):              from .nova import NovaClient                 # ~:51
def _lazy_bedrock_mantle(...):    ...                                          # ~:58
def _lazy_gemma4(...):            from .gemma4 import Gemma4Client             # ~:17
SUPPORTED_CLIENTS: "bedrock-converse","nova","bedrock-mantle","mantle","gemma4"  # :115-126, :143
# nova/ files: __init__.py client.py audio.py (aws_sdk_bedrock_runtime) generation.py (aioboto3) mantle.py
```

### Does NOT Exist
- ~~`parrot/clients/amazon/`~~ — does not exist yet.
- ~~`"hf"` / `"transformers"` factory keys~~ — not registered today; introduced as `provider_keys` here, wired by TASK-2847.
- ~~A `BedrockModel` Enum class~~ — unverified; `bedrock_models.py` may be constants only.
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
Keep `aioboto3` / `aws_sdk_bedrock_runtime` imports lazy exactly as today (see the docstrings at `factory.py:24-45`). `amazon/client.py` is an aggregator module so the folder satisfies the three-file rule; the conformance test reads `__all__` of the package, so list all three clients there.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] `from parrot.clients.amazon import BedrockConverseClient, NovaClient, BedrockMantleClient` works; `parrot.clients.bedrock` / `parrot.clients.nova` are gone
- [ ] `from parrot.clients.gemma4 import Gemma4Model`, `from parrot.clients.hf import TransformersModel` work
- [ ] `parrot/models/bedrock_models.py` deleted
- [ ] `LLMFactory.create("bedrock-converse:…")`, `("nova:…")`, `("mantle:…")`, `("gemma4:…")` still resolve a class (lazy closures re-pointed)
- [ ] `pytest packages/ai-parrot/tests/unit/clients -q` green; `ruff` clean

---

## Test Specification

```python
# tests/unit/clients/test_amazon_layout.py
def test_amazon_exports():
    from parrot.clients.amazon import BedrockConverseClient, NovaClient, BedrockMantleClient
    assert BedrockMantleClient.provider_keys == ("bedrock-mantle", "mantle")
def test_lazy_keys_resolve():
    from parrot.clients.factory import SUPPORTED_CLIENTS
    for k in ("bedrock-converse", "nova", "mantle", "gemma4"):
        assert SUPPORTED_CLIENTS[k]() is not None
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
7. **Move this file** to `sdd/tasks/completed/TASK-2845-amazon-gemma4-hf-folders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
