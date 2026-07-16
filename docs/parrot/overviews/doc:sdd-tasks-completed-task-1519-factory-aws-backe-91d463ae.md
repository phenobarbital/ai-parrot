---
type: Wiki Overview
title: 'TASK-1519: Register `bedrock` / `anthropic-aws` provider keys in LLMFactory'
id: doc:sdd-tasks-completed-task-1519-factory-aws-backend-keys-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5** of the spec. Exposes the new backends through
relates_to:
- concept: mod:parrot.clients.claude
  rel: mentions
- concept: mod:parrot.clients.factory
  rel: mentions
---

# TASK-1519: Register `bedrock` / `anthropic-aws` provider keys in LLMFactory

**Feature**: FEAT-232 — Enable Anthropic AWS Bedrock & AWS-native Backends
**Spec**: `sdd/specs/enable-anthropic-aws-bedrock.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1518
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec. Exposes the new backends through
`LLMFactory` so users can do `LLMFactory.create("bedrock:claude-sonnet-4-6")` or
`"anthropic-aws:..."`. Each key resolves to `AnthropicClient` pre-bound to the
right `backend`.

---

## Scope

- In `clients/factory.py`, add entries to `SUPPORTED_CLIENTS`:
  - `"bedrock"` → `AnthropicClient` with `backend="bedrock"`.
  - `"anthropic-aws"` → `AnthropicClient` with `backend="aws"`.
  - (Decide alias names per spec §8 open question; at minimum ship these two.)
- Because `SUPPORTED_CLIENTS` maps a key to a class, pre-binding `backend` needs a
  small adapter: either a lazy loader returning a `functools.partial`/factory
  callable, OR have `LLMFactory.create` inject `backend=` when the provider is one
  of the AWS keys. Follow the existing lazy-loader convention
  (`_lazy_claude_agent`, `:16-46`) for the AWS-extra import hint.
- Add unit tests asserting the factory yields an `AnthropicClient` with the
  expected `backend`.

**NOT in scope**: client/backend internals, conf, packaging.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | add 2 provider keys + backend pre-binding |
| `packages/ai-parrot/tests/test_llm_factory.py` | CREATE/MODIFY | factory key tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .claude import AnthropicClient   # verified: clients/factory.py:3
```

### Existing Signatures to Use
```python
# clients/factory.py
SUPPORTED_CLIENTS = {                  # line 49
    "claude": AnthropicClient,         # line 50
    "anthropic": AnthropicClient,      # line 51
    # ...
}                                       # ends line 69

def _lazy_claude_agent():              # line 16 — lazy-loader-with-ImportError-hint pattern
    ...

class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...   # line ~78
    @staticmethod
    def create(llm, model_args=None, tool_manager=None, **kwargs) -> AbstractClient: ...  # line ~106
    # create() resolves lazy loaders: `if callable(client_class) and not isinstance(client_class, type): client_class = client_class()`
    # then builds init_params and calls client_class(**init_params).
```

### Does NOT Exist
- ~~`AnthropicBedrockClient` / `AnthropicAWSClient`~~ — no separate classes; reuse `AnthropicClient(backend=...)`.
- ~~A `backend` field already handled by `create()`~~ — you must inject it for the new keys.

---

## Implementation Notes

### Key Constraints
- `create()` already merges `**kwargs` into `init_params`; the cleanest path is a
  small mapping `PROVIDER_BACKEND = {"bedrock": "bedrock", "anthropic-aws": "aws"}`
  and, when the provider is in it, set `init_params["backend"] = PROVIDER_BACKEND[provider]`
  before instantiation. Keep `SUPPORTED_CLIENTS[key] = AnthropicClient`.
- Preserve existing behavior for all other providers — additive change only.
- If you add a lazy loader for the AWS-extra import hint, mirror `_lazy_claude_agent`.

### References in Codebase
- `clients/factory.py:16-46` — lazy loader + hint.
- `clients/factory.py:49-69` — `SUPPORTED_CLIENTS`.
- `clients/factory.py:106-181` — `create()` flow.

---

## Acceptance Criteria

- [ ] `LLMFactory.create("bedrock:claude-sonnet-4-6")` returns `AnthropicClient` with `backend == "bedrock"`.
- [ ] `LLMFactory.create("anthropic-aws:claude-sonnet-4-6")` returns `AnthropicClient` with `backend == "aws"`.
- [ ] Existing providers (`claude`, `anthropic`, `openai`, …) unchanged.
- [ ] Unsupported provider still raises the existing `ValueError`.
- [ ] `pytest packages/ai-parrot/tests/test_llm_factory.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/factory.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_llm_factory.py
from parrot.clients.factory import LLMFactory
from parrot.clients.claude import AnthropicClient


def test_bedrock_key():
    c = LLMFactory.create("bedrock:claude-sonnet-4-6")
    assert isinstance(c, AnthropicClient) and c.backend == "bedrock"

def test_anthropic_aws_key():
    c = LLMFactory.create("anthropic-aws:claude-sonnet-4-6")
    assert isinstance(c, AnthropicClient) and c.backend == "aws"

def test_existing_anthropic_unchanged():
    c = LLMFactory.create("anthropic")
    assert isinstance(c, AnthropicClient) and getattr(c, "backend", "direct") == "direct"
```

---

## Agent Instructions

Standard SDD flow. Verify TASK-1518 added the `backend` param to `AnthropicClient`
before wiring the keys. Move this file to `sdd/tasks/completed/`, set status `done`,
fill the note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-10
**Notes**: Added `"bedrock"` and `"anthropic-aws"` to `SUPPORTED_CLIENTS` (both mapping to `AnthropicClient`) plus a `PROVIDER_BACKEND` dict. In `create()`, inject `init_params["backend"] = PROVIDER_BACKEND[provider]` before kwargs merge so explicit `backend=` kwarg still wins. 14 unit tests; all pass, ruff clean.
**Deviations from spec**: none
