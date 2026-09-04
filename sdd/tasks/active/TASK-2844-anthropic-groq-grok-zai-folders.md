# TASK-2844: Convert claude→anthropic/, groq/, grok/, zai/ folders with their enums

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2841
**Assigned-to**: unassigned
**Parallel**: false — Sequential: shares factory.py import block, parrot/models/__init__.py and the conformance test.

---

## Context

Spec §2 map rows anthropic/groq/grok/zai. `claude.py` → `anthropic/` is a **renamed** path (hard cut; the server handler imports `ClaudeModel` from `parrot.clients.claude` inside a try/except — repoint it). `GrokModel` currently lives inside `grok.py:39` and moves to `grok/models.py`.

---

## Scope

- `anthropic/`: `git mv claude.py anthropic/client.py`, `claude_agent.py anthropic/claude_agent.py`, `claude_agent_bridge.py anthropic/claude_agent_bridge.py`, `anthropic_backends.py anthropic/backends.py`, `parrot/models/claude.py anthropic/models.py`. `AnthropicClient.provider_keys = ("claude", "anthropic", "bedrock", "anthropic-aws")`, `models = ClaudeModel`; `ClaudeAgentClient.provider_keys = ("claude-agent", "claude-code")`, `models = ClaudeModel`.
- `groq/`: `git mv groq.py groq/client.py`, `parrot/models/groq.py groq/models.py`; keys `("groq",)`.
- `grok/`: `git mv grok.py grok/client.py`; cut `GrokModel` (`grok.py:39`) into `grok/models.py`; keys `("grok", "xai")`.
- `zai/`: `git mv zai.py zai/client.py`, `parrot/models/zai.py zai/models.py`; keys `("zai", "z.ai")`; drop `ZaiModel` from `parrot/models/__init__.py:108`. Leave the `ZaiClient` export in `parrot/clients/__init__.py:17` for TASK-2847 (path `.zai` still resolves).
- Update `factory.py:3,6,12` and `_lazy_claude_agent`; update callers of `parrot.clients.claude`, `parrot.clients.claude_agent`, `parrot.clients.anthropic_backends`, `parrot.models.{claude,groq,zai}` in `packages/*/src`, tests (`test_claude_multiround_usage.py`, `test_grok_*`, `test_groq_*`), `examples/`.
- Append anthropic, groq, grok, zai to `CONVERTED`.

**NOT in scope**: Bedrock Converse / Nova (TASK-2845) even though `AnthropicClient` has a Bedrock backend. Removing the `ZaiClient` export (TASK-2847).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/anthropic/{__init__,client,claude_agent,claude_agent_bridge,backends,models}.py` | CREATE/MOVE | folder |
| `packages/ai-parrot/src/parrot/clients/{groq,grok,zai}/{__init__,client,models}.py` | CREATE/MOVE | folders |
| `packages/ai-parrot/src/parrot/models/{claude,groq,zai}.py` | DELETE | moved |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | drop ZaiModel |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | import paths |
| `packages/ai-parrot-server/src/parrot/handlers/llm.py:32` | MODIFY | try-import ClaudeModel from parrot.clients.anthropic (TASK-2848 removes it) |
| `packages/ai-parrot/tests/unit/clients/test_folder_convention.py` | MODIFY | CONVERTED += 4 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from parrot.clients.claude import AnthropicClient       # claude.py:75  → parrot.clients.anthropic
from ..models.claude import ClaudeModel                  # claude.py:61
from parrot.clients.claude_agent import ClaudeAgentClient  # claude_agent.py:263
from parrot.clients.groq import GroqClient               # groq.py:51
from parrot.clients.grok import GrokClient, GrokModel    # grok.py:54, :39
from parrot.clients.zai import ZaiClient                 # zai.py:27 (SDK imported lazily at :81)
from parrot.models.zai import ZaiModel                   # models/__init__.py:108
```

### Existing Signatures to Use
```python
# parrot/clients/anthropic_backends.py
class AnthropicBackendProtocol(Protocol): ...  # :39
class DirectBackend: ...        # :52
class BedrockBackend: ...       # :98
class AWSWorkspaceBackend: ...  # :179
# parrot/clients/claude_agent_bridge.py:63  class ClaudeAgentToolBridge
# parrot/clients/factory.py
from .claude import AnthropicClient   # :3
from .groq import GroqClient          # :6
from .grok import GrokClient          # :7
from .zai import ZaiClient            # :12
PROVIDER_BACKEND = {"bedrock": "bedrock", "anthropic-aws": "aws"}   # :155 — UNCHANGED
# parrot/clients/__init__.py:17  from .zai import ZaiClient   (leave for TASK-2847)
```

### Does NOT Exist
- ~~`parrot/clients/anthropic.py`~~ — today the file is `claude.py`; after this task `anthropic/` is a folder.
- ~~`parrot.clients.grok.models` today~~ — enum is inline in `grok.py:39` until this task.
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
`anthropic_backends.py` is imported by `claude.py`; keep it inside the folder as `backends.py` and fix the relative import. `PROVIDER_BACKEND` keys `bedrock`/`anthropic-aws` map to `AnthropicClient` — include them in its `provider_keys` so the future entry points and `list_providers()` see them.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] `from parrot.clients.anthropic import AnthropicClient, ClaudeAgentClient, ClaudeModel` works; `parrot.clients.claude` is gone
- [ ] `AnthropicClient.provider_keys == ("claude", "anthropic", "bedrock", "anthropic-aws")`; `GrokClient.provider_keys == ("grok", "xai")`
- [ ] `parrot/models/{claude,groq,zai}.py` deleted; `parrot.models` has no `ZaiModel`
- [ ] `pytest packages/ai-parrot/tests/unit/clients -q` green; `ruff` clean

---

## Test Specification

```python
# tests/unit/clients/test_anthropic_layout.py
def test_anthropic_exports():
    from parrot.clients.anthropic import AnthropicClient, ClaudeAgentClient, ClaudeModel
    assert AnthropicClient.models is ClaudeModel
    assert set(AnthropicClient.provider_keys) >= {"claude", "anthropic", "bedrock", "anthropic-aws"}
def test_grok_enum_moved():
    from parrot.clients.grok.models import GrokModel
    from parrot.clients.grok import GrokClient
    assert GrokClient.models is GrokModel
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
7. **Move this file** to `sdd/tasks/completed/TASK-2844-anthropic-groq-grok-zai-folders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
