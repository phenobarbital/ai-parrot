---
type: Wiki Overview
title: 'TASK-1133: Add `agent_id` to `PromptLibrary` model + ALTER TABLE docs'
id: doc:sdd-tasks-completed-task-1133-prompt-library-agent-id-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module A1. The current `PromptLibrary` model only accepts a UUID
relates_to:
- concept: mod:parrot.handlers.models
  rel: mentions
---

# TASK-1133: Add `agent_id` to `PromptLibrary` model + ALTER TABLE docs

**Feature**: FEAT-167 — Prompt Library: agent_id support + new UserPrompts model
**Spec**: `sdd/specs/promptlibrary-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module A1. The current `PromptLibrary` model only accepts a UUID
`chatbot_id`, which excludes registry/code-defined agents whose identity is
a string `agent_id` (e.g. `web_search_agent`, `hitl_demo`,
`product_report`). This task relaxes the model to accept either, with a
DB-side CHECK enforcing XOR. It also documents the live-database
migration as an `ALTER TABLE` block embedded in the model docstring next
to the existing `CREATE TABLE`.

---

## Scope

- Add `agent_id: Optional[str]` field to `PromptLibrary` (`models/bots.py`).
- Relax `chatbot_id` from `uuid.UUID = Field(required=True)` to
  `Optional[uuid.UUID] = Field(required=False, default=None)`.
- Update the embedded `CREATE TABLE IF NOT EXISTS navigator.prompt_library`
  docstring block to:
  - mark `chatbot_id UUID` as nullable,
  - add `agent_id VARCHAR`,
  - add the `CHECK ((chatbot_id IS NOT NULL) <> (agent_id IS NOT NULL))`
    constraint,
  - add `UNIQUE (chatbot_id, agent_id, title)` named
    `unq_prompt_library_target_title`,
  - add `CREATE INDEX idx_prompt_library_agent_id ON navigator.prompt_library(agent_id)`.
- Append, in the same docstring, an authoritative `-- ALTER TABLE` block
  (verbatim contents below in *Implementation Notes*) for operators with
  a populated database.

**NOT in scope**:
- Updating `PromptLibraryManagement` GET behaviour (TASK-1134).
- Creating the new `UserPrompts` model (TASK-1135).
- Writing tests (TASK-1138 covers the test smoke suite).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/models/bots.py` | MODIFY | Add `agent_id` to `PromptLibrary`; relax `chatbot_id`; update + extend the embedded DDL docstring. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present at the top of models/bots.py — DO NOT re-import.
from typing import List, Union, Optional   # verified: models/bots.py:4
import uuid                                # verified: models/bots.py:5
from datetime import datetime              # verified: models/bots.py:7
from datamodel import Field                # verified: models/bots.py:10
from asyncdb.models import Model           # verified: models/bots.py:11
```

`Optional` is already imported on line 4 — DO NOT add a new import.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/models/bots.py
class PromptCategory(Enum):                                            # line 543
    TECH = "tech"; TECH_OR_EXPLAIN = "tech-or-explain"; IDEA = "idea"
    EXPLAIN = "explain"; ACTION = "action"; COMMAND = "command"; OTHER = "other"

class PromptLibrary(Model):                                            # line 558
    prompt_id: uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)  # 577
    chatbot_id: uuid.UUID = Field(required=True)                       # line 578  ← RELAX
    title: str = Field(required=True)                                  # line 579
    query: str = Field(required=True)                                  # line 580
    description: str = Field(required=False)                           # line 581
    prompt_category: str = Field(required=False, default=PromptCategory.OTHER)  # 582
    prompt_tags: list = Field(required=False, default_factory=list)    # line 583
    created_at: datetime; created_by: int; updated_at: datetime        # 584-586

    class Meta:                                                        # line 588
        driver = 'pg'
        name = "prompt_library"
        schema = "navigator"
        strict = True
        frozen = False
```

### Does NOT Exist
- ~~`PromptLibrary.agent_id`~~ — does NOT exist yet; this task adds it.
- ~~`PromptLibrary.from_chatbot_or_agent()`~~ — not a real class method;
  do NOT add factories. The constructor handles both via the new
  `agent_id` field.
- ~~A separate `prompt_library_creation.sql` file~~ — does NOT exist;
  the DDL lives inside the Python docstring (legacy quirk preserved
  for this task).
- ~~`PromptLibrary.Meta.constraints`~~ — `asyncdb`'s `Model.Meta` does
  not expose Python-level CHECK constraints; constraints live in the
  DDL block only.

---

## Implementation Notes

### Pattern to Follow

`UserBotModel` (`packages/ai-parrot/src/parrot/handlers/models/users_bots.py:35-40`)
uses `Optional[uuid.UUID]`-style fields the same way. Use the same
`Field(required=False, default=None)` shape.

### Field shape

```python
# REPLACE line 578 with:
chatbot_id: Optional[uuid.UUID] = Field(required=False, default=None)
# INSERT immediately after (new line 579):
agent_id:   Optional[str]       = Field(required=False, default=None)
```

### Updated docstring DDL block (replace the existing CREATE TABLE block)

```sql
-- PostgreSQL CREATE TABLE Syntax --
CREATE TABLE IF NOT EXISTS navigator.prompt_library (
        prompt_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        chatbot_id UUID,                                  -- now nullable
        agent_id   VARCHAR,                               -- NEW
        title      VARCHAR,
        query      VARCHAR,
        description TEXT,
        prompt_category VARCHAR,
        prompt_tags VARCHAR[],
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        created_by INTEGER,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT chk_prompt_library_target_xor
            CHECK ((chatbot_id IS NOT NULL) <> (agent_id IS NOT NULL)),
        CONSTRAINT unq_prompt_library_target_title
            UNIQUE (chatbot_id, agent_id, title)
);
CREATE INDEX IF NOT EXISTS idx_prompt_library_agent_id
    ON navigator.prompt_library(agent_id);
```

### Append the ALTER TABLE block to the same docstring

```sql
-- ALTER TABLE (live-database migration) --
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

### Key Constraints

- Do not change `Meta.schema = "navigator"` to `PARROT_SCHEMA` —
  that's an open hygiene question deferred to a later feature (spec §8).
- Do not introduce new imports; `Optional` is already available
  (`models/bots.py:4`).
- Keep `prompt_id` and all metadata fields exactly as today.

### References in Codebase
- `models/bots.py:558-598` — current `PromptLibrary` definition.
- `models/bots.py:543-556` — `PromptCategory` enum (unchanged).
- `models/users_bots.py:35-40` — example of `Optional[uuid.UUID]` field shape.

---

## Acceptance Criteria

- [ ] `PromptLibrary.agent_id` exists and is `Optional[str]` with default `None`.
- [ ] `PromptLibrary.chatbot_id` is `Optional[uuid.UUID]` with default `None`.
- [ ] The class docstring contains the updated `CREATE TABLE` block with
  `agent_id`, the XOR `CHECK` constraint, and the
  `unq_prompt_library_target_title` UNIQUE constraint.
- [ ] The class docstring contains a clearly-labelled `-- ALTER TABLE` block
  for live-database migration.
- [ ] `from parrot.handlers.models import PromptLibrary` still works
  (no broken exports).
- [ ] `ruff check packages/ai-parrot/src/parrot/handlers/models/bots.py` — no new errors.
- [ ] Manual instantiation works: `PromptLibrary(agent_id="web_search_agent", title="x", query="y")` does not raise.

---

## Test Specification

> Tests for this change land in TASK-1138. The smoke checks below are
> only for the implementing agent to run manually before handing off.

```python
# Manual smoke (not committed):
from parrot.handlers.models import PromptLibrary
p1 = PromptLibrary(chatbot_id=None, agent_id="web_search_agent", title="x", query="q")
p2 = PromptLibrary(chatbot_id=uuid.uuid4(),                 title="x", query="q")
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/promptlibrary-changes.spec.md` §2, §6, §7.
2. Verify the Codebase Contract: re-grep line 578 of `models/bots.py`
   to confirm the current `chatbot_id: uuid.UUID = Field(required=True)` is intact.
3. Apply the two field edits and rewrite the docstring DDL block.
4. Append the `ALTER TABLE` block to the same docstring.
5. Run ruff on the file; ensure no new errors.
6. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-13
**Notes**: Added `agent_id: Optional[str]` field, relaxed `chatbot_id` to `Optional[uuid.UUID]`. Updated docstring with the full new CREATE TABLE DDL (including XOR CHECK constraint and UNIQUE constraint) and the ALTER TABLE migration block. Verified annotations via PYTHONPATH smoke test.

**Deviations from spec**: none
