# TASK-2854: Core extras → satellites, drop extracted SDK pins, remove transitional registry

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2849, TASK-2850, TASK-2851, TASK-2852, TASK-2853
**Assigned-to**: unassigned
**Parallel**: false — Sequential: needs all 15 satellite names; edits core pyproject.toml and factory.py.

---

## Context

Spec §3 Module 5, AC-8, AC-9. With all folders relocated, core's extras must install satellites instead of raw SDKs, core must stop pinning SDKs it no longer imports, and the transitional in-core registry in `factory.py` goes away.

---

## Scope

- `packages/ai-parrot/pyproject.toml` extras: `anthropic = ["ai-parrot-client-anthropic"]`, `openai = ["ai-parrot-client-openai"]`, `google = ["ai-parrot-client-google"]`, `groq`, `zai`, `bedrock`/`bedrock-native` → `["ai-parrot-client-amazon"]`, `claude-agent` → anthropic satellite, `codex-agent` → openai satellite; add `gemma4`, `hf`, `grok`, `nvidia`, `moonshot`, `openrouter`, `local`, `vllm`, `meta`; `llms = [all 15]`.
- Remove from core `dependencies`/extras every pin now owned by a satellite (`anthropic`, `google-genai`, `groq`, `xai-sdk`, `zai-sdk`, `aioboto3`, `claude-agent-sdk`, `openai-codex`, `transformers`/`torch` **only if** no remaining core module imports them — grep first; `images` extra may still need torch). **Keep `openai==3.3.1` and `tiktoken`** (spec decision: `OpenAIBaseClient` stays in core).
- Root `pyproject.toml`: `all` extra pulls `ai-parrot[llms]` transitively (verify current shape first).
- `factory.py`: delete `_IN_CORE_PROVIDERS` and its branch in `_discover()`; entry points are now the only source.
- `uv lock && uv sync --all-extras`; `python -c 'import parrot.clients.factory'` in a venv with **no** satellites installed must succeed.

**NOT in scope**: Version bumps / release (`/release` skill). Documentation beyond a `docs/migration/feat-523-llm-client-satellites.md` stub listing the renamed import paths.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | extras → satellites; drop pins |
| `pyproject.toml (root)` | MODIFY | all extra transitive |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | remove transitional registry |
| `docs/migration/feat-523-llm-client-satellites.md` | CREATE | renamed paths table |
| `uv.lock` | MODIFY | regenerated |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
# packages/ai-parrot/pyproject.toml extras (line numbers 2026-09-04): anthropic:484 bedrock:491 bedrock-native:502
#   claude-agent:516 codex-agent:520 openai:527 google:532 groq:539 zai:543 ; core deps: tiktoken>=0.9.0 :61 ;
#   google-genai>=2.18.1 :432 and openai==3.3.1 :433 appear inside another extra (:431 mcp) — inspect before touching.
# Root pyproject.toml:57-58 [tool.uv.workspace] members = ["packages/*"]
# Pattern for a meta-extra that pulls satellites: packages/ai-parrot/pyproject.toml `all`/embeddings extras from FEAT-201
```

### Existing Signatures to Use
```python
# spec §7 External Dependencies table lists the pins each satellite owns.
```

### Does NOT Exist
- ~~`_IN_CORE_PROVIDERS`~~ — exists only between TASK-2847 and this task; delete it.
- ~~`ai-parrot[llms]` installing SDKs directly~~ — after this task it installs satellites which bring their own SDKs.
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
Grep for residual core imports before dropping a pin: `grep -rn "^\s*\(from\|import\) \(anthropic\|google.genai\|groq\|xai_sdk\|aioboto3\|claude_agent_sdk\|transformers\|torch\)" packages/ai-parrot/src`. `parrot/tokenizer` or `interfaces/images` may still need `transformers`/`torch` — keep those pins in their own extras, not in `llms`.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] Core `dependencies` has no extracted SDK pin except `openai` and `tiktoken`; `ai-parrot[llms]` resolves to the 15 satellites
- [ ] Fresh venv with `uv pip install -e packages/ai-parrot` (no satellites) → `python -c 'from parrot.clients.factory import LLMFactory; LLMFactory.list_providers()'` returns `{}` without error
- [ ] `_IN_CORE_PROVIDERS` gone; `uv lock` clean; full `pytest packages/ai-parrot/tests/unit -q` green (timeout-wrapped)

---

## Test Specification

```python
# tests/unit/clients/test_core_has_no_sdk_pins.py
import tomllib, pathlib
def test_core_pins():
    py = tomllib.loads(pathlib.Path("packages/ai-parrot/pyproject.toml").read_text())
    deps = " ".join(py["project"]["dependencies"])
    for sdk in ("anthropic", "google-genai", "groq", "xai-sdk", "zai-sdk", "aioboto3", "claude-agent-sdk"):
        assert sdk not in deps
    assert "openai" in deps and "tiktoken" in deps
    assert len(py["project"]["optional-dependencies"]["llms"]) == 15
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
7. **Move this file** to `sdd/tasks/completed/TASK-2854-core-extras-workspace-cleanup.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
