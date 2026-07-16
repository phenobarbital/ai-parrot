---
type: Wiki Overview
title: 'TASK-1518: Integrate backend strategy into AnthropicClient'
id: doc:sdd-tasks-completed-task-1518-anthropicclient-backend-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of the spec — the heart of the feature. Adds the
  `backend`
relates_to:
- concept: mod:parrot.clients.anthropic_backends
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.models.claude
  rel: mentions
---

# TASK-1518: Integrate backend strategy into AnthropicClient

**Feature**: FEAT-232 — Enable Anthropic AWS Bedrock & AWS-native Backends
**Spec**: `sdd/specs/enable-anthropic-aws-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1517, TASK-1515
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec — the heart of the feature. Adds the `backend`
parameter + AWS credential intake to `AnthropicClient`, rewrites `get_client()` to
delegate to the chosen backend, and routes every model-resolution site through a
single `_resolve_model()` chokepoint so Bedrock IDs are translated uniformly.

---

## Scope

- In `clients/claude.py`, `AnthropicClient.__init__`:
  - Add params: `backend: Literal["direct","bedrock","aws"] = "direct"`,
    `aws_access_key`, `aws_secret_key`, `aws_session_token`, `aws_region`,
    `workspace_id`, `aws_profile` (all `Optional[str] = None`).
  - Resolve each AWS value **parrot.conf → env → None**: read the `parrot.conf`
    constant (e.g. `AWS_ACCESS_KEY`, `AWS_REGION_NAME`, `ANTHROPIC_AWS_WORKSPACE_ID`,
    `AWS_SESSION_TOKEN`) when the kwarg is None; leave `None` for the SDK chain
    (Bedrock only — AWS-workspace mandatory fields are validated in the backend).
  - Instantiate the matching backend object from TASK-1517 and store it
    (e.g. `self._backend`).
- Rewrite `get_client()` to `return await self._backend.build_client()`.
- Add `def _resolve_model(self, model) -> str` that resolves the model arg the
  same way the existing sites do (`model.value if isinstance(model, ClaudeModel)
  else model) or (self.model or self.default_model)`) and then applies
  `self._backend.translate_model(...)`.
- Replace the inline model resolution at **every** site with `_resolve_model(...)`:
  `:227`, `:499`, `:661-662`, `:1065`, `:1169`. Also ensure the `_fallback_model`
  path (`:321-323`) is translated before use.
- Update / add tests: direct-path regression, get_client dispatch, credential
  precedence, `_resolve_model` routing.

**NOT in scope**: backend class internals (TASK-1517), conf constants (TASK-1515),
factory keys (TASK-1519), packaging (TASK-1516).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | `__init__`, `get_client`, `_resolve_model`, route 5 sites |
| `packages/ai-parrot/tests/test_anthropic_client.py` | MODIFY | add backend + translation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navconfig import config                       # verified: clients/claude.py:14
from parrot.clients.anthropic_backends import (     # from TASK-1517 (verify it exists)
    DirectBackend, BedrockBackend, AWSWorkspaceBackend,
)
from parrot.conf import (                           # AWS_SESSION_TOKEN/ANTHROPIC_AWS_WORKSPACE_ID from TASK-1515
    AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION_NAME,
    AWS_SESSION_TOKEN, ANTHROPIC_AWS_WORKSPACE_ID,
)
from parrot.models.claude import ClaudeModel        # verified: clients/claude.py:41
```

### Existing Signatures to Use
```python
# clients/claude.py
class AnthropicClient(AbstractClient):              # line 50
    _default_model: str = 'claude-sonnet-4-5'       # line 56
    _fallback_model: str = 'claude-sonnet-4.5'      # line 57
    def __init__(self, api_key=None,
                 base_url="https://api.anthropic.com", **kwargs):  # line 62
        self.api_key = api_key or config.get('ANTHROPIC_API_KEY')  # line 68
        super().__init__(**kwargs)                  # line 76
    async def get_client(self) -> "AsyncAnthropic":  # line 78 (rewrite to delegate)

# Model-resolution sites to replace with self._resolve_model(...):
#   :227  model = (model.value if isinstance(model, ClaudeModel) else model) or (self.model or self.default_model)
#   :499  model = state.get("agent_name", self.model or self.default_model)   # keep agent_name semantics; translate result
#   :661-662  (model.value if isinstance(model, ClaudeModel) else model) or (self.model or self.default_model)
#   :1065 "model": model.value if isinstance(model, ClaudeModel) else model
#   :1169 model=model.value if isinstance(model, ClaudeModel) else model
#   :321-323 payload["model"] = self._fallback_model   # translate before assigning

# clients/base.py
@property
def default_model(self) -> str: return getattr(self, '_default_model', None)  # line 813
# Per-loop client cache: subclasses override get_client() only — do NOT assign self.client.
```

### Does NOT Exist
- ~~`AnthropicBedrockClient` / `AnthropicAWSClient`~~ — single class + `backend` param.
- ~~SDK param `aws_workspace_id`~~ — the SDK param is `workspace_id` (our env constant is `ANTHROPIC_AWS_WORKSPACE_ID`).
- ~~`self.client` assignment~~ — base owns the per-loop cache; only override `get_client()`.

---

## Implementation Notes

### Key Constraints
- **Backward compatibility is an acceptance gate**: `AnthropicClient()` with no
  `backend` must behave exactly as today (DirectBackend reproduces current `get_client`).
- The `:499` site uses `state.get("agent_name", ...)` — preserve that lookup; only
  feed its final string through `translate_model` (wrap, don't drop the agent_name semantics).
- conf→env precedence: prefer explicit kwarg, else the `parrot.conf` constant (which
  navconfig already backs with env). Do NOT read env a second time directly unless a
  constant is absent.
- Async-first; `self.logger`; type hints + Google docstrings.

### References in Codebase
- `clients/claude.py:78-90` — current get_client (DirectBackend parity target).
- `interfaces/aws.py:51-83` — conf→env→SDK-chain precedence precedent.

---

## Acceptance Criteria

- [ ] `AnthropicClient()` (no backend) is behavior-identical to pre-change; existing `test_anthropic_client.py` passes unchanged.
- [ ] `AnthropicClient(backend="bedrock")` → `get_client()` returns `AsyncAnthropicBedrock` (mocked).
- [ ] `AnthropicClient(backend="aws")` → returns `AsyncAnthropicAWS` (mocked) and validates region+workspace_id.
- [ ] `_resolve_model()` is the only place a model string reaches the SDK; a Bedrock test asserts a translated ID at completion, structured-output, and batch paths.
- [ ] Credential precedence (kwarg → conf/env → None) verified by test for the Bedrock path.
- [ ] `pytest packages/ai-parrot/tests/test_anthropic_client.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/claude.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_anthropic_client.py (additions)
async def test_direct_backend_unchanged(monkeypatch):
    # AnthropicClient() get_client() builds AsyncAnthropic (mocked) — parity.
    ...

async def test_bedrock_dispatch(monkeypatch):
    c = AnthropicClient(backend="bedrock", aws_region="us-east-1")
    client = await c.get_client()        # mocked AsyncAnthropicBedrock
    assert client is not None

def test_resolve_model_translates_for_bedrock():
    c = AnthropicClient(backend="bedrock", aws_region="us-east-1")
    assert "anthropic." in c._resolve_model("claude-sonnet-4-6")

def test_resolve_model_identity_for_direct():
    c = AnthropicClient()  # direct
    assert c._resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
```

---

## Agent Instructions

Standard SDD flow. Verify TASK-1517 backends and TASK-1515 conf constants exist
first (they are `Depends-on`). Move this file to `sdd/tasks/completed/`, set status
`done`, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-10
**Notes**: Added `backend`, AWS credential kwargs to `__init__`; credential resolution via conf→env→None; `_resolve_model()` chokepoint; all model-resolution and fallback sites routed through it; `get_client()` delegates to backend. Updated `test_anthropic_client.py` to fix pre-existing mock issues (base class now disallows `client.client = ...` assignment) and added 10 new FEAT-232 tests. 14/14 pass, ruff clean.
**Deviations from spec**: Existing test_anthropic_client.py tests updated (not just "unchanged") because the base class now raises AttributeError on direct `client.client` assignment — the tests needed patching via `_backend` instead.
