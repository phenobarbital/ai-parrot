---
type: Wiki Overview
title: 'Feature Specification: Enable Anthropic AWS Bedrock & AWS-native Backends'
id: doc:sdd-specs-enable-anthropic-aws-bedrock-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's `AnthropicClient` (`clients/claude.py`) can only reach Claude
  through
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Enable Anthropic AWS Bedrock & AWS-native Backends

**Feature ID**: FEAT-232
**Date**: 2026-06-10
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x

> Input: `sdd/proposals/enable-anthropic-aws-bedrock.proposal.md` (research-grounded,
> mode=enrichment, all 4 design forks resolved). Audit: `sdd/state/FEAT-232/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's `AnthropicClient` (`clients/claude.py`) can only reach Claude through
the direct Anthropic API (`AsyncAnthropic`). Enterprise deployments frequently
require Claude served through **AWS Bedrock** (`AnthropicBedrock`, IAM/STS
credentials, region-scoped, ARN/inference-profile model IDs) or the **AWS-native
workspace** path (`AnthropicAWS`, `workspace_id`). Today neither is reachable
without bypassing the framework. The full ~1600-line completion/streaming/vision/
tool-call pipeline in `claude.py` is transport-agnostic — it operates only on the
object returned by `get_client()` — so the gap is narrow: SDK selection,
credential intake, and Bedrock model-ID translation.

### Goals

- Let one `AnthropicClient` reach Claude via **three** transports selected by a
  `backend` parameter: `direct` (current, default), `bedrock`, `aws`.
- Make `get_client()` a factory that builds a per-backend, composable SDK client;
  keep all downstream completion logic untouched.
- Translate public model IDs (e.g. `claude-sonnet-4-6`) to Bedrock IDs via
  **map + region-prefix + pass-through**, applied uniformly at every model-
  resolution site.
- Read AWS / workspace credentials from `parrot.conf` first, then environment,
  then leave `None` for the SDK's own AWS chain — mirroring `interfaces/aws.py`.
- Ship **both** Bedrock and AWS-workspace backends in this feature.

### Non-Goals (explicitly out of scope)

- Anthropic **Vertex** (Google Cloud) backend — not requested.
- Changing the completion / streaming / vision / tool-call / batch logic.
- Changing `AbstractClient`'s per-loop client cache machinery.
- Separate subclasses per backend — rejected in proposal §5 in favor of a single
  class with a `backend` strategy (see `proposals/enable-anthropic-aws-bedrock.proposal.md`).

---

## 2. Architectural Design

### Overview

Keep a **single** `AnthropicClient` for all Claude communication and add a
`backend: Literal["direct","bedrock","aws"] = "direct"` parameter. `get_client()`
becomes a factory that dispatches on `self.backend` to instantiate a small
composable **backend object**, each of which knows how to (a) build its SDK
client from resolved credentials and (b) translate a public model ID for its
transport. Shared logic stays in `AnthropicClient`; only credential intake, SDK
selection, and model translation vary per backend.

A single `_resolve_model()` chokepoint funnels every model-resolution site
through the active backend's `translate_model()`, so Bedrock's prefixed/
inference-profile IDs are applied everywhere or nowhere (preventing 404s).

Resolved design decisions (from proposal §5, carried forward verbatim in §8):
- **Topology**: one class + composable backend objects; `get_client()` is the factory.
- **Model translation**: map + region prefix + pass-through (all three).
- **Scope**: both `bedrock` and `aws` backends in this feature.
- **Packaging**: fold `anthropic[aws]` into the existing `[anthropic]` extra; keep lazy imports.

### Component Diagram

```
LLMFactory ("bedrock" / "anthropic-aws")
      │
      ▼
AnthropicClient(backend=…)                      models/bedrock_models.py
  __init__  → credential intake (conf→env→None)   (map + prefix + pass-through)
  get_client() ── dispatch on backend ──┐               ▲
  _resolve_model() ─────────────────────┼───────────────┘ translate_model()
                                         ▼
                         ┌───────────────┴───────────────┐
                  DirectBackend   BedrockBackend   AWSWorkspaceBackend
                  AsyncAnthropic  AsyncAnthropic   AsyncAnthropicAWS
                                  Bedrock          (region+workspace_id required)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AnthropicClient` (`clients/claude.py:50`) | extends in place | add `backend` param, credential intake, `_resolve_model()` |
| `AnthropicClient.get_client` (`:78`) | rewrite as factory | dispatch on `backend`; lazy-import the chosen SDK class |
| model-resolution sites (`:227,:499,:661-662,:1065,:1169`) | route through `_resolve_model()` | uniform translation chokepoint |
| `LLMFactory.SUPPORTED_CLIENTS` (`clients/factory.py:49`) | register | add `bedrock` / `anthropic-aws` keys |
| `parrot/conf.py` (`:457-484`) | extend | add `AWS_SESSION_TOKEN`, `ANTHROPIC_AWS_WORKSPACE_ID` constants |
| `interfaces/aws.py` (`:51-83`) | pattern reuse | parrot.conf→env→SDK-chain credential precedence |

### Data Models

```python
from typing import Literal, Optional

# backend selector accepted by AnthropicClient.__init__
AnthropicBackend = Literal["direct", "bedrock", "aws"]
```

Backends are small classes (not Pydantic) holding resolved config; the public
data contract is just the `backend` string plus AWS credential kwargs.

### New Public Interfaces

```python
# clients/claude.py
class AnthropicClient(AbstractClient):
    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.anthropic.com",
        backend: AnthropicBackend = "direct",
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        aws_region: Optional[str] = None,
        workspace_id: Optional[str] = None,   # AWS-workspace only; SDK param name (NOT aws_workspace_id)
        aws_profile: Optional[str] = None,     # optional, passed through to AWS backends
        **kwargs,
    ): ...

    async def get_client(self):  # returns AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicAWS
        ...

    def _resolve_model(self, model) -> str:
        """Resolve a model arg to a string and apply the backend's translation."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Bedrock model-ID translator
- **Path**: `packages/ai-parrot/src/parrot/models/bedrock_models.py` (new)
- **Responsibility**: `translate(public_id, region_prefix=None) -> str` implementing
  **map + region-prefix + pass-through**: static `public → Bedrock base ID` map;
  optional cross-region inference-profile prefix (`us.`/`eu.`/`apac.`); verbatim
  pass-through when the input already looks like a Bedrock ID/ARN
  (e.g. contains `anthropic.` or starts with `arn:` or a known region prefix).
- **Depends on**: `models/claude.py::ClaudeModel` (source of public IDs).

### Module 2: Backend strategy objects
- **Path**: `packages/ai-parrot/src/parrot/clients/anthropic_backends.py` (new)
- **Responsibility**: `DirectBackend`, `BedrockBackend`, `AWSWorkspaceBackend`,
  each with `build_client()` (lazy-imports its SDK class, constructs it from
  resolved config) and `translate_model(model_str) -> str` (identity for direct/
  aws; Bedrock translator for bedrock).
  `AWSWorkspaceBackend.build_client()` MUST validate that `aws_region` **and**
  `workspace_id` are non-empty before constructing `AsyncAnthropicAWS` (the SDK
  raises at construction otherwise — no fallback); raise a clear `ConfigError`/
  `ValueError` naming the missing field and its env var.
- **Depends on**: Module 1.

### Module 3: AnthropicClient integration
- **Path**: `packages/ai-parrot/src/parrot/clients/claude.py` (modify)
- **Responsibility**: add `backend` + AWS kwargs to `__init__` with conf→env
  credential resolution; instantiate the chosen backend; rewrite `get_client()`
  to delegate to `backend.build_client()`; add `_resolve_model()` and route the
  ~5 model-resolution sites through it.
- **Depends on**: Module 2.

### Module 4: Configuration constants
- **Path**: `packages/ai-parrot/src/parrot/conf.py` (modify)
- **Responsibility**: add `AWS_SESSION_TOKEN = config.get("AWS_SESSION_TOKEN", fallback=None)`
  and `ANTHROPIC_AWS_WORKSPACE_ID = config.get("ANTHROPIC_AWS_WORKSPACE_ID", fallback=None)`
  alongside the existing AWS constants (`:457-484`). Note: the env/conf constant is
  `ANTHROPIC_AWS_WORKSPACE_ID`, but it feeds the SDK's `workspace_id` parameter
  (the SDK has no `aws_` prefix on this field).
- **Depends on**: none.

### Module 5: Factory registration
- **Path**: `packages/ai-parrot/src/parrot/clients/factory.py` (modify)
- **Responsibility**: add `"bedrock"` and `"anthropic-aws"` (+ agreed aliases) to
  `SUPPORTED_CLIENTS`, pre-binding `backend=`; use a lazy loader that re-raises a
  missing-SDK `ImportError` with a `pip install ai-parrot[anthropic]` hint
  (mirrors `_lazy_claude_agent` at `:16-46`).
- **Depends on**: Module 3.

### Module 6: Packaging
- **Path**: `packages/ai-parrot/pyproject.toml` (modify)
- **Responsibility**: change the `[anthropic]` extra to `anthropic[aiohttp,aws]`
  (lines 331-332 and the `all`-style duplicate at 363) so the AWS SDK ships with
  the existing extra. Keep imports lazy in `get_client()`.
- **Depends on**: none.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_bedrock_translate_map` | M1 | Public `claude-sonnet-4-6` maps to the configured Bedrock base ID |
| `test_bedrock_translate_region_prefix` | M1 | Region prefix (`us.`) prepended when configured |
| `test_bedrock_translate_passthrough` | M1 | Already-Bedrock IDs / ARNs returned verbatim |
| `test_backend_direct_builds_asyncanthropic` | M2 | `DirectBackend.build_client()` returns `AsyncAnthropic` |
| `test_backend_bedrock_builds_bedrock_client` | M2 | `BedrockBackend.build_client()` returns `AsyncAnthropicBedrock` |
| `test_get_client_dispatches_on_backend` | M3 | `get_client()` returns the SDK class matching `backend` |
| `test_resolve_model_routes_through_backend` | M3 | `_resolve_model()` applies the active backend's translation |
| `test_credential_precedence_conf_then_env` | M3 | parrot.conf value wins; env used only when conf is None; `None` passed to SDK otherwise |
| `test_aws_requires_region_and_workspace` | M2 | `backend="aws"` missing `aws_region` or `workspace_id` raises a clear error before SDK construction |
| `test_factory_bedrock_key` | M5 | `LLMFactory.create("bedrock:…")` yields `AnthropicClient(backend="bedrock")` |
| `test_missing_aws_sdk_hint` | M5 | Missing `anthropic[aws]` raises ImportError with install hint |

### Integration Tests
| Test | Description |
|---|---|
| `test_direct_backend_regression` | Existing direct-path completion unchanged (no `backend` arg) |
| `test_bedrock_completion_mocked` | Mocked `AsyncAnthropicBedrock.messages.create` receives a translated model ID at every code path (completion, structured, batch) |

### Test Data / Fixtures
```python
@pytest.fixture
def bedrock_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY", "AKIA_TEST")
    monkeypatch.setenv("AWS_SECRET_KEY", "secret_test")
    monkeypatch.setenv("AWS_REGION_NAME", "us-east-1")
```

---

## 5. Acceptance Criteria

- [ ] `AnthropicClient(backend="direct")` is byte-for-byte equivalent to today's
  behavior; existing tests pass unchanged (`tests/test_anthropic_client.py`).
- [ ] `AnthropicClient(backend="bedrock")` builds `AsyncAnthropicBedrock` in
  `get_client()`; `backend="aws"` builds the AWS-workspace SDK client.
- [ ] Every model-resolution site (`:227, :499, :661-662, :1065, :1169`) routes
  through `_resolve_model()`; a Bedrock-path test asserts the translated ID at
  completion, structured-output, and batch paths.
- [ ] Bedrock translation implements map + region-prefix + pass-through (3 unit tests).
- [ ] Credentials resolve parrot.conf → env → `None` (SDK chain) for the Bedrock
  backend (`aws_access_key`, `aws_secret_key`, `aws_session_token`, `aws_region`);
  verified by `test_credential_precedence_conf_then_env`.
- [ ] `backend="aws"` validates that `aws_region` **and** `workspace_id` are
  present and raises a clear error (naming `AWS_REGION_NAME` /
  `ANTHROPIC_AWS_WORKSPACE_ID`) before constructing `AsyncAnthropicAWS`; the SDK
  receives `workspace_id` (not `aws_workspace_id`).
- [ ] `LLMFactory` resolves `bedrock` and `anthropic-aws` provider keys.
- [ ] Missing `anthropic[aws]` SDK raises ImportError with a `pip install
  ai-parrot[anthropic]` hint.
- [ ] `conf.py` exposes `AWS_SESSION_TOKEN` and `ANTHROPIC_AWS_WORKSPACE_ID`.
- [ ] `pyproject.toml` `[anthropic]` extra includes `aws`.
- [ ] All unit tests pass (`pytest tests/ -v`); no breaking change to the public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against the working tree on
> 2026-06-10. Paths are relative to `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from navconfig import config                       # verified: clients/claude.py:14
from ..conf import (                                # verified: interfaces/aws.py:10-14
    AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION_NAME, AWS_CREDENTIALS
)
from .base import AbstractClient                    # verified: clients/claude.py:17
from ..models.claude import ClaudeModel             # verified: clients/claude.py:41
from anthropic import AsyncAnthropic                # verified: clients/claude.py:81 (lazy, inside get_client)
from .claude import AnthropicClient                 # verified: clients/factory.py:3
# anthropic 0.109.0 top-level exports (verified by user against installed SDK):
from anthropic import AsyncAnthropicBedrock         # Amazon Bedrock transport
from anthropic import AsyncAnthropicAWS             # Claude Platform on AWS (impl: anthropic.lib.aws._client)
```

### Existing Class Signatures
```python
# clients/claude.py
class AnthropicClient(AbstractClient):              # line 50
    version: str = "2023-06-01"                     # line 51
    client_type: str = "anthropic"                  # line 52
    client_name: str = "claude"                     # line 53
    _default_model: str = 'claude-sonnet-4-5'       # line 56
    _fallback_model: str = 'claude-sonnet-4.5'      # line 57
    _lightweight_model: str = "claude-haiku-4-5-20251001"  # line 58

    def __init__(self, api_key: str = None,
                 base_url: str = "https://api.anthropic.com", **kwargs):  # line 62
        self.api_key = api_key or config.get('ANTHROPIC_API_KEY')        # line 68

    async def get_client(self) -> "AsyncAnthropic":  # line 78 — SOLE SDK-construction seam
        from anthropic import AsyncAnthropic         # line 81 (lazy)
        return AsyncAnthropic(api_key=self.api_key, max_retries=2)  # line 87

# Model resolution sites (all must route through _resolve_model):
#   :227  model = (model.value if isinstance(model, ClaudeModel) else model) or (self.model or self.default_model)
#   :499  model = state.get("agent_name", self.model or self.default_model)
#   :661-662  (model.value if isinstance(model, ClaudeModel) else model) or (self.model or self.default_model)
#   :1065 "model": model.value if isinstance(model, ClaudeModel) else model
#   :1169 model=model.value if isinstance(model, ClaudeModel) else model

# clients/base.py
class AbstractClient:
    @property
    def default_model(self) -> str:                 # line 813
        return getattr(self, '_default_model', None)  # line 815
    async def get_client(self) -> Any: ...          # line 846 (base default)
    # per-loop client cache via _ensure_client()/get_client(); subclasses override get_client only.

# models/claude.py
class ClaudeModel(Enum):                            # line 4
    OPUS_4_6 = "claude-opus-4-6"                    # public IDs to translate for Bedrock

# clients/factory.py
SUPPORTED_CLIENTS = { "claude": AnthropicClient, "anthropic": AnthropicClient, ... }  # line 49
def _lazy_claude_agent(): ...                       # line 16 — lazy-loader-with-hint pattern to copy

# anthropic[aws] 0.109.0 — verified by user against installed SDK
# AsyncAnthropicAWS(aws_region=..., workspace_id=...,            # BOTH mandatory, no fallback → raises at construction
#                   aws_access_key=..., aws_secret_key=..., aws_session_token=...,
#                   aws_profile=..., skip_auth=...)
# AsyncAnthropicBedrock(aws_region=..., aws_access_key=..., aws_secret_key=...,
#                       aws_session_token=...)                   # no-keys → standard AWS chain
# (Also exported: AnthropicBedrockMantle / AsyncAnthropicBedrockMantle — NOT used here.)

# conf.py
AWS_ACCESS_KEY  = config.get("AWS_ACCESS_KEY",  fallback=aws_key)     # line 457
AWS_SECRET_KEY  = config.get("AWS_SECRET_KEY",  fallback=aws_secret)  # line 458
AWS_REGION_NAME = config.get("AWS_REGION_NAME", fallback=aws_region)  # line 459
AWS_CREDENTIALS = { ... }                                             # line 473
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AnthropicClient.get_client` (rewrite) | backend `build_client()` | delegation | `clients/claude.py:78` |
| `_resolve_model()` | the 5 model sites | helper call | `clients/claude.py:227,499,661,1065,1169` |
| factory keys | `AnthropicClient(backend=…)` | `SUPPORTED_CLIENTS` | `clients/factory.py:49` |
| credential intake | `parrot.conf` constants | `from ..conf import` | `interfaces/aws.py:10` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AWS_SESSION_TOKEN`~~ in `conf.py` — **must be added** (Module 4).
- ~~`ANTHROPIC_AWS_WORKSPACE_ID`~~ in `conf.py` — **must be added** (Module 4).
- ~~`AnthropicBedrockClient`~~ / ~~`AnthropicAWSClient`~~ — no separate subclasses (rejected; single class + `backend`).
- ~~`aws_workspace_id`~~ as an SDK parameter — **does not exist**; the SDK param is `workspace_id` (our env/conf constant is `ANTHROPIC_AWS_WORKSPACE_ID`, mapped to `workspace_id` at the call site).
- `parrot.conf` is NOT imported by `claude.py` today — it uses `from navconfig import config`. Either import the conf constants or use `config.get(...)`; do not assume the constants are already in scope there.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Lazy SDK import + actionable hint** — mirror `_lazy_claude_agent` (`factory.py:16-46`)
  and the existing `get_client()` ImportError message (`claude.py:81-86`).
- **parrot.conf → env → SDK-chain credentials** — mirror `AWSInterface`
  (`interfaces/aws.py:51-83`), including the deliberate fall-through (pass `None`
  so the SDK resolves via `~/.aws/credentials` / `AWS_ACCESS_KEY_ID` / IMDS).
- Async-first; type hints + Google-style docstrings; `self.logger` not print.

### Known Risks / Gotchas
- **Incomplete translation coverage** (primary risk): the model string is resolved
  at **≥5** sites — all must route through `_resolve_model()` or Bedrock 404s on
  unprefixed IDs. Add a per-path Bedrock test.
- **AWS-workspace mandatory fields**: `AsyncAnthropicAWS` requires **both**
  `aws_region` and `workspace_id` and raises at construction if either is missing
  (no fallback). The "conf→env→None (SDK chain)" precedence that works for Bedrock
  does NOT apply here — `AWSWorkspaceBackend` must validate these are present and
  raise an actionable error naming the env var (`AWS_REGION_NAME` /
  `ANTHROPIC_AWS_WORKSPACE_ID`). The SDK param is `workspace_id`, not `aws_workspace_id`.
- **Region-dependent inference-profile prefixes**: a hard-coded prefix breaks
  cross-region callers — keep it configurable with a pass-through escape hatch.
- **`_fallback_model` is `'claude-sonnet-4.5'`** (note the dot) — Bedrock fallback
  must also be translated, not passed raw.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `anthropic[aws]` | folded into existing `anthropic[aiohttp]>=0.109.0,<1.0.0` | Bedrock + AWS-workspace transports |

---

## 8. Open Questions

### Resolved (carried forward from proposal §5)
- [x] **Class topology — subclasses vs. backend switch?** — *Resolved in proposal*:
  one `AnthropicClient` with `backend=direct|bedrock|aws`; `get_client()` is the
  factory that instantiates a composable backend object (incl. the direct SDK).
- [x] **Bedrock model-ID translation strategy?** — *Resolved in proposal*: map +
  region prefix + pass-through (all three).
- [x] **AWS-workspace path in scope now?** — *Resolved in proposal*: yes — both
  backends ship in this feature.
- [x] **Packaging?** — *Resolved in proposal*: fold `anthropic[aws]` into the
  existing `[anthropic]` extra; keep lazy imports in `get_client()`.

### Resolved (verified against installed SDK, 2026-06-10)
- [x] **Exact `AnthropicAWS` async class name + param** — *Resolved*: anthropic
  0.109.0 exports `AsyncAnthropicAWS` (impl `anthropic.lib.aws._client`) and
  `AsyncAnthropicBedrock` at top level. Key params: `aws_region`, `workspace_id`,
  `aws_access_key`/`aws_secret_key`/`aws_session_token`/`aws_profile`, `skip_auth`.
  The param is `workspace_id` (NOT `aws_workspace_id`); `aws_region` + `workspace_id`
  are mandatory with no fallback.

### Unresolved (defer to implementation)
- [ ] **Factory key naming for the AWS-workspace backend** — `"anthropic-aws"`
  vs `"aws"` vs `"claude-aws"`. *Owner: tbd*.
- [ ] **Cross-region inference-profile prefix default** — ship `us.` as default,
  or require explicit config? *Owner: tbd*.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (sequential tasks in one worktree).
- **Rationale**: Modules 1, 4, 6 are independent (translator, conf constants,
  packaging) and could parallelize, but Modules 2→3→5 form a tight chain centered
  on `clients/claude.py` and would conflict if edited in parallel worktrees.
  Sequential execution in one worktree avoids merge churn on `claude.py`.
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-10 | Jesus Lara | Initial draft from proposal FEAT-232 |
