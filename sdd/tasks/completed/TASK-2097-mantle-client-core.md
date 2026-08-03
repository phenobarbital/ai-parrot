# TASK-2097: BedrockMantleClient core — client subclass + conf vars

**Feature**: FEAT-407 — Bedrock Mantle Client
**Spec**: `sdd/specs/bedrock-mantle-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Amazon Bedrock's Project Mantle exposes an OpenAI-compatible API
(`https://bedrock-mantle.<region>.api.aws/v1`, Bedrock API key as bearer
token). This task implements spec §3 Module 1: the
`BedrockMantleClient` subclass of `OpenAIClient` plus the two new conf
vars it reads. It is the foundation the other two tasks build on.

---

## Scope

- Add two conf vars to `packages/ai-parrot/src/parrot/conf.py`,
  immediately after `AWS_NOVA_API_KEY` (line 492):
  - `BEDROCK_MANTLE_API_KEY = config.get("BEDROCK_MANTLE_API_KEY", fallback=None)`
  - `BEDROCK_MANTLE_BASE_URL = config.get("BEDROCK_MANTLE_BASE_URL", fallback=None)`
- Create `packages/ai-parrot/src/parrot/clients/nova/mantle.py` with
  `BedrockMantleClient(OpenAIClient)`:
  - Class attributes: `client_type = "bedrock-mantle"`,
    `client_name = "bedrock-mantle"`,
    `_default_model = "openai.gpt-oss-120b"`,
    `_fallback_model = "google.gemma-4-26b-a4b"`.
  - `__init__(self, api_key=None, base_url=None, region=None, **kwargs)`
    implementing the resolution orders from spec §2:
    - API key: kwarg → `BEDROCK_MANTLE_API_KEY` → `AWS_NOVA_API_KEY`.
    - Base URL: kwarg → `BEDROCK_MANTLE_BASE_URL` →
      `f"https://bedrock-mantle.{region}.api.aws/v1"` where region =
      kwarg → `BEDROCK_AWS_REGION` → `AWS_REGION_NAME` → `"us-east-1"`.
    - `kwargs.setdefault("fallback_model", "google.gemma-4-26b-a4b")`
      BEFORE `super().__init__` (AbstractClient shadowing gotcha, spec §7).
    - Re-set `self.api_key = resolved_key` AFTER `super().__init__`
      (AbstractClient overwrite guard, `nvidia.py:84` pattern).
  - Google-style docstrings documenting both resolution orders (so a
    wrong-region DNS failure is debuggable from the docstring alone).
- Everything else (`ask`, `ask_stream`, `invoke`, tool-calling, retry)
  is INHERITED — do not reimplement or override any OpenAI machinery.

**NOT in scope**: factory registration and `nova/__init__.py` export
(TASK-2098); tests and docs (TASK-2099); any `_chat_completion`
override (only if live verification in TASK-2099 shows Mantle rejects
`parse()` — see spec §8); model enums; boto/SigV4 code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/mantle.py` | CREATE | `BedrockMantleClient` implementation |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `BEDROCK_MANTLE_API_KEY`, `BEDROCK_MANTLE_BASE_URL` near line 492 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
# Inside parrot/clients/nova/mantle.py (module is one level deeper than nvidia.py):
from ..gpt import OpenAIClient        # verified: packages/ai-parrot/src/parrot/clients/gpt.py:79
from navconfig import config          # verified: same import used by clients/gpt.py and clients/nvidia.py:15
from parrot.conf import (             # all verified in packages/ai-parrot/src/parrot/conf.py
    AWS_NOVA_API_KEY,                 # line 492
    BEDROCK_AWS_REGION,               # line 488
    AWS_REGION_NAME,                  # line 474
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/gpt.py:79
class OpenAIClient(AbstractClient):
    client_type: str = "openai"                                          # line 82
    client_name: str = "openai"                                          # line 84
    _default_model: str = "gpt-5-mini"                                   # line 85
    _fallback_model: str = "gpt-5-nano"                                  # line 86

    def __init__(self, api_key: str = None,
                 base_url: str = "https://api.openai.com/v1", **kwargs):  # line 91
        # sets self.api_key (falls back to config OPENAI_API_KEY only when
        # api_key is falsy), self.base_url, self.base_headers (Bearer),
        # then super().__init__(**kwargs)

    async def get_client(self) -> "AsyncOpenAI":                          # line 203
        # AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
        #             timeout=config.get("OPENAI_TIMEOUT", 60))
```

```python
# packages/ai-parrot/src/parrot/clients/nvidia.py:74-84 — THE __init__ pattern to copy
def __init__(self, api_key: Optional[str] = None, **kwargs):
    resolved_key = api_key or config.get("NVIDIA_API_KEY")
    super().__init__(api_key=resolved_key, base_url="https://...", **kwargs)
    # Re-set after super().__init__ because AbstractClient may overwrite
    # self.api_key during its own initialisation (line 84)
    self.api_key = resolved_key
```

```python
# packages/ai-parrot/src/parrot/clients/bedrock.py:186-192 — region resolution order to mirror
self._region = (region or credentials.get('region_name')
                or BEDROCK_AWS_REGION or AWS_REGION_NAME or "us-east-1")
# NOTE: mantle.py does NOT use AWS_CREDENTIALS profiles — drop the
# credentials.get(...) step; only kwarg → BEDROCK_AWS_REGION →
# AWS_REGION_NAME → "us-east-1".

# packages/ai-parrot/src/parrot/clients/bedrock.py:199-209 — documents the
# AbstractClient._fallback_model shadowing bug and the setdefault workaround.
```

```python
# packages/ai-parrot/src/parrot/conf.py — insertion anchor
AWS_REGION_NAME = config.get("AWS_REGION_NAME", fallback=aws_region)      # line 474
BEDROCK_AWS_REGION = config.get("BEDROCK_AWS_REGION", fallback=None)      # line 488
AWS_NOVA_API_KEY = config.get("AWS_NOVA_API_KEY", fallback=None)          # line 492  ← add new vars after this
```

### Does NOT Exist

- ~~`BEDROCK_MANTLE_API_KEY` / `BEDROCK_MANTLE_BASE_URL` in `parrot.conf`~~
  — THIS task creates them; do not import until added.
- ~~`parrot.clients.bedrock_mantle`~~ — the module lives at
  `parrot/clients/nova/mantle.py`, nothing else.
- ~~`OpenAIClient.responses` / Responses-API wrapper~~ — chat-completions only.
- ~~`BedrockMantleModel` enum~~ — out of scope for v1 (spec §1 Non-Goals).
- ~~`AWS_CREDENTIALS` profile resolution in this client~~ — that belongs
  to `BedrockConverseBase` (boto path); Mantle uses bearer key + region
  conf vars only.
- ~~`from .gpt import OpenAIClient`~~ — WRONG depth from inside `nova/`;
  it is `from ..gpt import OpenAIClient`.

---

## Implementation Notes

### Pattern to Follow

`NvidiaClient` (`packages/ai-parrot/src/parrot/clients/nvidia.py:36-84`)
is the template: thin subclass, resolve key/URL before `super().__init__`,
re-set `self.api_key` after. The ONLY additions vs. nvidia are: (a) the
region→base_url construction, (b) the `fallback_model` setdefault guard.

### Key Constraints

- Async-first: no blocking I/O; no new sync code paths.
- No new dependencies — the `openai` SDK is already the transport
  (installed via the `ai-parrot[openai]` extra).
- No `aioboto3`/`botocore` import anywhere in `mantle.py`.
- Pass the *resolved* key into `super().__init__` so `base_headers`
  gets the correct Bearer value (spec §7).
- Google-style docstrings + strict type hints throughout.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/nvidia.py` — subclass pattern
- `packages/ai-parrot/src/parrot/clients/bedrock.py:186-209` — region order + fallback-shadowing workaround
- `sdd/specs/bedrock-mantle-client.spec.md` §2, §6, §7 — full design

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/clients/nova/mantle.py` created per scope
- [ ] Conf vars added; `from parrot.conf import BEDROCK_MANTLE_API_KEY, BEDROCK_MANTLE_BASE_URL` works
- [ ] `from parrot.clients.nova.mantle import BedrockMantleClient` works (package export is TASK-2098)
- [ ] `BedrockMantleClient(region="eu-west-1", api_key="k").base_url == "https://bedrock-mantle.eu-west-1.api.aws/v1"`
- [ ] Constructed instance has `_fallback_model == "google.gemma-4-26b-a4b"` (not shadowed to `None`)
- [ ] No OpenAI machinery overridden (no `ask`/`ask_stream`/`invoke`/`_chat_completion` in the subclass)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/nova/mantle.py`

---

## Test Specification

> Formal unit tests land in TASK-2099. For THIS task, verify behavior
> with a quick inline check (no live network):

```python
from parrot.clients.nova.mantle import BedrockMantleClient

c = BedrockMantleClient(api_key="ABSK-test", region="us-east-1")
assert c.base_url == "https://bedrock-mantle.us-east-1.api.aws/v1"
assert c.api_key == "ABSK-test"
assert c._fallback_model == "google.gemma-4-26b-a4b"
assert c.client_type == "bedrock-mantle"

c2 = BedrockMantleClient(api_key="k", base_url="https://custom/v1")
assert c2.base_url == "https://custom/v1"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/bedrock-mantle-client.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2097-mantle-client-core.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-03
**Notes**: Added `BEDROCK_MANTLE_API_KEY` / `BEDROCK_MANTLE_BASE_URL` conf
vars in `parrot/conf.py` right after `AWS_NOVA_API_KEY`. Created
`BedrockMantleClient(OpenAIClient)` in `parrot/clients/nova/mantle.py`
implementing the region-aware base-URL resolution and API-key resolution
orders from spec §2, with the `fallback_model` setdefault guard applied
before `super().__init__()` and `self.api_key` re-set after (mirroring
`NvidiaClient`). No OpenAI machinery overridden. Verified via inline
script (base_url construction, explicit overrides, fallback_model
survival, no `ask`/`ask_stream`/`invoke`/`_chat_completion` overrides, no
`aioboto3`/`botocore` references) and `ruff check` (clean).

Note: importing this repo inside a git worktree resolves `parrot` to the
editable-install location (main repo `packages/ai-parrot/src`), not the
worktree's own copy — `PYTHONPATH` must be prepended with the worktree's
`packages/ai-parrot/src` when running ad hoc verification/tests here.

**Deviations from spec**: none
