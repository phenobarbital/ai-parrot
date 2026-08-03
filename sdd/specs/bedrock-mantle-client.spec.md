---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Bedrock Mantle Client

**Feature ID**: FEAT-407
**Date**: 2026-08-03
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.25.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Amazon Bedrock now exposes **Project Mantle** — a distributed inference
engine with an **OpenAI-compatible API** for Bedrock-hosted models
(endpoint: `https://bedrock-mantle.<region>.api.aws/v1`, authenticated
with a Bedrock API key as the bearer token). This lets any OpenAI-SDK
consumer talk to Bedrock models (`openai.gpt-oss-120b`,
`anthropic.claude-*`, …) without SigV4 signing or the Converse API.

AI-Parrot already has a mature `OpenAIClient` with completion,
streaming, tool-calling, structured output, retry, and fallback
machinery, and a proven pattern for OpenAI-compatible gateways
(`NvidiaClient`, `OpenRouterClient`, `MoonshotClient`, `ZaiClient`).
What is missing is a drop-in client that points that machinery at the
Bedrock Mantle endpoint, so agents and crews can use Bedrock-hosted
models through the plain OpenAI SDK path — complementing (not
replacing) the native `BedrockConverseClient` (FEAT-302) and
`NovaClient` (FEAT-315).

### Goals

- `BedrockMantleClient` extends `OpenAIClient` as a **drop-in
  replacement** for OpenAI-compatible usage of Bedrock-hosted models.
- Lives in `parrot/clients/nova/` (satellite of the existing AWS/Nova
  client subpackage), exported from `parrot.clients.nova`.
- Region-aware endpoint construction: base URL defaults to
  `https://bedrock-mantle.<region>.api.aws/v1`, with the region resolved
  from existing Bedrock conventions (`BEDROCK_AWS_REGION` →
  `AWS_REGION_NAME` → `"us-east-1"`) and an explicit `base_url` override
  always winning.
- Bedrock API key (bearer token) resolution via kwarg → dedicated conf
  var → existing `AWS_NOVA_API_KEY` fallback.
- Factory registration (`LLMFactory`) so `"bedrock-mantle:<model>"`
  (alias `"mantle"`) works everywhere an `llm` string is accepted.
- Inherited `ask` / `ask_stream` / `invoke` / tool-calling work
  unmodified against Mantle's `/v1/chat/completions`.

### Non-Goals (explicitly out of scope)

- No SigV4 / aioboto3 code path — that is `BedrockConverseBase`
  (FEAT-302/315). Mantle authenticates with a plain bearer API key.
- No liteLLM dependency — the example in the request uses liteLLM only
  as external documentation of the endpoint; AI-Parrot goes through the
  `openai` SDK already wrapped by `OpenAIClient`.
- No Responses API (`client.responses.create`) support — `OpenAIClient`
  is built on chat completions; Mantle supports chat completions.
- No `BedrockMantleModel` enum / model catalog in v1 — the Mantle model
  list is fluid; model ids are passed as plain strings (see §8).
- No voice/image/video modalities — text-only (those stay in
  `NovaClient`).

---

## 2. Architectural Design

### Overview

`BedrockMantleClient` is a thin subclass of `OpenAIClient`, following
the `NvidiaClient` gateway pattern (`parrot/clients/nvidia.py:36-84`):
resolve credentials and endpoint in `__init__`, call
`super().__init__(api_key=..., base_url=..., **kwargs)`, re-set
`self.api_key` after `super().__init__()` (AbstractClient may overwrite
it), and inherit every behavior — `ask`, `ask_stream`, `invoke`,
`_chat_completion`, tool calling, structured output, retry, fallback.

Endpoint resolution (first match wins):
1. explicit `base_url` kwarg;
2. `BEDROCK_MANTLE_BASE_URL` conf var (new);
3. constructed: `https://bedrock-mantle.{region}.api.aws/v1`, where
   `region` = explicit `region` kwarg → `BEDROCK_AWS_REGION` →
   `AWS_REGION_NAME` → `"us-east-1"` (same order as
   `BedrockConverseBase`, `bedrock.py:186-192`).

API-key resolution (first match wins):
1. explicit `api_key` kwarg;
2. `BEDROCK_MANTLE_API_KEY` conf var (new);
3. `AWS_NOVA_API_KEY` conf var (existing Bedrock API key,
   `conf.py:492`).

Reference usage (target public behavior):

```python
from parrot.clients.nova import BedrockMantleClient

client = BedrockMantleClient(region="us-east-1")
async with client:
    response = await client.ask(
        "Explain quantum entanglement simply.",
        model="anthropic.claude-mythos-preview",
    )
```

And via factory string anywhere an `llm` spec is accepted:

```python
agent = Agent(llm="bedrock-mantle:openai.gpt-oss-120b")
```

### Component Diagram

```
AbstractClient (base.py)
      ▲
OpenAIClient (gpt.py) ── AsyncOpenAI SDK ──→ https://bedrock-mantle.<region>.api.aws/v1
      ▲
BedrockMantleClient (nova/mantle.py)
      ▲ registered via
LLMFactory ("bedrock-mantle" / "mantle", lazy loader in factory.py)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OpenAIClient` (`parrot/clients/gpt.py:79`) | extends | All completion/stream/tool/retry logic inherited |
| `LLMFactory` (`parrot/clients/factory.py`) | registers | New keys `"bedrock-mantle"`, `"mantle"` via lazy loader |
| `parrot.clients.nova` package | exports | `BedrockMantleClient` added to `__all__` |
| `parrot.conf` | reads | `BEDROCK_AWS_REGION`, `AWS_REGION_NAME`, `AWS_NOVA_API_KEY` + new `BEDROCK_MANTLE_API_KEY`, `BEDROCK_MANTLE_BASE_URL` |
| `BedrockConverseClient` / `NovaClient` | coexists | Distinct factory keys; no shared code path (Mantle is HTTP-bearer, not boto) |

### Data Models

No new Pydantic models. Responses are the inherited `AIMessage`
(`parrot.models.AIMessage`) produced by `OpenAIClient`.

### New Public Interfaces

```python
# parrot/clients/nova/mantle.py
class BedrockMantleClient(OpenAIClient):
    """Client for Amazon Bedrock Mantle's OpenAI-compatible API."""

    client_type: str = "bedrock-mantle"
    client_name: str = "bedrock-mantle"
    _default_model: str = "openai.gpt-oss-120b"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        region: Optional[str] = None,
        **kwargs,
    ): ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: BedrockMantleClient

- **Path**: `packages/ai-parrot/src/parrot/clients/nova/mantle.py`
- **Responsibility**: The client subclass — endpoint/region/API-key
  resolution per §2, class attributes (`client_type`, `client_name`,
  `_default_model`), docstrings. Also adds the two new conf vars to
  `packages/ai-parrot/src/parrot/conf.py` next to `AWS_NOVA_API_KEY`
  (line 492).
- **Depends on**: existing `OpenAIClient`, `parrot.conf`.

### Module 2: Package export + factory registration

- **Path**: `packages/ai-parrot/src/parrot/clients/nova/__init__.py`,
  `packages/ai-parrot/src/parrot/clients/factory.py`
- **Responsibility**: Export `BedrockMantleClient` from the nova
  subpackage; add `_lazy_bedrock_mantle()` loader and the
  `"bedrock-mantle"` / `"mantle"` keys to `SUPPORTED_CLIENTS`
  (following the `_lazy_nova` pattern, `factory.py`).
- **Depends on**: Module 1.

### Module 3: Tests + docs

- **Path**: `packages/ai-parrot/tests/clients/test_bedrock_mantle.py`
- **Responsibility**: Unit tests per §4 (no live AWS calls — mock
  `AsyncOpenAI`), plus a short usage section in `docs/`.
- **Depends on**: Modules 1–2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_default_base_url_from_region` | Module 1 | No kwargs → `https://bedrock-mantle.us-east-1.api.aws/v1` (with conf region unset) |
| `test_region_kwarg_builds_base_url` | Module 1 | `region="eu-west-1"` → `https://bedrock-mantle.eu-west-1.api.aws/v1` |
| `test_explicit_base_url_wins` | Module 1 | `base_url=` kwarg overrides region/conf construction |
| `test_api_key_resolution_order` | Module 1 | kwarg → `BEDROCK_MANTLE_API_KEY` → `AWS_NOVA_API_KEY`; survives `super().__init__` (re-set guard) |
| `test_default_model` | Module 1 | `_default_model == "openai.gpt-oss-120b"`; `client_type == "bedrock-mantle"` |
| `test_get_client_uses_base_url` | Module 1 | `get_client()` returns `AsyncOpenAI` configured with resolved key + base_url |
| `test_factory_creates_mantle_client` | Module 2 | `LLMFactory.create("bedrock-mantle:openai.gpt-oss-120b")` returns `BedrockMantleClient` with model set; `"mantle"` alias too |
| `test_ask_delegates_to_openai_machinery` | Module 3 | Mocked chat-completion round trip returns `AIMessage` (inherited path untouched) |

### Integration Tests

| Test | Description |
|---|---|
| `test_live_mantle_ask` | Optional, skipped unless a Bedrock API key is configured — one `ask()` round trip against the real endpoint |

### Test Data / Fixtures

```python
@pytest.fixture
def mantle_client(monkeypatch):
    # isolate from developer environment
    monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "ABSK-test-key")
    return BedrockMantleClient(region="us-east-1")
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `BedrockMantleClient` importable via
      `from parrot.clients.nova import BedrockMantleClient`.
- [ ] Constructing with no kwargs and only a Bedrock API key in conf
      yields base URL `https://bedrock-mantle.<resolved-region>.api.aws/v1`.
- [ ] Explicit `base_url` and `api_key` kwargs always win over conf.
- [ ] `LLMFactory.create("bedrock-mantle:<model>")` and
      `("mantle:<model>")` return a configured `BedrockMantleClient`.
- [ ] `ask` / `ask_stream` / `invoke` / tool-calling are inherited —
      no reimplementation of OpenAI machinery in the subclass.
- [ ] No `aioboto3` / botocore import anywhere in the new module.
- [ ] All unit tests pass:
      `pytest packages/ai-parrot/tests/clients/test_bedrock_mantle.py -v`.
- [ ] Full client test suite still green (no regression in
      `tests/clients/`).
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot.clients.gpt import OpenAIClient        # verified: packages/ai-parrot/src/parrot/clients/gpt.py:79
from parrot.clients.nova import NovaClient          # verified: packages/ai-parrot/src/parrot/clients/nova/__init__.py:8
from parrot.models import AIMessage                 # verified: used by clients/nvidia.py:23
from navconfig import config                        # verified: used by clients/gpt.py, clients/nvidia.py:15
from parrot.conf import AWS_NOVA_API_KEY            # verified: packages/ai-parrot/src/parrot/conf.py:492
from parrot.conf import BEDROCK_AWS_REGION          # verified: packages/ai-parrot/src/parrot/conf.py:488
from parrot.conf import AWS_REGION_NAME             # verified: packages/ai-parrot/src/parrot/conf.py:474
```

Inside `parrot/clients/nova/mantle.py` use relative imports, mirroring
`nvidia.py`: `from ..gpt import OpenAIClient` (one extra level up vs.
`nvidia.py` because the module sits inside the `nova/` subpackage).

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(AbstractClient):                                     # line 79
    client_type: str = "openai"                                         # line 82
    model: str = OpenAIModel.GPT5_MINI.value                            # line 83
    client_name: str = "openai"                                         # line 84
    _default_model: str = "gpt-5-mini"                                  # line 85
    _fallback_model: str = "gpt-5-nano"                                 # line 86

    def __init__(self, api_key: str = None,
                 base_url: str = "https://api.openai.com/v1", **kwargs):  # line 91
        # sets self.api_key (config OPENAI_API_KEY fallback), self.base_url,
        # self.base_headers (Bearer), then super().__init__(**kwargs)

    async def get_client(self) -> "AsyncOpenAI":                        # line 203
        # AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
        #             timeout=config.get("OPENAI_TIMEOUT", 60))
```

```python
# packages/ai-parrot/src/parrot/clients/nvidia.py  — THE reference pattern
class NvidiaClient(OpenAIClient):                                       # line 36
    client_type: str = "nvidia"                                         # line 70
    client_name: str = "nvidia"                                         # line 71

    def __init__(self, api_key: Optional[str] = None, **kwargs):        # line 74
        resolved_key = api_key or config.get("NVIDIA_API_KEY")
        super().__init__(api_key=resolved_key, base_url="https://...", **kwargs)
        # Re-set after super().__init__ because AbstractClient may
        # overwrite self.api_key (guard, line 84 — REQUIRED for Mantle too)
        self.api_key = resolved_key
```

```python
# packages/ai-parrot/src/parrot/clients/bedrock.py — region resolution order to mirror
self._region = (region or credentials.get('region_name')
                or BEDROCK_AWS_REGION or AWS_REGION_NAME or "us-east-1")  # lines 186-192
```

```python
# packages/ai-parrot/src/parrot/clients/factory.py — registration pattern
def _lazy_nova():                                                        # lazy-loader pattern to copy
    from .nova import NovaClient
    return NovaClient

SUPPORTED_CLIENTS = {
    "bedrock-converse": _lazy_bedrock_converse,
    "nova": _lazy_nova,
    "openai": OpenAIClient,
    ...
}
```

### Configuration References

```python
# packages/ai-parrot/src/parrot/conf.py
AWS_REGION_NAME = config.get("AWS_REGION_NAME", fallback=aws_region)      # line 474
BEDROCK_AWS_REGION = config.get("BEDROCK_AWS_REGION", fallback=None)      # line 488
AWS_NOVA_API_KEY = config.get("AWS_NOVA_API_KEY", fallback=None)          # line 492
# NEW (Module 1): BEDROCK_MANTLE_API_KEY, BEDROCK_MANTLE_BASE_URL — add near line 492
```

### External Endpoint Contract (user-provided, verified against liteLLM docs)

- Base URL shape: `https://bedrock-mantle.<region>.api.aws/v1`
  (us-east-1: `bedrock-mantle.us-east-1.api.aws`).
- Auth: Bedrock API key as OpenAI-style bearer (`OPENAI_API_KEY` slot).
- Model-id shape: `<vendor>.<model>` — e.g. `openai.gpt-oss-120b`,
  `anthropic.claude-mythos-preview`.
- Docs: https://docs.litellm.ai/docs/providers/bedrock_mantle ,
  https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BedrockMantleClient` | `OpenAIClient.__init__(api_key=, base_url=)` | `super().__init__` | `clients/gpt.py:91` |
| `BedrockMantleClient` | `OpenAIClient.get_client()` (inherited) | `self.base_url` / `self.api_key` | `clients/gpt.py:203-215` |
| `_lazy_bedrock_mantle` | `SUPPORTED_CLIENTS` dict | new keys | `clients/factory.py` |
| `nova/__init__.py` | `from .mantle import BedrockMantleClient` | export | `clients/nova/__init__.py:8-10` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.bedrock_mantle`~~ — nothing Mantle-related exists yet
  anywhere in the tree (no conf var, no module, no factory key).
- ~~`BEDROCK_MANTLE_API_KEY` / `BEDROCK_MANTLE_BASE_URL` in `parrot.conf`~~
  — do NOT import until Module 1 adds them.
- ~~`OpenAIClient.responses` / Responses-API path~~ — `OpenAIClient` is
  chat-completions based; there is no `responses.create` wrapper.
- ~~`BedrockMantleModel` enum in `parrot/models/`~~ — explicitly out of
  scope for v1 (§1 Non-Goals); model ids are plain strings.
- ~~`AWS_CREDENTIALS` profile lookup in this client~~ — that resolver
  belongs to `BedrockConverseBase` (boto path); Mantle uses only the
  bearer key + region conf vars listed above.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`NvidiaClient` is the template** (`clients/nvidia.py:36-84`): thin
  subclass, resolve key, call `super().__init__`, re-set `self.api_key`
  after `super().__init__` (AbstractClient overwrite guard — mirrors
  `openrouter.py:75` and `nvidia.py:84`).
- Lazy factory loader like `_lazy_nova` / `_lazy_bedrock_converse`,
  with a `# FEAT-407` comment on the new `SUPPORTED_CLIENTS` keys.
- Google-style docstrings + strict type hints; `self.logger` for
  logging; async-first — no blocking I/O.
- Module placement per user request: inside `clients/nova/` — note the
  relative import depth (`from ..gpt import OpenAIClient`).

### Known Risks / Gotchas

- **`parse()` shortcut may be rejected**: Nvidia NIM 5xx's on the
  OpenAI SDK's `chat.completions.parse()` path, which is why
  `NvidiaClient` overrides `_chat_completion` (`nvidia.py:124-173`).
  Whether Mantle accepts `parse()` is unknown — verify during
  implementation; if it fails, port the same minimal override
  (always `create()`), keeping retry via tenacity.
- **`base_headers` is rebuilt by `OpenAIClient.__init__`** from the
  `api_key` it received — pass the *resolved* key into
  `super().__init__` so the Bearer header is correct, then re-set
  `self.api_key`.
- **Model-id validation**: `OpenAIClient._normalize_model` warns on
  deprecated *OpenAI* model names; Mantle ids (`openai.gpt-oss-120b`)
  pass through untouched — no override needed, but confirm no false
  deprecation warnings fire.
- **Regional availability**: Mantle is not in every region; a wrong
  region yields DNS/connection errors, not auth errors. Docstring must
  state the region resolution order so misconfiguration is debuggable.
- **Key precedence with OPENAI_API_KEY**: `OpenAIClient.__init__` falls
  back to `config.get("OPENAI_API_KEY")` only when `api_key` is falsy —
  since the subclass resolves the key *before* calling super, a
  developer's real OpenAI key is never silently used against Mantle
  unless no Mantle/Nova key is configured at all. Test
  `test_api_key_resolution_order` must cover this.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `openai` | already an extra (`ai-parrot[openai]`) | Inherited `AsyncOpenAI` transport — no new dependency |

No new packages. No liteLLM, no aioboto3 in this module.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] Confirm `_default_model` choice — proposed `openai.gpt-oss-120b`
      (the model in the user-provided example). — *Owner: Jesus Lara*
- [ ] Does Mantle accept the OpenAI SDK `parse()` structured-output
      path, or does it need the `NvidiaClient`-style `_chat_completion`
      override? Decide empirically during Module 1. — *Owner: implementer*
- [ ] Should a `BedrockMantleModel` enum/catalog be added later once the
      Mantle model list stabilizes? Deferred out of v1 (§1 Non-Goals).
      — *Owner: Jesus Lara*
- [ ] `_fallback_model` for capacity errors — inherit OpenAI's
      `gpt-5-nano` is wrong for Mantle; likely set to a small Mantle
      model (e.g. a Nova or gpt-oss variant) or `None`. Decide during
      Module 1. — *Owner: implementer*

---

## Worktree Strategy

- **Isolation unit**: per-spec — but this is a small 3-module feature
  with strictly sequential dependencies (Module 1 → 2 → 3), so per
  CLAUDE.md ("When NOT to Use Worktrees") working directly on a
  `feat-407-bedrock-mantle-client` branch off `dev` is acceptable.
- **Parallelizable tasks**: none — each module depends on the previous.
- **Cross-feature dependencies**: none pending; builds only on merged
  FEAT-302/315 code already in `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-03 | Jesus Lara | Initial draft |
