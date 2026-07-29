---
type: Wiki Overview
title: 'Feature Specification: Prompt Library — `agent_id` support + new `UserPrompts`
  model'
id: doc:sdd-specs-promptlibrary-changes-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The current `PromptLibrary` model at
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.bots
  rel: mentions
- concept: mod:parrot.handlers.models
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Prompt Library — `agent_id` support + new `UserPrompts` model

**Feature ID**: FEAT-167
**Date**: 2026-05-13
**Author**: Jesus Lara
**Status**: draft
**Target version**: TBD

> **Source proposal**: [`sdd/proposals/promptlibrary-changes.proposal.md`](../proposals/promptlibrary-changes.proposal.md)
> **Research audit**: [`sdd/state/FEAT-167/`](../state/FEAT-167/)
> **Confidence (from proposal)**: high

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `PromptLibrary` model at
`packages/ai-parrot/src/parrot/handlers/models/bots.py:558-598` only covers
**public** prompts that are bound to a chatbot via a strict UUID
`chatbot_id`. Two real-world use-cases break against this contract:

1. **Registry/code-defined agents have no UUID.** Agents declared via
   `@register_agent` (or coded as `Agent` subclasses) carry a string
   `agent_id` (verified at `bots/agent.py:54,83`, `bots/search.py:69`,
   `bots/product.py:53`, `agents/demo.py:161`, `handlers/agent.py:90`) —
   never a UUID. They cannot have prompts in `navigator.prompt_library`
   today.
2. **Per-user prompts have no home.** All entries in
   `navigator.prompt_library` are publicly visible to every user of the
   bot. There is no mechanism for a user to save their own personal
   prompts against a bot or agent.

### Goals

- **G1.** Allow `navigator.prompt_library` rows to belong to **either** a
  DB-backed bot (UUID `chatbot_id`) **or** a registry/code agent (string
  `agent_id`), with exactly one of the two set on every row.
- **G2.** Teach `PromptLibraryManagement` to honour an `agent_id` query
  parameter on GET, alongside the existing `chatbot_id` parameter.
- **G3.** Ship an **`ALTER TABLE`** migration block (documented in the
  Python model file, alongside the existing `CREATE TABLE` docstring) so
  operators have a clean upgrade path for live databases.
- **G4.** Introduce a new **`UserPrompts`** model at
  `navigator.users_prompts`, keyed by `(user_id, prompt_id)`, with a
  free-form `VARCHAR` `chatbot_id` that accepts UUIDs or registry slugs,
  plus an `is_public BOOLEAN DEFAULT FALSE` reserved for future promotion
  to public.
- **G5.** Expose `UserPromptsManagement(ModelView)` at
  **`/api/v1/agents/user_prompts`**, mirroring the
  `PromptLibraryManagement` shape but with `user_id` enforced from the
  authenticated session on every write.

### Non-Goals (explicitly out of scope)

- **No data migration of existing public prompts into per-user prompts.**
  Users start with an empty `users_prompts` store.
- **No PBAC integration for `UserPrompts`.** Per-row scope is enforced by
  `user_id`; no per-row policy rules.
- **No changes to `BotModel` / `UserBotModel`.** These are bot-definition
  tables and are unaffected.
- **No public-from-day-one sharing.** `is_public` is reserved structure
  only; serving public-promoted user prompts is a later feature.
- **No changes to the `PromptCategory` enum.** Values stay TECH,
  TECH_OR_EXPLAIN, IDEA, EXPLAIN, ACTION, COMMAND, OTHER
  (`models/bots.py:543-556`); both models reuse it.

---

## 2. Architectural Design

### Overview

The change has **two independent pillars** that may be implemented as
separate tasks but live in the same feature:

**Pillar A — Enrich `PromptLibrary`:**
- Add an `agent_id VARCHAR NULL` column to `navigator.prompt_library`.
- Relax `chatbot_id` from `UUID NOT NULL` to `UUID NULL`.
- Add a CHECK constraint enforcing
  `(chatbot_id IS NOT NULL) <> (agent_id IS NOT NULL)` — exactly one set.
- Add `UNIQUE (chatbot_id, agent_id, title)` so duplicate titles cannot
  exist within the same bot/agent (resolved Q1 from proposal).
- Update the Python `PromptLibrary` model accordingly: typed
  `chatbot_id: Optional[uuid.UUID]`, new `agent_id: Optional[str]`.
- Document the `ALTER TABLE` migration in the model's docstring next to
  the existing `CREATE TABLE` block.
- Teach `PromptLibraryManagement` GET to filter by `agent_id` OR
  `chatbot_id` query parameter; if both are supplied, return HTTP 400.

**Pillar B — Introduce `UserPrompts`:**
- New Python model
  `packages/ai-parrot/src/parrot/handlers/models/users_prompts.py`,
  mirroring the `UserBotModel` (`models/users_bots.py:26-117`) sibling
  pattern: composite PK `(user_id, prompt_id)`, FK
  `auth.users(user_id) ON DELETE CASCADE`.
- New DDL file
  `packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql`
  following the `users_bots_creation.sql:7-91` template (table + indexes
  + `updated_at` trigger + COMMENTs).
- `chatbot_id` typed as `VARCHAR NOT NULL` so it can hold UUIDs **or**
  registry agent slugs (resolved by the user: "can be a string, not
  uuid").
- Fields mirror public `PromptLibrary` (resolved Q2 in proposal:
  `prompt_category` + `prompt_tags`) plus an
  `is_public BOOLEAN DEFAULT FALSE` (resolved Q3).
- New handler `UserPromptsManagement(ModelView)` exposed at
  `/api/v1/agents/user_prompts`; sets `user_id` from
  `self.get_userid(session=self._session)` on every write.

### Component Diagram

```
                 ┌─── navigator.prompt_library (ALTERED)
                 │       chatbot_id UUID NULL  ──┐
                 │       agent_id   VARCHAR NULL │ CHECK XOR
                 │       UNIQUE (chatbot_id, agent_id, title)
                 │
PromptLibraryManagement ── GET ?chatbot_id=… | ?agent_id=…
   (existing — extended)

                 ┌─── navigator.users_prompts (NEW)
                 │       PK (user_id, prompt_id)
                 │       chatbot_id VARCHAR  (uuid OR slug)
                 │       is_public  BOOLEAN DEFAULT FALSE
                 │       FK auth.users(user_id) ON DELETE CASCADE
                 │
UserPromptsManagement   ── /api/v1/agents/user_prompts  (NEW)
   (new ModelView)        user_id enforced from session
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.handlers.models.PromptLibrary` | extends | new field `agent_id`, relaxed `chatbot_id` |
| `parrot.handlers.models.PromptCategory` | reuses | unchanged enum |
| `parrot.handlers.bots.PromptLibraryManagement` | extends | new GET filter contract |
| `parrot.handlers.models.UserBotModel` | sibling-pattern reference | DDL + composite PK template |
| `navigator.views.ModelView` | inherits | `UserPromptsManagement` |
| `parrot.conf.PARROT_SCHEMA` | imports | schema constant for new model |
| `app.py:135` (route wiring) | extends | add `UserPromptsManagement.configure(...)` |

### Data Models

```python
# packages/ai-parrot/src/parrot/handlers/models/bots.py — UPDATED

class PromptLibrary(Model):
    prompt_id: uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)
    chatbot_id: Optional[uuid.UUID] = Field(required=False, default=None)   # relaxed
    agent_id:   Optional[str]       = Field(required=False, default=None)   # NEW
    title: str = Field(required=True)
    query: str = Field(required=True)
    description: str = Field(required=False)
    prompt_category: str = Field(required=False, default=PromptCategory.OTHER)
    prompt_tags: list = Field(required=False, default_factory=list)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: int = Field(required=False)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        driver = 'pg'
        name = "prompt_library"
        schema = "navigator"
        strict = True
        frozen = False
```

```python
# packages/ai-parrot/src/parrot/handlers/models/users_prompts.py — NEW

class UserPrompts(Model):
    # Composite identity
    prompt_id:  uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)
    user_id:    int       = Field(primary_key=True, required=True)

    # Bot/agent binding — VARCHAR to allow UUID strings OR registry agent slugs
    chatbot_id: str = Field(required=True)

    # Prompt body (mirrors PromptLibrary)
    title: str = Field(required=True)
    query: str = Field(required=True)
    description: Optional[str] = Field(required=False, default=None)
    prompt_category: str = Field(required=False, default=PromptCategory.OTHER)
    prompt_tags: list = Field(required=False, default_factory=list)

    # Reserved for future "promote to public" workflow
    is_public: bool = Field(required=False, default=False)

    # Metadata
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: int      = Field(required=False)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        driver = "pg"
        name = "users_prompts"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/handlers/bots.py — NEW class

class UserPromptsManagement(ModelView):
    """Per-user prompt library handler.

    Exposes CRUD over navigator.users_prompts at /api/v1/agents/user_prompts.
    Every read/write is implicitly scoped to the authenticated user_id.
    """
    model = UserPrompts
    name: str = "User Prompts Management"
    path: str = '/api/v1/agents/user_prompts'
    pk: str = 'prompt_id'

    async def _set_user_id(self, value, column, data):
        # Always enforce session-derived user_id; never trust client input.
        return await self.get_userid(session=self._session)

    async def _set_created_by(self, value, column, data):
        if not value:
            return await self.get_userid(session=self._session)
        return value
```

```python
# packages/ai-parrot/src/parrot/handlers/bots.py — PromptLibraryManagement.get (extended)

# Pseudocode contract for the GET filter — implementation MUST:
#  - accept either ?chatbot_id=<uuid> OR ?agent_id=<slug>
#  - 400 if both are present
#  - delegate to ModelView default behaviour when neither is present
#    (returns the full row by prompt_id)
```

---

## 3. Module Breakdown

> Pillar A and Pillar B are independent; tasks within each pillar are
> sequential.

### Module A1 — `PromptLibrary` model + DDL update
- **Path**: `packages/ai-parrot/src/parrot/handlers/models/bots.py`
- **Responsibility**: Add `agent_id: Optional[str]` field, relax
  `chatbot_id` to `Optional[uuid.UUID]`, update the in-docstring
  `CREATE TABLE` to reflect the new schema, append a new `ALTER TABLE`
  migration block right after it for live databases.
- **Depends on**: nothing (first module).

### Module A2 — `PromptLibraryManagement` GET filter
- **Path**: `packages/ai-parrot/src/parrot/handlers/bots.py`
- **Responsibility**: Override or extend GET so it filters by either
  `chatbot_id` or `agent_id`. Reject the request with HTTP 400 if both
  are supplied. Leave POST/PUT/DELETE behaviour unchanged.
- **Depends on**: Module A1.

### Module B1 — `UserPrompts` Python model
- **Path**: `packages/ai-parrot/src/parrot/handlers/models/users_prompts.py` (NEW)
- **Responsibility**: Define `UserPrompts(Model)` per §2 Data Models.
  Re-export from `handlers/models/__init__.py`.
- **Depends on**: nothing (parallel to A1).

### Module B2 — `users_prompts` DDL
- **Path**: `packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql` (NEW)
- **Responsibility**: `CREATE TABLE navigator.users_prompts` per §2
  Component Diagram and §6 Codebase Contract. Include the `updated_at`
  trigger, `COMMENT ON TABLE / COLUMN`, and indexes on `user_id` and
  `chatbot_id`.
- **Depends on**: nothing (parallel to A1; should match Module B1's
  Python model field-for-field).

### Module B3 — `UserPromptsManagement` handler
- **Path**: `packages/ai-parrot/src/parrot/handlers/bots.py`
- **Responsibility**: Implement the new `UserPromptsManagement(ModelView)`
  class per §2 New Public Interfaces. Wire it in `app.py` immediately
  after the existing `PromptLibraryManagement.configure(...)` call.
- **Depends on**: Module B1.

### Module T1 — Tests
- **Path**: `packages/ai-parrot/tests/handlers/test_prompt_library.py` (NEW)
  and `packages/ai-parrot/tests/handlers/test_user_prompts.py` (NEW)
- **Responsibility**: Smoke tests for the GET-filter behaviour
  (chatbot_id, agent_id, both → 400, neither → default), the CHECK
  constraint, and CRUD on `UserPrompts` including the session-derived
  `user_id` enforcement.
- **Depends on**: Modules A2 and B3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_prompt_library_agent_id_field` | A1 | `PromptLibrary(agent_id="web_search_agent", title=..., query=...)` validates and persists |
| `test_prompt_library_xor_constraint` | A1 | Setting both `chatbot_id` AND `agent_id` raises (DB CHECK fires) |
| `test_prompt_library_neither_constraint` | A1 | Setting neither raises (DB CHECK fires) |
| `test_prompt_library_unique_title_per_bot` | A1 | Duplicate title within same `chatbot_id` raises UNIQUE violation |
| `test_prompt_library_get_by_chatbot_id` | A2 | GET `?chatbot_id=<uuid>` returns only matching rows |
| `test_prompt_library_get_by_agent_id` | A2 | GET `?agent_id=<slug>` returns only matching rows |
| `test_prompt_library_get_both_rejects` | A2 | GET with both params returns HTTP 400 |
| `test_user_prompts_chatbot_id_uuid_string` | B1 | `UserPrompts(chatbot_id="<uuid>", ...)` accepts UUID-format strings |
| `test_user_prompts_chatbot_id_slug` | B1 | `UserPrompts(chatbot_id="web_search_agent", ...)` accepts agent slugs |
| `test_user_prompts_is_public_default_false` | B1 | `is_public` defaults to `False` |
| `test_user_prompts_session_user_id` | B3 | POST sets `user_id` from session, ignoring any client value |

### Integration Tests

| Test | Description |
|---|---|
| `test_prompt_library_alter_migration` | Run the documented `ALTER TABLE` block against a fresh `prompt_library` instance and confirm the new constraints exist |
| `test_user_prompts_end_to_end_crud` | POST/GET/PUT/DELETE through `/api/v1/agents/user_prompts` with a faked session |
| `test_user_prompts_cascade_delete` | Deleting an `auth.users` row cascades-deletes the per-user prompts |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/handlers/conftest.py — additions

@pytest.fixture
def public_prompt_chatbot(prompt_library_conn) -> dict:
    return {
        "chatbot_id": uuid.uuid4(),
        "title": "Greeting",
        "query": "Say hi.",
        "prompt_category": "command",
    }

@pytest.fixture
def public_prompt_agent(prompt_library_conn) -> dict:
    return {
        "agent_id": "web_search_agent",
        "title": "Find docs",
        "query": "Search official docs for {topic}.",
        "prompt_category": "tech",
    }

@pytest.fixture
def user_prompt_row() -> dict:
    return {
        "user_id": 42,
        "chatbot_id": "web_search_agent",   # slug; VARCHAR is fine
        "title": "My favourite search",
        "query": "Search {topic} in {language}.",
        "is_public": False,
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true.

### Pillar A — `PromptLibrary`
- [ ] `navigator.prompt_library` has a new nullable column `agent_id VARCHAR`.
- [ ] `chatbot_id` is now nullable on `navigator.prompt_library`.
- [ ] A CHECK constraint enforces
  `(chatbot_id IS NOT NULL) <> (agent_id IS NOT NULL)` (exactly one set).
- [ ] A UNIQUE constraint exists on `(chatbot_id, agent_id, title)`.
- [ ] The Python `PromptLibrary` model exposes
  `chatbot_id: Optional[uuid.UUID]` and `agent_id: Optional[str]`.
- [ ] The model docstring contains both the updated `CREATE TABLE` and a
  separate documented `ALTER TABLE` migration block for live databases.
- [ ] `PromptLibraryManagement` GET filters by `chatbot_id` or `agent_id`
  query parameter; returns HTTP 400 when both are supplied.
- [ ] No existing call site that uses `chatbot_id` as a UUID breaks
  (verified by smoke test reading any pre-migration row).

### Pillar B — `UserPrompts`
- [ ] `navigator.users_prompts` exists with composite PK `(user_id, prompt_id)`.
- [ ] `user_id` references `auth.users(user_id) ON DELETE CASCADE`.
- [ ] `chatbot_id` is `VARCHAR NOT NULL` (accepts UUIDs or slugs).
- [ ] `prompt_category` and `prompt_tags` mirror the public `PromptLibrary`.
- [ ] `is_public BOOLEAN NOT NULL DEFAULT FALSE` exists.
- [ ] `updated_at` is maintained by a trigger that follows the
  `users_bots` pattern.
- [ ] Indexes exist on `user_id` and `chatbot_id`.
- [ ] DDL lives in a separate
  `users_prompts_creation.sql` file (NOT embedded in the Python
  docstring) — follows the `users_bots_creation.sql` template.
- [ ] `UserPrompts` is exported from
  `packages/ai-parrot/src/parrot/handlers/models/__init__.py`.

### API & wiring
- [ ] `UserPromptsManagement` is configured at
  `/api/v1/agents/user_prompts` in `app.py`.
- [ ] POST to `/api/v1/agents/user_prompts` populates `user_id` from the
  authenticated session, ignoring any client-supplied value.
- [ ] GET to `/api/v1/agents/user_prompts` returns only rows owned by the
  authenticated user.

### Cross-cutting
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/handlers/ -v`.
- [ ] Integration tests pass: `pytest packages/ai-parrot/tests/integration/ -v -k prompt`.
- [ ] No regression in the existing handler test suite.
- [ ] No new mypy or ruff violations introduced in the touched files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below are verified at the line numbers shown.

### Verified Imports

```python
# All verified against the source tree
from datamodel import Field                                          # used by every Model in handlers/models/
from asyncdb.models import Model                                     # used by every Model in handlers/models/
from parrot.conf import PARROT_SCHEMA                                # verified: packages/ai-parrot/src/parrot/conf.py:82
from parrot.handlers.models import PromptLibrary, PromptCategory     # verified: handlers/models/__init__.py:8,9
from parrot.handlers.models import UserBotModel                      # verified: handlers/models/__init__.py:12

# In handlers/bots.py:
from navigator.views import ModelView                                # verified: handlers/bots.py:16
from .models import PromptLibrary, ChatbotUsage, ChatbotFeedback     # verified: handlers/bots.py:27-33
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/handlers/models/bots.py
class PromptCategory(Enum):                                          # line 543
    TECH = "tech"; TECH_OR_EXPLAIN = "tech-or-explain"; IDEA = "idea"
    EXPLAIN = "explain"; ACTION = "action"; COMMAND = "command"; OTHER = "other"

class PromptLibrary(Model):                                          # line 558
    prompt_id: uuid.UUID = Field(primary_key=True, ...)              # line 577
    chatbot_id: uuid.UUID = Field(required=True)                     # line 578  ← to relax to Optional
    title: str = Field(required=True)                                # line 579
    query: str = Field(required=True)                                # line 580
    description: str                                                 # line 581
    prompt_category: str = Field(default=PromptCategory.OTHER)       # line 582
    prompt_tags: list = Field(default_factory=list)                  # line 583
    created_at: datetime; created_by: int; updated_at: datetime      # 584-586

    class Meta:                                                      # line 588
        driver = 'pg'; name = "prompt_library"; schema = "navigator"

# packages/ai-parrot/src/parrot/handlers/bots.py
class PromptLibraryManagement(ModelView):                            # line 96
    model = PromptLibrary                                            # line 102
    name: str = "Prompt Library Management"                          # line 103
    path: str = '/api/v1/prompt_library'                             # line 104  ← class default; not the live path
    pk: str = 'prompt_id'                                            # line 105
    async def _set_created_by(self, value, column, data):            # line 107
        if not value:
            return await self.get_userid(session=self._session)
        return value

# packages/ai-parrot/src/parrot/handlers/models/users_bots.py
class UserBotModel(Model):                                           # line 26
    chatbot_id: uuid.UUID = Field(primary_key=True, ...)             # line 35
    user_id: int = Field(primary_key=True, required=True)            # line 40
    class Meta:                                                      # line 112
        driver = "pg"; name = "users_bots"; schema = PARROT_SCHEMA
```

### Existing DDL (reference for new file)

```sql
-- packages/ai-parrot/src/parrot/handlers/models/users_bots_creation.sql:7-15
CREATE TABLE IF NOT EXISTS navigator.users_bots (
    chatbot_id     UUID NOT NULL DEFAULT uuid_generate_v4(),
    user_id        INTEGER NOT NULL
                   REFERENCES auth.users(user_id) ON DELETE CASCADE,
    ...
    PRIMARY KEY (user_id, chatbot_id),
    CONSTRAINT unq_users_bots_user_name UNIQUE (user_id, name)
);
-- Trigger pattern (lines 79-91):
CREATE OR REPLACE FUNCTION update_users_bots_updated_at() ...
DROP TRIGGER IF EXISTS trigger_users_bots_updated_at ON navigator.users_bots;
CREATE TRIGGER trigger_users_bots_updated_at
    BEFORE UPDATE ON navigator.users_bots
    FOR EACH ROW
    EXECUTE FUNCTION update_users_bots_updated_at();
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `UserPrompts` (model) | `auth.users(user_id)` | FK ON DELETE CASCADE | `models/users_bots_creation.sql:14-15` (sibling pattern) |
| `UserPrompts` (model) | `PromptCategory` (enum) | default value for `prompt_category` | `models/bots.py:543-556` |
| `UserPromptsManagement` | `ModelView` | inherits | `handlers/bots.py:16` |
| `UserPromptsManagement` | `self.get_userid()` | session-derived user_id | `handlers/bots.py:109,182,790` |
| `UserPromptsManagement.configure` | `app.py:135` | route registration | `app.py:135` |
| `PromptLibrary` (altered) | `PromptLibraryManagement` GET filter | query param dispatch | `handlers/bots.py:96-110` |

### ALTER TABLE block (template for Module A1 docstring)

```sql
-- Migration block to be added INSIDE the PromptLibrary docstring,
-- right after the existing CREATE TABLE, so operators have an
-- authoritative single source of truth.

-- ALTER TABLE — adds agent_id and XOR constraint on existing rows.
ALTER TABLE navigator.prompt_library
    ADD COLUMN IF NOT EXISTS agent_id VARCHAR;

ALTER TABLE navigator.prompt_library
    ALTER COLUMN chatbot_id DROP NOT NULL;

ALTER TABLE navigator.prompt_library
    ADD CONSTRAINT chk_prompt_library_target_xor
    CHECK ((chatbot_id IS NOT NULL) <> (agent_id IS NOT NULL));

ALTER TABLE navigator.prompt_library
    ADD CONSTRAINT unq_prompt_library_target_title
    UNIQUE (chatbot_id, agent_id, title);

CREATE INDEX IF NOT EXISTS idx_prompt_library_agent_id
    ON navigator.prompt_library(agent_id);
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.handlers.models.UserPrompts`~~ — does NOT exist yet; this
  spec creates it.
- ~~`parrot.handlers.bots.UserPromptsManagement`~~ — does NOT exist;
  this spec creates it.
- ~~`navigator.users_prompts`~~ table — does NOT exist; this spec
  creates it.
- ~~`PromptLibrary.agent_id`~~ — does NOT exist on the model yet; this
  spec adds it.
- ~~`UserBotModel.prompts`~~ — `UserBotModel` has no `prompts`
  attribute; the linkage is implicit via `chatbot_id`.
- ~~`PromptLibraryManagement.get_by_agent_id()`~~ — there is no such
  method; GET filtering must be implemented inside the standard `get`
  dispatch (or via ModelView's filter mechanism), not as a sibling
  method.
- ~~`parrot.conf.NAVIGATOR_SCHEMA`~~ — the schema constant is
  `PARROT_SCHEMA` (`parrot/conf.py:82`); do NOT invent
  `NAVIGATOR_SCHEMA`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

…(truncated)…
