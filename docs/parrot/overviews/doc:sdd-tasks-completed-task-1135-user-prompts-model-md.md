---
type: Wiki Overview
title: 'TASK-1135: Create the `UserPrompts` Python model'
id: doc:sdd-tasks-completed-task-1135-user-prompts-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module B1. The codebase needs a per-user prompt store so users
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.models
  rel: mentions
- concept: mod:parrot.handlers.models.bots
  rel: mentions
---

# TASK-1135: Create the `UserPrompts` Python model

**Feature**: FEAT-167 — Prompt Library: agent_id support + new UserPrompts model
**Spec**: `sdd/specs/promptlibrary-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module B1. The codebase needs a per-user prompt store so users
can save their own prompts against either a DB-backed chatbot (UUID) or
a code/registry agent (slug). The model mirrors `UserBotModel`'s
sibling-pattern: composite PK `(user_id, prompt_id)`, FK to
`auth.users(user_id) ON DELETE CASCADE`, separate `.sql` DDL file
(TASK-1136). Fields parity with `PromptLibrary` (category + tags) plus
a reserved `is_public BOOLEAN DEFAULT FALSE` for a future public-promotion
workflow.

---

## Scope

- Create new file
  `packages/ai-parrot/src/parrot/handlers/models/users_prompts.py`
  containing the `UserPrompts(Model)` class as specified.
- Export `UserPrompts` from
  `packages/ai-parrot/src/parrot/handlers/models/__init__.py`.
- `chatbot_id` is typed as **`str`** (free-form VARCHAR) so it can store
  UUIDs or registry slugs.
- Reuse the existing `PromptCategory` enum
  (`models/bots.py:543-556`) for the default `prompt_category` value.

**NOT in scope**:
- DDL file (TASK-1136).
- Handler / route (TASK-1137).
- Tests (TASK-1138).
- Any change to `PromptLibrary` (TASK-1133/1134).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/models/users_prompts.py` | CREATE | Define `UserPrompts(Model)`. |
| `packages/ai-parrot/src/parrot/handlers/models/__init__.py` | MODIFY | Re-export `UserPrompts`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# These imports compile cleanly and are mirrored from users_bots.py.
from __future__ import annotations          # mirror users_bots.py:12
import uuid                                 # mirror users_bots.py:14
from datetime import datetime               # mirror users_bots.py:15
from typing import List, Optional           # subset of users_bots.py:16
from datamodel import Field                 # verified: users_bots.py:18
from asyncdb.models import Model            # verified: users_bots.py:19
from parrot.conf import PARROT_SCHEMA       # verified: parrot/conf.py:82, used at users_bots.py:21
from .bots import PromptCategory            # verified export: models/__init__.py:9
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/models/users_bots.py (sibling pattern)
class UserBotModel(Model):                                              # line 26
    chatbot_id: uuid.UUID = Field(primary_key=True, required=False,
                                  default_factory=uuid.uuid4)           # line 35
    user_id: int = Field(primary_key=True, required=True)               # line 40
    # ... other fields ...
    class Meta:                                                         # line 112
        driver = "pg"
        name = "users_bots"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False
```

```python
# packages/ai-parrot/src/parrot/handlers/models/bots.py
class PromptCategory(Enum):                                             # line 543
    TECH = "tech"; TECH_OR_EXPLAIN = "tech-or-explain"; IDEA = "idea"
    EXPLAIN = "explain"; ACTION = "action"; COMMAND = "command"; OTHER = "other"
```

```python
# packages/ai-parrot/src/parrot/handlers/models/__init__.py
from .bots import (
    BotModel, ChatbotUsage, ChatbotFeedback, FeedbackType,
    PromptLibrary, PromptCategory, create_bot,
)                                                                       # lines 3-11
from .users_bots import UserBotModel                                    # line 12
__all__ = [..., "UserBotModel", ...]                                    # lines 19-34
```

### Does NOT Exist
- ~~`parrot.handlers.models.UserPrompts`~~ — does NOT exist; this task
  creates it.
- ~~`UserPrompts.from_public(prompt_library_row)`~~ — no factory exists
  or is required.
- ~~`UserPrompts.set_chatbot_id()` accessor~~ — not required; `chatbot_id`
  is a plain `str` Field.
- ~~`asyncdb.models.UserModel`~~ — there is no such base; inherit from
  `asyncdb.models.Model`.
- ~~`navigator.auth.User` import~~ — the FK to `auth.users` is a
  DB-level reference; do NOT import a Python user model.

---

## Implementation Notes

### Pattern to Follow

```python
"""Database model for per-user prompts (``navigator.users_prompts``).

Mirrors :class:`parrot.handlers.models.bots.PromptLibrary` but is keyed
by ``(user_id, prompt_id)`` so each user owns their own private prompt
collection. ``chatbot_id`` is typed as a plain string so it can hold
either a DB-backed chatbot UUID (stringified) or a registry agent slug
(e.g. ``"web_search_agent"``).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from datamodel import Field
from asyncdb.models import Model

from parrot.conf import PARROT_SCHEMA
from .bots import PromptCategory


class UserPrompts(Model):
    """Per-user prompt definition.

    All fields mirror :class:`PromptLibrary` semantics where applicable,
    plus ``user_id`` and the future-promotion flag ``is_public``.
    """

    # Composite identity
    prompt_id: uuid.UUID = Field(
        primary_key=True,
        required=False,
        default_factory=uuid.uuid4,
    )
    user_id: int = Field(primary_key=True, required=True)

    # Bot / agent binding — VARCHAR so both UUIDs and agent slugs fit.
    chatbot_id: str = Field(required=True)

    # Prompt body
    title: str = Field(required=True)
    query: str = Field(required=True)
    description: Optional[str] = Field(required=False, default=None)
    prompt_category: str = Field(
        required=False,
        default=PromptCategory.OTHER,
    )
    prompt_tags: List[str] = Field(required=False, default_factory=list)

    # Reserved for future "promote to public" workflow
    is_public: bool = Field(required=False, default=False)

    # Metadata
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int] = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        driver = "pg"
        name = "users_prompts"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False
```

### `__init__.py` update

Append `UserPrompts` to both the import block and `__all__`:
```python
from .users_prompts import UserPrompts        # NEW
# ...
__all__ = [
    ...,
    "UserBotModel",
    "UserPrompts",                             # NEW
    ...,
]
```

### Key Constraints

- `chatbot_id` is `str`, not `uuid.UUID`. Do NOT relax this back to UUID.
- `is_public` defaults to `False`.
- Reuse `PromptCategory` — do NOT redefine it.
- Use `PARROT_SCHEMA` (not the literal `"navigator"`) so the dev/staging
  schema toggle works.
- Use `from __future__ import annotations` at the top so the
  `Optional[...]` syntax compiles under older Pythons.

### References in Codebase
- `models/users_bots.py:26-117` — sibling-pattern template.
- `models/bots.py:543-598` — `PromptCategory` + `PromptLibrary` for
  cross-reference on field semantics.
- `models/__init__.py` — exports surface.

---

## Acceptance Criteria

- [ ] File `packages/ai-parrot/src/parrot/handlers/models/users_prompts.py`
  exists and defines `UserPrompts(Model)` per the pattern above.
- [ ] `from parrot.handlers.models import UserPrompts` works.
- [ ] `UserPrompts.Meta.name == "users_prompts"` and `Meta.schema ==
  PARROT_SCHEMA`.
- [ ] `chatbot_id` is annotated as `str`.
- [ ] `is_public` is annotated as `bool` with default `False`.
- [ ] `models/__init__.py` lists `UserPrompts` in `__all__`.
- [ ] `ruff check packages/ai-parrot/src/parrot/handlers/models/` — no new errors.
- [ ] `python -c "from parrot.handlers.models import UserPrompts; UserPrompts(user_id=1, chatbot_id='web_search_agent', title='t', query='q')"`
  succeeds.

---

## Test Specification

> Tests for the model + handler land in TASK-1138.

---

## Agent Instructions

1. Read spec §2 (Data Models) and §6 (Codebase Contract).
2. Read `models/users_bots.py` end-to-end as the canonical reference.
3. Create `users_prompts.py`. Mirror the structure shown above; do not
   add encrypted-field accessors (this model has no encrypted columns).
4. Update `models/__init__.py` to re-export `UserPrompts`.
5. Run a Python import smoke test (see Acceptance Criteria).
6. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-13
**Notes**: Created `users_prompts.py` with `UserPrompts(Model)` class. `chatbot_id` is `str`, `is_public` is `bool` defaulting to `False`, `PARROT_SCHEMA` used for schema. Exported from `models/__init__.py`. All annotations verified.

**Deviations from spec**: none
