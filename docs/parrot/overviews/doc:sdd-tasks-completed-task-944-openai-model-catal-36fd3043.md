---
type: Wiki Overview
title: 'TASK-944: Refresh OpenAIModel enum + add DEPRECATIONS registry and helpers'
id: doc:sdd-tasks-completed-task-944-openai-model-catalog-and-deprecations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational task for FEAT-138. It rewrites
relates_to:
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.models.openai
  rel: mentions
---

# TASK-944: Refresh OpenAIModel enum + add DEPRECATIONS registry and helpers

**Feature**: FEAT-138 — OpenAI Model Deprecation Refresh
**Spec**: `sdd/specs/openai-model-deprecation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-138. It rewrites
`packages/ai-parrot/src/parrot/models/openai.py` to:

1. Mirror the upstream "current" catalog snapshot fetched on 2026-04-29
   from <https://developers.openai.com/api/docs/models/all>.
2. Add a typed deprecation registry encoding the table the user provided
   in the original feature request (50 entries, dates 2024-09-13 →
   2026-10-23, including `shutoff`, `ft_shutoff`, and `alias`).
3. Expose three helper functions so other modules can reason about
   deprecation state without re-parsing the dict.

Implements §2 "Architectural Design" and Module 1 of §3.

---

## Scope

- Rewrite `OpenAIModel(Enum)` with the exact member set listed in the
  spec §2 (26 members across `gpt-5*`, `gpt-4*`, `o3*`, realtime, audio,
  image families).
- Add `DeprecationInfo(BaseModel)` with `shutoff: date`, `ft_shutoff:
  Optional[date]`, `alias: Optional[str]`.
- Add `DEPRECATIONS: dict[str, DeprecationInfo]` populated **verbatim**
  from the table in the original `/sdd-spec` invocation (50 entries).
  Use `date(YYYY, MM, DD)` literals — not strings.
- Add three helper functions:
  - `is_deprecated(model: str | OpenAIModel) -> bool`
  - `get_shutoff_date(model: str | OpenAIModel) -> Optional[date]`
  - `resolve_alias(model: str | OpenAIModel) -> str`
- Add `__all__` listing the public exports.

**NOT in scope**:
- Touching `parrot/clients/gpt.py` (TASK-945 / TASK-946).
- Touching `parrot/handlers/{chat,llm}.py` or `parrot/loaders/abstract.py`
  (TASK-947 / TASK-948).
- Writing the test file (TASK-949).
- Removing/renaming any consumers of dropped enum members — those tasks
  rely on this one being merged first.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/openai.py` | REWRITE | Full module rewrite per spec §2 + §3 Module 1. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/models/openai.py:1
from enum import Enum

# pydantic is already a project dependency — used throughout parrot/models/
# verified: e.g. packages/ai-parrot/src/parrot/models/responses.py imports BaseModel
from pydantic import BaseModel, Field
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/openai.py — current full body
# (38 lines, will be entirely replaced):
from enum import Enum


class OpenAIModel(Enum):
    """Enum class for OpenAI models."""
    GPT5_4 = "gpt-5.4"
    GPT5_4_PRO = "gpt-5.4-pro"
    # ... 36 lines total ending at:
    GPT_IMAGE_1_MINI = "gpt-image-1-mini"
```

### Target Catalog (copy verbatim into the new enum)

The new `OpenAIModel` body must equal:

```python
class OpenAIModel(Enum):
    """Current OpenAI model catalog (deprecated IDs removed — see DEPRECATIONS)."""

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
    GPT4_1 = "gpt-4.1"
    GPT4_1_MINI = "gpt-4.1-mini"
    GPT4_1_NANO = "gpt-4.1-nano"
    GPT4O_MINI = "gpt-4o-mini"
    GPT4 = "gpt-4"
    O3 = "o3"
    O3_PRO = "o3-pro"
    GPT_REALTIME = "gpt-realtime"
    GPT_REALTIME_1_5 = "gpt-realtime-1.5"
    GPT_AUDIO = "gpt-audio"
    GPT_AUDIO_1_5 = "gpt-audio-1.5"
    GPT_IMAGE_2 = "gpt-image-2"
    GPT_IMAGE_1_5 = "gpt-image-1.5"
    GPT_IMAGE_1_MINI = "gpt-image-1-mini"
```

### Target DEPRECATIONS Table (copy verbatim from the spec)

The dict MUST contain exactly these 50 keys (full table from the original
spec request — reproduced here as the authoritative reference). Use
`datetime.date(YYYY, MM, DD)` literals:

```
gpt-3.5-turbo-0125                       shutoff 2026-10-23  ft_shutoff 2026-10-23
gpt-4-0613                               shutoff 2026-10-23  ft_shutoff 2026-10-23
gpt-4-1106-preview                       shutoff 2026-10-23  ft_shutoff 2026-10-23
gpt-4-turbo-2024-04-09                   shutoff 2026-10-23  alias=gpt-4-turbo
gpt-4.1-nano-2025-04-14                  shutoff 2026-10-23  ft_shutoff 2026-10-23  alias=gpt-4.1-nano
gpt-4o-2024-05-13                        shutoff 2026-10-23
gpt-image-1                              shutoff 2026-10-23
o1-2024-12-17                            shutoff 2026-10-23
o1-pro-2025-03-19                        shutoff 2026-10-23
o3-mini-2025-01-31                       shutoff 2026-10-23
o4-mini-2025-04-16                       shutoff 2026-10-23  ft_shutoff 2026-10-23
gpt-3.5-turbo-instruct                   shutoff 2026-09-28
babbage-002                              shutoff 2026-09-28  ft_shutoff 2026-10-23
davinci-002                              shutoff 2026-09-28  ft_shutoff 2026-10-23
gpt-3.5-turbo-1106                       shutoff 2026-09-28  ft_shutoff 2026-10-23
computer-use-preview-2025-03-11          shutoff 2026-07-23
gpt-4o-audio-preview-2024-12-17          shutoff 2026-07-23
gpt-4o-mini-audio-preview-2024-12-17     shutoff 2026-07-23
gpt-4o-mini-realtime-preview-2024-12-17  shutoff 2026-07-23
gpt-4o-mini-search-preview-2025-03-11    shutoff 2026-07-23
gpt-4o-mini-tts-2025-03-20               shutoff 2026-07-23
gpt-4o-search-preview-2025-03-11         shutoff 2026-07-23
gpt-5-chat-latest                        shutoff 2026-07-23
gpt-5-codex                              shutoff 2026-07-23
gpt-5.1-chat-latest                      shutoff 2026-07-23
gpt-5.1-codex                            shutoff 2026-07-23
gpt-5.1-codex-max                        shutoff 2026-07-23
gpt-5.1-codex-mini                       shutoff 2026-07-23
gpt-5.2-codex                            shutoff 2026-07-23
gpt-audio-mini-2025-10-06                shutoff 2026-07-23
gpt-realtime-mini-2025-10-06             shutoff 2026-07-23
o3-deep-research-2025-06-26              shutoff 2026-07-23
o4-mini-deep-research-2025-06-26         shutoff 2026-07-23
gpt-4-0314                               shutoff 2026-03-26
gpt-4-0125-preview                       shutoff 2026-03-26  alias=gpt-4-turbo-preview
gpt-4o-audio-preview-2025-06-03          shutoff 2026-03-24
gpt-4o-mini-audio-preview                shutoff 2026-03-24
chatgpt-4o-latest                        shutoff 2026-02-17
codex-mini-latest                        shutoff 2026-01-16
o1-mini-2024-09-12                       shutoff 2025-10-27  alias=o1-mini
gpt-4o-audio-preview-2024-10-01          shutoff 2025-10-10
o1-preview-2024-09-12                    shutoff 2025-07-28  alias=o1-preview
gpt-4.5-preview                          shutoff 2025-07-14
gpt-4-32k-0613                           shutoff 2025-06-06  alias=gpt-4-32k
gpt-4-32k-0314                           shutoff 2025-06-06
gpt-4-1106-vision-preview                shutoff 2024-12-06  alias=gpt-4-vision-preview
gpt-3.5-turbo-0613                       shutoff 2024-09-13  ft_shutoff 2026-10-23
gpt-3.5-turbo-16k-0613                   shutoff 2024-09-13  ft_shutoff 2026-10-23
gpt-3.5-turbo-0301                       shutoff 2024-09-13
```

### Helper Function Semantics

```python
def is_deprecated(model: str | OpenAIModel) -> bool:
    """Return True if `model` is a key in DEPRECATIONS, OR if `model`
    matches the `alias` of any DEPRECATIONS entry.

    Examples:
        is_deprecated("gpt-4-turbo-2024-04-09") -> True   # direct key
        is_deprecated("gpt-4-turbo")            -> True   # alias of above
        is_deprecated("gpt-5-mini")             -> False
        is_deprecated(OpenAIModel.GPT5_MINI)    -> False
    """


def get_shutoff_date(model: str | OpenAIModel) -> Optional[date]:
    """Return DEPRECATIONS[key].shutoff, where `key` is either the model
    string itself or the canonical key whose `alias` matches `model`.
    Return None if `model` is not deprecated."""


def resolve_alias(model: str | OpenAIModel) -> str:
    """Per spec §8 Q3 — pending user decision. For this task default to
    interpretation (b): map deprecated IDs to the new client-wide
    migration target `gpt-5-mini`. Pass-through for non-deprecated IDs.

    Implementers: leave a TODO comment noting Q3 is open and that the
    return-value contract may change once the question is answered."""
```

### Does NOT Exist

- ~~`parrot.models.openai.OpenAIModelRegistry`~~ — no registry class; use a module-level dict.
- ~~`pydantic.dataclasses.DeprecationInfo`~~ — use `pydantic.BaseModel`, not the dataclass variant.
- ~~`OpenAIModel.GPT_4O_MINI`~~ — note: previous codebase used `GPT_4O_MINI` (with underscore-O). New name is `GPT4O_MINI` (no underscore between 4 and O). This is a deliberate naming-convention cleanup.
- ~~`OpenAIModel.GPT_4O`~~ — `gpt-4o` (the bare alias) is no longer in the upstream catalog snapshot; do NOT add it back. Keep `GPT4O_MINI` only.
- ~~`OpenAIModel.GPT_O4`~~ — old name for `gpt-4o-2024-08-06`; no replacement member.
- ~~`from datetime import datetime, date as _date`~~ — just `from datetime import date`.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/models/openai.py
from datetime import date
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


class OpenAIModel(Enum):
    """Current OpenAI model catalog (deprecated IDs removed — see DEPRECATIONS)."""
    # ... members from §2 of the spec


class DeprecationInfo(BaseModel):
    """Structured deprecation metadata for a single OpenAI model ID."""

    shutoff: date = Field(..., description="API shutoff date (UTC).")
    ft_shutoff: Optional[date] = Field(default=None)
    alias: Optional[str] = Field(default=None)


DEPRECATIONS: dict[str, DeprecationInfo] = {
    "gpt-3.5-turbo-0125": DeprecationInfo(
        shutoff=date(2026, 10, 23), ft_shutoff=date(2026, 10, 23)
    ),
    "gpt-4-turbo-2024-04-09": DeprecationInfo(
        shutoff=date(2026, 10, 23), alias="gpt-4-turbo"
    ),
    # ... 48 more entries
}


def _coerce(model: Union[str, OpenAIModel]) -> str:
    return model.value if isinstance(model, OpenAIModel) else model


def is_deprecated(model: Union[str, OpenAIModel]) -> bool:
    s = _coerce(model)
    if s in DEPRECATIONS:
        return True
    return any(info.alias == s for info in DEPRECATIONS.values())


def get_shutoff_date(model: Union[str, OpenAIModel]) -> Optional[date]:
    s = _coerce(model)
    if s in DEPRECATIONS:
        return DEPRECATIONS[s].shutoff
    for info in DEPRECATIONS.values():
        if info.alias == s:
            return info.shutoff
    return None


_MIGRATION_TARGET = "gpt-5-mini"  # spec §8 Q3 — currently using interpretation (b)


def resolve_alias(model: Union[str, OpenAIModel]) -> str:
    """TODO(spec §8 Q3): contract may switch to canonical-alias semantics."""
    s = _coerce(model)
    if is_deprecated(s):
        return _MIGRATION_TARGET
    return s


__all__ = [
    "OpenAIModel",
    "DeprecationInfo",
    "DEPRECATIONS",
    "is_deprecated",
    "get_shutoff_date",
    "resolve_alias",
]
```

### Key Constraints

- Use `Union[str, OpenAIModel]` for parameter typing — repo-wide style is
  pre-3.10-compatible (search `grep -r "Union\[" packages/ai-parrot/src/parrot/models/`
  to confirm).
- `DeprecationInfo` is a Pydantic model, not a dataclass — consistent with
  the rest of `parrot/models/`.
- No I/O. No async. Pure data + pure functions.
- Do NOT import from `parrot.clients.*` here — `clients/gpt.py` will
  import FROM this module, not the other way around.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/openai.py` — current 38-line file (will be replaced).
- `packages/ai-parrot/src/parrot/models/responses.py` — example of Pydantic `BaseModel` usage in this directory.
- `packages/ai-parrot/src/parrot/clients/gpt.py:38` — current consumer (will be edited in TASK-945/915).

---

## Acceptance Criteria

- [ ] `OpenAIModel` has exactly 26 members matching the §2 catalog.
- [ ] No member of the new enum has a value that appears as a key OR an
      `alias` in `DEPRECATIONS`.
- [ ] `DEPRECATIONS` has exactly 50 entries; each entry is a
      `DeprecationInfo` instance.
- [ ] `is_deprecated("gpt-4-turbo-2024-04-09")` returns `True`.
- [ ] `is_deprecated("gpt-4-turbo")` returns `True` (alias path).
- [ ] `is_deprecated("gpt-5-mini")` returns `False`.
- [ ] `get_shutoff_date("gpt-3.5-turbo-0125")` returns `date(2026, 10, 23)`.
- [ ] `resolve_alias("gpt-4-turbo")` returns `"gpt-5-mini"` (interpretation (b); TODO note present in source).
- [ ] `__all__` lists exactly: `OpenAIModel`, `DeprecationInfo`, `DEPRECATIONS`, `is_deprecated`, `get_shutoff_date`, `resolve_alias`.
- [ ] Module imports cleanly: `python -c "import parrot.models.openai"`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/openai.py`.

---

## Test Specification

Tests are out of scope for this task and will be added by TASK-949.
However, the implementing agent SHOULD do a quick smoke check via the
Python REPL to confirm imports + helper return values before marking
the task done.

```bash
source .venv/bin/activate
python -c "
from parrot.models.openai import (
    OpenAIModel, DEPRECATIONS, is_deprecated, get_shutoff_date, resolve_alias
)
assert len(list(OpenAIModel)) == 26, len(list(OpenAIModel))
assert len(DEPRECATIONS) == 50, len(DEPRECATIONS)
assert is_deprecated('gpt-4-turbo')
assert not is_deprecated('gpt-5-mini')
print('OK')
"
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/openai-model-deprecation.spec.md` for full context.
2. No `Depends-on` entries — start immediately.
3. Verify the codebase contract by reading the current
   `packages/ai-parrot/src/parrot/models/openai.py` (38 lines) and
   confirming its members.
4. Update `sdd/tasks/.index.json` → `"in-progress"` with your session ID.
5. Implement the rewrite in a single commit.
6. Run the smoke check from the Test Specification.
7. Move this file to `sdd/tasks/completed/`, update the index → `"done"`.
8. Fill in the Completion Note below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
