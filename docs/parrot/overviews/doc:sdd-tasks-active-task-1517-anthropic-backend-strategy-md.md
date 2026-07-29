---
type: Wiki Overview
title: 'TASK-1517: Backend strategy objects (Direct / Bedrock / AWS-workspace)'
id: doc:sdd-tasks-active-task-1517-anthropic-backend-strategy-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of the spec. These are the composable backend objects
  that
relates_to:
- concept: mod:parrot.clients.anthropic_backends
  rel: mentions
- concept: mod:parrot.models.bedrock_models
  rel: mentions
---

# TASK-1517: Backend strategy objects (Direct / Bedrock / AWS-workspace)

**Feature**: FEAT-232 — Enable Anthropic AWS Bedrock & AWS-native Backends
**Spec**: `sdd/specs/enable-anthropic-aws-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1514
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec. These are the composable backend objects that
`AnthropicClient.get_client()` will dispatch to (TASK-1518). Each knows how to
(a) lazily build its SDK client from resolved config and (b) translate a model ID
for its transport. This keeps `claude.py` thin and isolates per-transport quirks.

---

## Scope

- Create `clients/anthropic_backends.py` with three small classes:
  - `DirectBackend` — `build_client()` returns `AsyncAnthropic(api_key=..., max_retries=2)`;
    `translate_model(m)` is identity.
  - `BedrockBackend` — `build_client()` lazy-imports and returns
    `AsyncAnthropicBedrock(aws_region=..., aws_access_key=..., aws_secret_key=...,
    aws_session_token=...)` (pass `None` for missing keys → SDK uses standard AWS
    chain); `translate_model(m)` calls `parrot.models.bedrock_models.translate`
    with the configured `region_prefix`.
  - `AWSWorkspaceBackend` — `build_client()` **validates** `aws_region` AND
    `workspace_id` are non-empty (raise a clear `ValueError`/ConfigError naming the
    missing field + its env var) BEFORE constructing
    `AsyncAnthropicAWS(aws_region=..., workspace_id=..., aws_access_key=...,
    aws_secret_key=..., aws_session_token=...)`; `translate_model(m)` is identity
    (AWS-workspace uses public IDs unchanged).
- Each backend takes its resolved config via `__init__` (plain attributes — the
  client resolves conf→env precedence in TASK-1518 and passes values in).
- Lazy-import the SDK classes inside `build_client()`; on `ImportError` re-raise
  with hint `pip install ai-parrot[anthropic]`.
- Write unit tests with the SDK classes mocked.

**NOT in scope**: editing `claude.py` (TASK-1518), conf constants (TASK-1515),
factory keys (TASK-1519), credential conf→env resolution (lives in TASK-1518).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/anthropic_backends.py` | CREATE | 3 backend classes |
| `packages/ai-parrot/tests/test_anthropic_backends.py` | CREATE | unit tests (SDK mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.bedrock_models import translate   # from TASK-1514 (verify it exists first)
# Lazy, inside build_client():
from anthropic import AsyncAnthropic           # verified: clients/claude.py:81
from anthropic import AsyncAnthropicBedrock    # verified export: anthropic 0.109.0 (top-level)
from anthropic import AsyncAnthropicAWS        # verified export: anthropic 0.109.0 (impl anthropic.lib.aws._client)
```

### Existing Signatures to Use
```python
# anthropic[aws] 0.109.0 — verified against installed SDK:
# AsyncAnthropicAWS(aws_region=..., workspace_id=...,           # BOTH mandatory, no fallback → raises if missing
#                   aws_access_key=..., aws_secret_key=..., aws_session_token=...,
#                   aws_profile=..., skip_auth=...)
# AsyncAnthropicBedrock(aws_region=..., aws_access_key=..., aws_secret_key=...,
#                       aws_session_token=...)                  # None keys → standard AWS chain
# AsyncAnthropic(api_key=..., max_retries=2)                    # current direct path, clients/claude.py:87

# clients/claude.py:78-90 — the current get_client() that DirectBackend reproduces.
```

### Does NOT Exist
- ~~`workspace_id` named `aws_workspace_id` on the SDK~~ — the SDK param is `workspace_id`.
- ~~`AnthropicBedrockMantle`~~ usage — exported but NOT used by this feature.
- ~~Anthropic Vertex backend~~ — out of scope.
- `parrot.clients.anthropic_backends` — this task CREATES it.

---

## Implementation Notes

### Pattern to Follow
```python
# Lazy import + actionable hint — mirror clients/claude.py:80-86 and
# factory._lazy_claude_agent (clients/factory.py:16-46).
async def build_client(self):
    try:
        from anthropic import AsyncAnthropicBedrock
    except ImportError as exc:
        raise ImportError(
            "Bedrock backend requires the AWS extra. Install with: "
            "pip install ai-parrot[anthropic]"
        ) from exc
    return AsyncAnthropicBedrock(...)
```

### Key Constraints
- `build_client()` should be `async def` to match `AbstractClient.get_client`'s
  signature (the client awaits it). Construction itself is sync, but keep the
  coroutine shape for a clean drop-in.
- Use `self.logger = logging.getLogger(__name__)`.
- AWSWorkspaceBackend validation message must name `AWS_REGION_NAME` /
  `ANTHROPIC_AWS_WORKSPACE_ID` so users know which env var to set.

### References in Codebase
- `clients/claude.py:78-90` — direct `get_client()` to reproduce in `DirectBackend`.
- `clients/factory.py:16-46` — lazy-loader-with-hint pattern.
- `interfaces/aws.py:51-83` — AWS credential handling precedent.

---

## Acceptance Criteria

- [ ] `DirectBackend.build_client()` returns `AsyncAnthropic` (mocked) with `api_key`.
- [ ] `BedrockBackend.build_client()` returns `AsyncAnthropicBedrock` (mocked); `translate_model` applies Bedrock translation.
- [ ] `AWSWorkspaceBackend.build_client()` raises a clear error when `aws_region` or `workspace_id` is missing; succeeds when both present.
- [ ] AWS-workspace `translate_model` is identity; Direct `translate_model` is identity.
- [ ] Missing SDK → ImportError with `pip install ai-parrot[anthropic]` hint.
- [ ] `pytest packages/ai-parrot/tests/test_anthropic_backends.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/anthropic_backends.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_anthropic_backends.py
import pytest
from parrot.clients.anthropic_backends import (
    DirectBackend, BedrockBackend, AWSWorkspaceBackend,
)


async def test_direct_builds(monkeypatch):
    # mock anthropic.AsyncAnthropic; assert returned + api_key passed
    ...

async def test_bedrock_translate_applied():
    b = BedrockBackend(region_prefix="us", aws_region="us-east-1")
    assert b.translate_model("claude-sonnet-4-6").startswith("us.anthropic.")

async def test_aws_requires_region_and_workspace():
    with pytest.raises(ValueError, match="ANTHROPIC_AWS_WORKSPACE_ID"):
        await AWSWorkspaceBackend(aws_region="us-east-1", workspace_id=None).build_client()
```

---

## Agent Instructions

Standard SDD flow. Verify TASK-1514's `translate` exists before importing it.
Move this file to `sdd/tasks/completed/`, set status `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
