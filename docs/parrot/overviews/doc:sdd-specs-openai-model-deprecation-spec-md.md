---
type: Wiki Overview
title: 'Feature Specification: OpenAI Model Deprecation Refresh'
id: doc:sdd-specs-openai-model-deprecation-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenAI has published a deprecation schedule with shutoff dates ranging from
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.clients.gpt
  rel: mentions
- concept: mod:parrot.handlers.chat
  rel: mentions
- concept: mod:parrot.handlers.llm
  rel: mentions
- concept: mod:parrot.loaders.abstract
  rel: mentions
- concept: mod:parrot.models.openai
  rel: mentions
- concept: mod:parrot.setup.providers.openai
  rel: mentions
---

# Feature Specification: OpenAI Model Deprecation Refresh

**Feature ID**: FEAT-138
**Date**: 2026-04-29
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

OpenAI has published a deprecation schedule with shutoff dates ranging from
2025-06 to 2026-10 covering a large slice of the model IDs currently exposed
by `parrot.models.openai.OpenAIModel`. At the same time the upstream catalog
at <https://developers.openai.com/api/docs/models/all> has added new families
(`gpt-5.5`, `gpt-5.3-chat-latest`, `gpt-5.3-codex`, `gpt-realtime*`,
`gpt-audio*`, `gpt-image-2`) that AI-Parrot does not yet surface.

Concretely, today the codebase still:

- Defaults `OpenAIClient.model` to `OpenAIModel.GPT4_TURBO` (alias for
  `gpt-4-turbo-2024-04-09`, shutoff **2026-10-23**).
- Hard-codes `"gpt-4-turbo"` in `parrot/handlers/chat.py` (3 sites) and
  `"gpt-3.5-turbo"` in `parrot/loaders/abstract.py:156` (both shutoff
  **2026-10-23**).
- Lists `gpt-image-1`, `gpt-5-chat-latest`, `gpt-4o-search-preview`,
  `gpt-4o-mini-search-preview`, `o3-mini`, `o3-deep-research`,
  `o4-mini-deep-research`, `o4-mini`, `gpt-3.5-turbo`, `gpt-4`,
  `gpt-4-turbo` in the public enum — all on the deprecation table.
- Has no programmatic way to detect that a user-supplied model string is
  deprecated, what its shutoff date is, or what the surviving alias is.

After the relevant cutoff each request to a deprecated ID will return a
hard error from OpenAI. We need to (a) refresh the enum against the
upstream catalog, (b) ship a structured deprecation registry, (c) emit a
one-shot `DeprecationWarning` whenever a deprecated ID is used, and
(d) migrate the three internal call sites that still hard-code
soon-to-be-dead model IDs.

### Goals

- Align `OpenAIModel` with the live upstream catalog (additions + removals).
- Encode the user-supplied deprecation table as a typed `DEPRECATIONS`
  registry with `shutoff`, `ft_shutoff`, and `alias` fields.
- Replace `gpt-4-turbo` and `gpt-3.5-turbo` defaults across the framework
  with `gpt-5-mini` (new client-wide default) and the new lightweight
  default for loaders.
- Emit a Python `DeprecationWarning` (deduplicated per process) the first
  time a deprecated model ID flows through `OpenAIClient`.
- Provide a small public API (`is_deprecated`, `get_shutoff_date`,
  `resolve_alias`) so other components and tests can react to deprecation
  state without re-parsing the dict.

### Non-Goals (explicitly out of scope)

- Embedding / TTS / Whisper / moderation enums — those live in
  `parrot/embeddings/openai.py` and other modules and are not part of
  `OpenAIModel`. Their deprecation review is a separate feature.
- Azure OpenAI deployment-name mapping. The handler still treats the same
  enum as the source of truth for `provider in {"openai", "azure"}` but no
  Azure-specific naming policy is introduced here.
- Fine-tuning lifecycle automation. The `ft_shutoff` field is recorded but
  no fine-tune migration tooling is built.
- Per-call "raise after shutoff date" enforcement. We warn only;
  enforcement was rejected in favour of a soft DeprecationWarning so the
  framework keeps working past the date if OpenAI extends models silently.

---

## 2. Architectural Design

### Overview

A two-layer change in `parrot/models/openai.py`:

1. **Catalog layer** — the `OpenAIModel(Enum)` enumeration is rewritten
   to mirror the upstream "current" list. Deprecated members are removed
   so consumers cannot accidentally type them via attribute access.
2. **Deprecation layer** — a sibling `DEPRECATIONS: dict[str, DeprecationInfo]`
   plus a small Pydantic model and three pure-function helpers
   (`is_deprecated`, `get_shutoff_date`, `resolve_alias`). The deprecation
   layer accepts *raw strings*, including dated source IDs that no longer
   appear in the enum, because users still pass them via config.

Runtime warning is emitted at one chokepoint: `OpenAIClient._normalize_model`
(new helper called from `__init__`, `ask`, `ask_stream`, `responses`,
`generate_image`). It calls `is_deprecated(model)`; if true it calls
`warnings.warn(..., DeprecationWarning, stacklevel=2)` *once per
(model, process)* via a module-level `_warned: set[str]` cache.

Consumer migration is mechanical: replace any `OpenAIModel.GPT4_TURBO`
default with `OpenAIModel.GPT5_MINI` and any string literal `"gpt-4-turbo"`
or `"gpt-3.5-turbo"` with `OpenAIModel.GPT5_MINI.value` (or the new
lightweight default for loaders).

### Component Diagram

```
parrot/models/openai.py
  ├── OpenAIModel (Enum)              ← refreshed catalog
  ├── DeprecationInfo (BaseModel)     ← shutoff, ft_shutoff, alias
  ├── DEPRECATIONS: dict[str, DeprecationInfo]
  ├── is_deprecated(model) -> bool
  ├── get_shutoff_date(model) -> date | None
  └── resolve_alias(model) -> str
            │
            ▼
parrot/clients/gpt.py
  └── OpenAIClient
        ├── model = "gpt-5-mini"        (was GPT4_TURBO)
        ├── _default_model = "gpt-5-mini"
        ├── _normalize_model(m)         ← NEW: emits DeprecationWarning
        ├── STRUCTURED_OUTPUT_COMPATIBLE_MODELS  ← refreshed
        └── RESPONSES_ONLY_MODELS                ← refreshed
            │
            ▼
parrot/handlers/{chat,llm}.py + parrot/loaders/abstract.py
  └── consumers updated to new defaults / partitioned listing
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.models.openai.OpenAIModel` | rewrite (members) | Drop deprecated, add upstream additions. |
| `parrot.clients.gpt.OpenAIClient` | edit (defaults + helper) | New `_normalize_model`; new `model` / `_default_model` defaults. |
| `parrot.handlers.chat` | edit (string literals) | 3 sites swap `"gpt-4-turbo"` → `OpenAIModel.GPT5_MINI.value`. |
| `parrot.handlers.llm.LLMClient._get_supported_models` | edit | Returns `{"active": [...], "deprecated": [...]}` so the public endpoint exposes both. |
| `parrot.loaders.abstract` | edit | `model_name` default `"gpt-3.5-turbo"` → `"gpt-4.1-mini"`. |
| `parrot.setup.providers.openai` | review only | Default `"gpt-4o"` is currently safe (not in deprecation table); keep. |
| `parrot.pageindex.{md_builder,utils}` | review only | `"gpt-4o"` token-counting only; safe. |

### Data Models

```python
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class DeprecationInfo(BaseModel):
    """Structured deprecation metadata for a single OpenAI model ID."""

    shutoff: date = Field(..., description="API shutoff date (UTC).")
    ft_shutoff: Optional[date] = Field(
        default=None,
        description="Fine-tuning shutoff date when distinct from API shutoff.",
    )
    alias: Optional[str] = Field(
        default=None,
        description="Public alias under which this dated model is sold "
                    "(e.g. 'gpt-4-turbo' for 'gpt-4-turbo-2024-04-09').",
    )
```

### New Public Interfaces

```python
# parrot/models/openai.py

DEPRECATIONS: dict[str, DeprecationInfo] = { ... }  # populated from spec table


def is_deprecated(model: str | OpenAIModel) -> bool:
    """Return True if `model` (or its alias target) appears in DEPRECATIONS."""


def get_shutoff_date(model: str | OpenAIModel) -> Optional[date]:
    """Return the API shutoff date for `model`, or None if not deprecated."""


def resolve_alias(model: str | OpenAIModel) -> str:
    """Normalize an alias string to its canonical (currently-recommended) ID
    when the alias points at a deprecated dated source. Pass-through for
    non-deprecated IDs."""
```

The new `OpenAIModel` enum members (refreshed catalog):

```python
class OpenAIModel(Enum):
    """Current OpenAI model catalog (deprecated IDs removed — see DEPRECATIONS)."""

    # gpt-5 family
    GPT5_5 = "gpt-5.5"
    GPT5_5_PRO = "gpt-5.5-pro"
    GPT5_4 = "gpt-5.4"
    GPT5_4_PRO = "gpt-5.4-pro"
    GPT5_4_MINI = "gpt-5.4-mini"
    GPT5_4_NANO = "gpt-5.4-nano"
    GPT5_3_CHAT = "gpt-5.3-chat-latest"
    GPT5_3_CODEX = "gpt-5.3-codex"
    GPT5_2_CHAT = "gpt-5.2-chat-latest"
    GPT5 = "gpt-5"
    GPT5_MINI = "gpt-5-mini"
    GPT5_NANO = "gpt-5-nano"

    # gpt-4 family (only what the upstream catalog lists as current)
    GPT4_1 = "gpt-4.1"
    GPT4_1_MINI = "gpt-4.1-mini"
    GPT4_1_NANO = "gpt-4.1-nano"
    GPT4O_MINI = "gpt-4o-mini"
    GPT4 = "gpt-4"

    # reasoning
    O3 = "o3"
    O3_PRO = "o3-pro"

    # realtime + audio
    GPT_REALTIME = "gpt-realtime"
    GPT_REALTIME_1_5 = "gpt-realtime-1.5"
    GPT_AUDIO = "gpt-audio"
    GPT_AUDIO_1_5 = "gpt-audio-1.5"

    # image
    GPT_IMAGE_2 = "gpt-image-2"
    GPT_IMAGE_1_5 = "gpt-image-1.5"
    GPT_IMAGE_1_MINI = "gpt-image-1-mini"
```

Deprecated IDs that previously existed as enum members (`GPT4_TURBO`,
`GPT3_5_TURBO`, `GPT_O4`, `GPT_4O`, `GPT_4O_SEARCH`, `GPT_4O_MINI_SEARCH`,
`O4_MINI`, `O4_MINI_DEEP_RESEARCH`, `O3_MINI`, `O3_DEEP_RESEARCH`,
`GPT5_CHAT`, `GPT_IMAGE_1`, `CHATGPT_IMAGE_LATEST`, `GPT5_PRO`, `GPT5_2`,
`GPT5_1`) are removed from the enum but still recognised by
`is_deprecated()` because they live in the `DEPRECATIONS` dict as raw
strings. Any code path that previously did `OpenAIModel.GPT4_TURBO.value`
must instead pass the literal string or move to `OpenAIModel.GPT5_MINI`.

---

## 3. Module Breakdown

### Module 1: Refreshed `OpenAIModel` enum + deprecation registry

- **Path**: `packages/ai-parrot/src/parrot/models/openai.py`
- **Responsibility**:
  - Replace the existing `Enum` body with the curated current catalog
    listed in §2.
  - Add `DeprecationInfo` Pydantic model.
  - Add `DEPRECATIONS` dict, populated verbatim from the user-provided
    table (every entry preserved including alias and `ft_shutoff`).
  - Add helper functions `is_deprecated`, `get_shutoff_date`, `resolve_alias`.
- **Depends on**: nothing (pure module rewrite).

### Module 2: Deprecation warning chokepoint in `OpenAIClient`

- **Path**: `packages/ai-parrot/src/parrot/clients/gpt.py`
- **Responsibility**:
  - Add `_warned: set[str]` module-level cache and `_normalize_model(model)`
    method that:
    1. Coerces `OpenAIModel | str` → `str`.
    2. If `is_deprecated(s)` and `s not in _warned`: emits
       `warnings.warn(f"OpenAI model '{s}' is deprecated; shutoff {date}. Migrate to '{resolve_alias(s)}'.", DeprecationWarning, stacklevel=3)`
       then adds `s` to `_warned`.
    3. Returns `s` unchanged (no auto-substitution — that is a follow-up).
  - Call `_normalize_model` from every public entry point that accepts a
    `model` parameter: `__init__` (when `model` kwarg is set), `ask`,
    `ask_stream`, `responses`, `generate_image`, `transcribe`, plus any
    method whose signature already takes `Union[str, OpenAIModel]`
    (lines 598, 1111, 1543, 1594, 1651, 1694, 1741, 1806).
- **Depends on**: Module 1.

### Module 3: Update `OpenAIClient` defaults

- **Path**: `packages/ai-parrot/src/parrot/clients/gpt.py`
- **Responsibility**:
  - `model: str = OpenAIModel.GPT5_MINI.value` (was `GPT4_TURBO`, line 94).
  - `_default_model: str = "gpt-5-mini"` (was `"gpt-4o-mini"`, line 96).
  - `_fallback_model: str = "gpt-4.1-nano"` (alias still active per upstream
    catalog — keep).
  - `_lightweight_model: str = "gpt-4.1"` (still active — keep).
  - Replace every `OpenAIModel.GPT4_TURBO` default in method signatures
    (lines 598, 1111, 1410, 1543, 1594, 1651, 1694, 1741) with
    `OpenAIModel.GPT5_MINI`. Line 1410's bare string `"gpt-4-turbo"`
    becomes `OpenAIModel.GPT5_MINI.value`.
  - Replace `OpenAIModel.GPT_O4` (`"gpt-4o-2024-08-06"`, deprecated path)
    in `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` with `OpenAIModel.GPT4O_MINI`.
- **Depends on**: Module 1.

### Module 4: Refresh `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` and `RESPONSES_ONLY_MODELS`

- **Path**: `packages/ai-parrot/src/parrot/clients/gpt.py` lines 56–87
- **Responsibility**:
  - `RESPONSES_ONLY_MODELS`: drop `"o3-mini"`, `"o3-deep-research"`,
    `"o4-mini"`, `"o4-mini-deep-research"`, `"gpt-5.4-pro"`, `"gpt-5-pro"`,
    `"gpt-5.2-pro"`, `"gpt-5-mini"`. Add `"o3"`, `"o3-pro"`, `"gpt-5.5-pro"`,
    `"gpt-5.4-pro"`. (Curate against current upstream Responses-API list;
    cross-reference at implementation time.)
  - `STRUCTURED_OUTPUT_COMPATIBLE_MODELS`: drop `GPT_O4`, `GPT_4O`,
    `GPT5_CHAT`, `GPT5_PRO`, `GPT5_2`, `GPT5_1`. Add `GPT5_5`, `GPT5_5_PRO`,
    `GPT5_3_CHAT`, `GPT5_2_CHAT`, `GPT4O_MINI`, `GPT4_1`, `GPT4_1_MINI`,
    `GPT4_1_NANO`, `GPT5`, `GPT5_MINI`, `GPT5_NANO`.
  - `DEFAULT_STRUCTURED_OUTPUT_MODEL = OpenAIModel.GPT5_MINI.value`.
  - The `GPT_4O_MINI_SEARCH` / `GPT_4O_SEARCH` references in the search
    branch (lines 729–730) and `_resolve_deep_research_model` (lines 256–264)
    must be rewritten to use raw deprecated strings via the
    `DEPRECATIONS` lookup *or* removed if the upstream catalog no longer
    exposes a search-preview / deep-research replacement (open question
    §8 Q1).
- **Depends on**: Module 1.

### Module 5: Migrate consumers with hard-coded deprecated strings

- **Path**: `packages/ai-parrot/src/parrot/handlers/chat.py`
  - Lines 245, 294, 357: replace `"gpt-4-turbo"` → `OpenAIModel.GPT5_MINI.value`
    (import added at top).
- **Path**: `packages/ai-parrot/src/parrot/loaders/abstract.py:156`
  - `model_name: str = "gpt-3.5-turbo"` → `"gpt-4.1-mini"` (cheap chat
    model still in current catalog; chosen over `gpt-5-mini` because
    abstract loaders use this only for token counting / titling and the
    cost delta matters at scale).
- **Depends on**: Module 1.

### Module 6: Partition `LLMClient._get_supported_models` listing

- **Path**: `packages/ai-parrot/src/parrot/handlers/llm.py:58–72`
- **Responsibility**:
  - Return a `dict[str, list[str]]` `{"active": [...], "deprecated": [...]}`
    for `provider in {"openai", "azure"}` instead of a flat list of
    `OpenAIModel` values.
  - `active` = enum members. `deprecated` = `list(DEPRECATIONS.keys())`.
  - Other providers (`groq`, `claude`, `google`) keep returning a flat list
    until their own deprecation work lands — the public endpoint shape
    becomes `Union[list[str], dict[str, list[str]]]` and must be
    documented in the docstring.
- **Depends on**: Module 1.

### Module 7: Tests

- **Path**: `packages/ai-parrot/tests/unit/models/test_openai_deprecations.py` (new)
- **Responsibility**: see §4.
- **Depends on**: Modules 1, 2, 3, 5, 6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_enum_contains_only_current_models` | 1 | Every `OpenAIModel` value is absent from `DEPRECATIONS`. |
| `test_enum_matches_upstream_catalog_snapshot` | 1 | Compare enum values to a fixture copied from <https://developers.openai.com/api/docs/models/all>; fail loudly if upstream drifts. |
| `test_deprecations_dict_shape` | 1 | Every `DEPRECATIONS` value is a `DeprecationInfo`; `shutoff` is a real `date`; aliases (where present) are also keys *or* enum members. |
| `test_is_deprecated_recognises_dated_id` | 1 | `is_deprecated("gpt-4-turbo-2024-04-09") is True`. |
| `test_is_deprecated_recognises_alias` | 1 | `is_deprecated("gpt-4-turbo") is True` because alias resolves to a deprecated dated source. |
| `test_is_deprecated_passes_current_id` | 1 | `is_deprecated("gpt-5-mini") is False`. |
| `test_get_shutoff_date_returns_iso_date` | 1 | `get_shutoff_date("gpt-3.5-turbo-0125") == date(2026, 10, 23)`. |
| `test_resolve_alias_returns_canonical_active` | 1 | `resolve_alias("gpt-4-turbo") == "gpt-5-mini"` (the new client-wide default — this is the suggested migration target, NOT the dated source). |
| `test_normalize_model_emits_warning_once` | 2 | Calling `client._normalize_model("gpt-4-turbo")` twice emits exactly one `DeprecationWarning`. |
| `test_normalize_model_silent_for_current_id` | 2 | Calling `client._normalize_model("gpt-5-mini")` emits zero warnings. |
| `test_openaiclient_default_is_gpt5_mini` | 3 | `OpenAIClient().model == "gpt-5-mini"`. |
| `test_chat_handler_default_model_is_gpt5_mini` | 5 | Construct the chat handler request payload and assert no occurrence of the literal `"gpt-4-turbo"`. |
| `test_loaders_abstract_default_model_name` | 5 | The default for the loader's token-counter is `"gpt-4.1-mini"`. |
| `test_llm_handler_lists_partitioned_models` | 6 | GET `/api/v1/ai/clients/models?client=openai` returns `{"active": [...], "deprecated": [...]}` and the deprecated list contains `"gpt-3.5-turbo"`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_openai_client_warns_on_deprecated_call` | Call `OpenAIClient(model="gpt-4-turbo").ask("hi")` against a stubbed transport; assert `pytest.warns(DeprecationWarning)`. |
| `test_no_internal_call_site_uses_deprecated_id` | Repo-grep: `rg -n "gpt-4-turbo|gpt-3.5-turbo|gpt-image-1\"|gpt-5-chat-latest"` under `packages/ai-parrot/src/parrot/` returns zero hits in non-`models/openai.py` files. |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/unit/models/conftest.py
import pytest
from parrot.models.openai import OpenAIModel, DEPRECATIONS


@pytest.fixture
def upstream_current_models() -> set[str]:
    """Snapshot of https://developers.openai.com/api/docs/models/all
    as fetched on 2026-04-29. Update when upstream changes."""
    return {
        "gpt-5.5", "gpt-5.5-pro", "gpt-5.4", "gpt-5.4-pro",
        "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5", "gpt-5-mini",
        "gpt-5-nano", "gpt-5.3-chat-latest", "gpt-5.2-chat-latest",
        "gpt-5.3-codex", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
        "gpt-4o-mini", "gpt-4", "o3", "o3-pro",
        "gpt-realtime", "gpt-realtime-1.5",
        "gpt-audio", "gpt-audio-1.5",
        "gpt-image-2", "gpt-image-1.5", "gpt-image-1-mini",
    }
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `OpenAIModel` enum members exactly equal the upstream "current"
      catalog snapshot (Module 1).
- [ ] `DEPRECATIONS` dict contains every entry from the user-provided
      table (50 entries) and every value is a valid `DeprecationInfo`.
- [ ] `is_deprecated`, `get_shutoff_date`, `resolve_alias` are exported
      from `parrot.models.openai` and accept both `str` and `OpenAIModel`.
- [ ] `OpenAIClient.model` defaults to `"gpt-5-mini"` and no method in
      `parrot/clients/gpt.py` defaults to `OpenAIModel.GPT4_TURBO`.
- [ ] `OpenAIClient._normalize_model("gpt-4-turbo")` emits exactly one
      `DeprecationWarning` per process per model.
- [ ] No file under `packages/ai-parrot/src/parrot/` (excluding
      `models/openai.py`) contains the string literal `"gpt-4-turbo"` or
      `"gpt-3.5-turbo"`.
- [ ] `LLMClient._get_supported_models("openai")` returns a partitioned
      `{"active": [...], "deprecated": [...]}` dict.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/models/ -v`.
- [ ] All integration tests pass: `pytest packages/ai-parrot/tests/integration/ -k openai -v`.
- [ ] No breaking changes to `OpenAIClient.ask`, `ask_stream`, `responses`
      public signatures (only default values change).
- [ ] CHANGELOG entry added describing the default-model bump and the new
      `DeprecationWarning` behaviour.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/models/openai.py:1
from enum import Enum

# verified: packages/ai-parrot/src/parrot/clients/gpt.py:38
from ..models.openai import OpenAIModel

# verified: packages/ai-parrot/src/parrot/handlers/llm.py:21
from parrot.models.openai import OpenAIModel
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/models/openai.py
class OpenAIModel(Enum):
    """Enum class for OpenAI models."""
    GPT5_4 = "gpt-5.4"             # line 6
    GPT5_4_PRO = "gpt-5.4-pro"     # line 7
    GPT5_4_MINI = "gpt-5.4-mini"   # line 8
    # ... (38-line file; full body read at sha-of-current-HEAD)
    GPT_IMAGE_1_MINI = "gpt-image-1-mini"  # line 38
```

```python
# packages/ai-parrot/src/parrot/clients/gpt.py
RESPONSES_ONLY_MODELS = {            # line 56
    "o3", "o3-pro", "o3-mini", "o3-deep-research",
    "o4-mini", "o4-mini-deep-research",
    "gpt-5.4-pro", "gpt-5-pro", "gpt-5.2-pro", "gpt-5-mini",
}

STRUCTURED_OUTPUT_COMPATIBLE_MODELS = {   # line 69 — references OpenAIModel members
    OpenAIModel.GPT_4O_MINI.value, OpenAIModel.GPT_O4.value,
    OpenAIModel.GPT_4O.value, OpenAIModel.GPT4_1.value,
    OpenAIModel.GPT_4_1_MINI.value, OpenAIModel.GPT_4_1_NANO.value,
    OpenAIModel.GPT5_4.value, OpenAIModel.GPT5_4_MINI.value,
    OpenAIModel.GPT5_4_NANO.value, OpenAIModel.GPT5_MINI.value,
    OpenAIModel.GPT5.value, OpenAIModel.GPT5_2.value,
    OpenAIModel.GPT5_1.value, OpenAIModel.GPT5_CHAT.value,
    OpenAIModel.GPT5_PRO.value,
}

DEFAULT_STRUCTURED_OUTPUT_MODEL = OpenAIModel.GPT_4O_MINI.value   # line 87


class OpenAIClient(AbstractClient):
    client_type: str = 'openai'                        # line 93
    model: str = OpenAIModel.GPT4_TURBO.value          # line 94  ← CHANGE TARGET
    client_name: str = 'openai'                        # line 95
    _default_model: str = 'gpt-4o-mini'                # line 96  ← CHANGE TARGET
    _fallback_model: str = 'gpt-4.1-nano'              # line 97  ← KEEP
    _lightweight_model: str = "gpt-4.1"                # line 98  ← KEEP

    def _is_capacity_error(self, error) -> bool: ...   # line 114
    async def get_client(self) -> AsyncOpenAI: ...     # line 126

    @staticmethod
    def _is_responses_only(model_str: str) -> bool: ...      # line 248
    @staticmethod
    def _resolve_deep_research_model(model_str) -> str: ...  # line 256

    # method-default sites that hard-code GPT4_TURBO:
    # line 598:  ask(..., model: Union[str, OpenAIModel] = OpenAIModel.GPT4_1, ...)
    # line 1111: responses(..., model: Union[str, OpenAIModel] = OpenAIModel.GPT4_TURBO, ...)
    # line 1410: <method>(..., model: str = "gpt-4-turbo", ...)
    # line 1543/1594/1651/1694/1741: same pattern, OpenAIModel.GPT4_TURBO
    # line 1806: <method>(..., model = OpenAIModel.GPT_4_1_MINI, ...)
```

```python
# packages/ai-parrot/src/parrot/handlers/llm.py
@is_authenticated()
@user_session()
class LLMClient(BaseView):
    _logger_name: str = "Parrot.LLMClient"             # line 53

    def _get_supported_models(self, provider: str) -> List[str]:   # line 58
        # uses OpenAIModel, GroqModel, ClaudeModel, GoogleModel as a flat list
```

```python
# packages/ai-parrot/src/parrot/handlers/chat.py
# line 245:  "model": "gpt-4-turbo",
# line 294:  model: "gpt-4-turbo"            (in a docstring/example)
# line 357:  model: "gpt-4-turbo"            (in a docstring/example)
```

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py:156
model_name: str = "gpt-3.5-turbo",
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `is_deprecated` | `OpenAIClient._normalize_model` | direct call | new code in `parrot/clients/gpt.py` |
| `DEPRECATIONS` | `LLMClient._get_supported_models` | `list(DEPRECATIONS.keys())` | `parrot/handlers/llm.py:58` |
| `OpenAIModel.GPT5_MINI` | `OpenAIClient.model` default | class attribute | `parrot/clients/gpt.py:94` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.models.openai.OpenAIModelRegistry`~~ — no registry class exists; we use a module-level dict.
- ~~`parrot.models.openai.OpenAIModel.GPT5_MINI`~~ — currently absent; will be **added** by Module 1.
- ~~`parrot.models.openai.OpenAIModel.GPT5_5`~~ — currently absent; will be **added** by Module 1.
- ~~`parrot.models.openai.OpenAIModel.GPT_REALTIME`~~ — currently absent; will be **added** by Module 1.
- ~~`parrot.clients.gpt.OpenAIClient._normalize_model`~~ — does not exist yet; introduced by Module 2.

…(truncated)…
