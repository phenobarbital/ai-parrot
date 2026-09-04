# TASK-2834: `MetaClient` core — Chat Completions path

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2833
**Assigned-to**: unassigned

---

## Context

Implements **Module 2**. Creates `MetaClient` as a subclass of
`OpenAIBaseClient` — the neutral OpenAI-wire layer from FEAT-438 that owns the
wire protocol and declares **zero** OpenAI-provider model defaults.

This task is deliberately small because almost everything is **inherited**.
`OpenAIBaseClient` already funnels `ask()`, `ask_stream()`, `resume()` and
`invoke()` through `_chat_completion()`, and its existing emissions were
verified live to be Meta-legal (`tool_choice="auto"`, `max_tokens`). Do not
re-implement any of that.

Follow `docs/clients/openai-compatible.md` § "Adding a New OpenAI-Compatible
Provider".

---

## Scope

- Create `parrot/clients/meta/client.py` with `class MetaClient(OpenAIBaseClient)`.
- Extend `parrot/clients/meta/__init__.py` (created by TASK-2833) to re-export
  `MetaClient` alongside `MetaModel`.
- Declare the FEAT-523 discovery class attributes `provider_keys` and `models`.
- Credential chain: `api_key` kwarg → `META_API_KEY` → `MODEL_API_KEY`.
- `base_url = "https://api.meta.ai/v1"`, `_default_model = muse-spark-1.3`,
  raised `_default_timeout`.
- `get_client()` returning `AsyncOpenAI`.
- `list_models()` over `GET /v1/models` using **aiohttp**.
- Accept a `use_responses: bool = True` kwarg and store it (TASK-2836 consumes
  it; here it is stored and otherwise inert).
- Unit tests.

**NOT in scope**: Responses API (TASK-2836), search grounding /
`count_input_tokens` (TASK-2837), factory registration (TASK-2835), any change
to `openai_base.py`, `base.py`, or `gpt.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/meta/client.py` | CREATE | `MetaClient` |
| `packages/ai-parrot/src/parrot/clients/meta/__init__.py` | MODIFY | add `MetaClient` re-export |
| `tests/clients/test_meta_client.py` | CREATE | Unit tests |

> **Codebase Contract correction (same as TASK-2833, re-verified
> 2026-09-04)**: test path corrected from
> `packages/ai-parrot/tests/clients/test_meta_client.py` to the root
> `tests/clients/test_meta_client.py` — `pyproject.toml` sets
> `testpaths = ["tests"]` and all sibling wire-client tests live there.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
from typing import Any, TYPE_CHECKING
from logging import getLogger

import aiohttp                                    # NEVER httpx / requests
from navconfig import config                      # credential resolution

from ..openai_base import OpenAIBaseClient       # openai_base.py:65 (note: ..)
from .models import MetaModel                    # created by TASK-2833

if TYPE_CHECKING:
    from openai import AsyncOpenAI
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                                  # :65
    tool_format: ToolFormat = ToolFormat.OPENAI                          # :76
    _default_timeout: float = 60.0                                       # :87
    def __init__(self, api_key: str|None = None,
                 base_url: str|None = None, **kwargs)                    # :89
        # sets self.api_key, self.base_url, self.base_headers,
        # self._timeout = kwargs.pop("timeout", self._default_timeout)
        # normalizes kwargs["model"] via _normalize_model, then super().__init__
    async def get_client(self) -> Any                                    # :120
    def _resolve_model(self, model: Any|None) -> str                     # :162
    def _is_responses_model(self, model_str: str) -> bool                # :181  (returns False)
    async def _chat_completion(self, model: str, messages: Any,
        use_tools: bool = False, stream: bool = False, **kwargs) -> Any  # :216
    async def ask(self, prompt, model=None, max_tokens=None, ...)        # :523
    async def ask_stream(...)                                            # :882
    async def invoke(...)                                                # :1153

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                            # :227
    client_type: str = "generic"                                         # class attr
    client_name: str = "generic"
    _lightweight_model: Optional[str] = None
    _fallback_model: Optional[str] = None
```

### THE PATTERN TO COPY — `OpenRouterClient` (verified 2026-09-04)
```python
# packages/ai-parrot/src/parrot/clients/openrouter.py
class OpenRouterClient(OpenAIBaseClient):
    client_type: str = "openrouter"
    client_name: str = "openrouter"
    _default_model: str = OpenRouterModel.DEEPSEEK_R1.value

    def __init__(self, api_key=None, ..., **kwargs):
        resolved_key = api_key or config.get('OPENROUTER_API_KEY')
        super().__init__(api_key=resolved_key,
                         base_url="https://openrouter.ai/api/v1", **kwargs)
        # Re-set after super().__init__ because AbstractClient may overwrite
        self.api_key = resolved_key

    async def get_client(self) -> "AsyncOpenAI":
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError("... Install with: pip install ai-parrot[openai]") from exc
        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
                           timeout=config.get('OPENAI_TIMEOUT', 60))

    async def list_models(self) -> List[Dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()
        return data.get("data", [])
```

### Live-verified endpoint contract
```
Base URL : https://api.meta.ai/v1     Auth: Authorization: Bearer <key>
GET  /v1/models            -> 200 {"data": [{"id": ..., "created": ...}, ...]}
POST /v1/chat/completions  -> 200 OpenAI-shaped `choices[]`
Unauthorized               -> 401 {"error":{"code","message","param","type"}}
```

### FEAT-523 discovery contract (MANDATORY — spec AC17)
```python
# Verified shape, sdd/specs/pep-420-llm-clients.spec.md:143-148
class MetaClient(OpenAIBaseClient):
    provider_keys: tuple[str, ...] = ("meta", "muse", "meta-muse")  # primary FIRST
    models: type[Enum] = MetaModel                                  # the catalogue
    # deprecated_models: Mapping[str, str] | None = None            # optional; omit
```
`provider_keys` must list **every** factory key the class answers to, primary
first — it is what FEAT-523's satellite entry points and the transitional
in-core registry are generated from. It must stay in sync with the keys
TASK-2835 registers in `SUPPORTED_CLIENTS`.

### Does NOT Exist
- ~~`parrot/clients/meta/client.py`~~ / ~~`MetaClient`~~ — you are creating them.
- ~~`from .openai_base import ...`~~ from inside `clients/meta/` — the client is
  now one level deeper, so it is `from ..openai_base import OpenAIBaseClient`.
  A single-dot import will fail.
- ~~`parrot/models/meta.py`~~ — provider enums left `parrot.models` (FEAT-523 v0.3).
- ~~`OpenAIBaseClient._responses_completion`~~, ~~`._prepare_responses_args`~~,
  ~~`._call_responses_create`~~ — **these are NOT on the base.** They live only
  on `OpenAIClient` (`gpt.py:353-680`). Do not call or import them.
- ~~`MODEL_API_KEY` in this environment~~ — it is **unset**. Only `META_API_KEY`
  is set. The `MODEL_API_KEY` link in the chain exists for upstream-example
  parity, not because it resolves here.
- ~~`httpx`~~ / ~~`requests`~~ — this repo uses `aiohttp` exclusively.
- ~~`parrot/` at the repo root~~ — source is `packages/ai-parrot/src/parrot/`.
- ~~Exporting `MetaClient` from `parrot/clients/__init__.py`~~ — **explicitly
  decided against** (spec §8, resolved). Do not add it there.

---

## Implementation Notes

### Key Constraints

1. **Credential chain, in this exact order**:
   ```python
   resolved_key = api_key or config.get('META_API_KEY') or config.get('MODEL_API_KEY')
   ```
   **MUST NOT** fall through to `OPENAI_API_KEY`. `AsyncOpenAI` reads that env
   var by default, so an unset key would silently ship an `sk-…` OpenAI key to
   Meta. Pass `api_key` explicitly to `AsyncOpenAI` — never rely on its default.
2. **Re-set `self.api_key` after `super().__init__()`** — `AbstractClient` only
   assigns it from kwargs when present, and may overwrite. Same as OpenRouter.
3. **`_default_model` MUST be `MetaModel.MUSE_SPARK_1_3.value`** — the Standard
   tier. **Never** a `-contributor` id: that tier grants Meta permission to
   train on prompts and completions.
4. **Never set `_default_model`/`_fallback_model`/`_lightweight_model` to a
   `gpt-*` id.** Leaving the latter two unset (inheriting `None`) is correct and
   is asserted by `tests/clients/test_openai_compatible_defaults.py`.
5. **Raise `_default_timeout` to `120.0`.** Muse Spark is a reasoning model and
   is measurably slow: 199 of 210 output tokens were reasoning for a one-word
   answer (spec §7 gotcha 1).
6. **Do NOT override `_chat_completion()`.** Meta needs no payload injection —
   the inherited funnel is already correct. An override here would be pure
   duplication.
7. Async throughout; `self.logger`, never `print`; Google-style docstrings.

---

## Acceptance Criteria

- [ ] `from parrot.clients.meta import MetaClient` works.
- [ ] `issubclass(MetaClient, OpenAIBaseClient)` and **not** a subclass of `OpenAIClient`.
- [ ] `MetaClient.client_type == MetaClient.client_name == "meta"`.
- [ ] `_default_model == "muse-spark-1.3"` and is NOT in `CONTRIBUTOR_MODELS`.
- [ ] `_default_timeout == 120.0`.
- [ ] No `gpt-*` id in `_default_model` / `_fallback_model` / `_lightweight_model`.
- [ ] Key chain prefers `META_API_KEY`, then `MODEL_API_KEY`.
- [ ] Key chain **never** reads `OPENAI_API_KEY` (explicit regression test).
- [ ] `base_url == "https://api.meta.ai/v1"`.
- [ ] `MetaClient` is NOT added to `parrot/clients/__init__.py`.
- [ ] **AC17 (layout)**: `parrot/clients/meta/` contains exactly `__init__.py`,
      `client.py`, `models.py`; `from parrot.clients.meta import MetaClient, MetaModel`
      works; `MetaClient.models is MetaModel`;
      `MetaClient.provider_keys == ("meta", "muse", "meta-muse")`; nothing named
      `meta` exists under `parrot/models/`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_meta_client.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/meta/client.py` clean.

---

## Test Specification

```python
import pytest
from parrot.clients.meta import MetaClient
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.clients.gpt import OpenAIClient
from parrot.clients.meta import CONTRIBUTOR_MODELS, MetaClient, MetaModel


class TestMetaClient:
    def test_subclasses_openai_base_not_openai_client(self):
        assert issubclass(MetaClient, OpenAIBaseClient)
        assert not issubclass(MetaClient, OpenAIClient)

    def test_default_model_is_standard_tier(self):
        assert MetaClient._default_model == "muse-spark-1.3"
        assert MetaClient._default_model not in CONTRIBUTOR_MODELS

    def test_no_gpt_leak_in_model_attrs(self):
        for attr in ("_default_model", "_fallback_model", "_lightweight_model"):
            val = getattr(MetaClient, attr, None)
            assert val is None or not str(val).startswith("gpt-")

    def test_feat523_discovery_attrs(self):
        assert MetaClient.provider_keys == ("meta", "muse", "meta-muse")
        assert MetaClient.models is MetaModel

    def test_package_layout_is_exactly_three_files(self):
        import parrot.clients.meta as pkg
        from pathlib import Path
        names = {p.name for p in Path(pkg.__file__).parent.glob("*.py")}
        assert names == {"__init__.py", "client.py", "models.py"}

    def test_base_url(self):
        assert MetaClient(api_key="k").base_url == "https://api.meta.ai/v1"

    def test_explicit_key_wins(self):
        assert MetaClient(api_key="explicit").api_key == "explicit"

    def test_prefers_meta_api_key(self, monkeypatch):
        monkeypatch.setattr("parrot.clients.meta.config.get",
                            lambda k, *a: {"META_API_KEY": "meta-key",
                                           "MODEL_API_KEY": "model-key"}.get(k))
        assert MetaClient().api_key == "meta-key"

    def test_never_falls_back_to_openai_api_key(self, monkeypatch):
        """Regression: an sk-… key must never be shipped to Meta."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-be-used")
        monkeypatch.setattr("parrot.clients.meta.config.get", lambda k, *a: None)
        assert MetaClient().api_key != "sk-should-never-be-used"
```

---

## Agent Instructions

1. Read the spec (§2 Overview, §6 Codebase Contract) and
   `docs/clients/openai-compatible.md`.
2. Confirm TASK-2833 is in `sdd/tasks/completed/`.
3. Verify the Codebase Contract before writing code.
4. Implement, test, verify acceptance criteria.
5. Move to `sdd/tasks/completed/`, set `done` in the index, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**: Created `MetaClient(OpenAIBaseClient)` in `clients/meta/client.py`.
Credential chain `api_key` → `META_API_KEY` → `MODEL_API_KEY`, never
`OPENAI_API_KEY` (regression-tested). `_default_model="muse-spark-1.3"`,
`_default_timeout=120.0`, `provider_keys=("meta","muse","meta-muse")`,
`models=MetaModel`. `__init__.py` re-exports `MetaClient` and `config` (the
latter so tests can `monkeypatch.setattr("parrot.clients.meta.config.get",
...)` per the sibling `test_moonshot_client.py` convention, extended one
level for the package layout). `_chat_completion` NOT overridden — fully
inherited. 15/15 unit tests pass, `ruff` clean.
**Deviations from spec**: none beyond the test-path correction already
noted in TASK-2833 (root `tests/clients/`, not
`packages/ai-parrot/tests/clients/`).
