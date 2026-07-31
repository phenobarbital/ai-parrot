---
type: Wiki Overview
title: 'TASK-1136: Author the `navigator.users_prompts` DDL file'
id: doc:sdd-tasks-completed-task-1136-user-prompts-ddl-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module B2. Unlike `PromptLibrary` (which embeds DDL in its
---

# TASK-1136: Author the `navigator.users_prompts` DDL file

**Feature**: FEAT-167 — Prompt Library: agent_id support + new UserPrompts model
**Spec**: `sdd/specs/promptlibrary-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module B2. Unlike `PromptLibrary` (which embeds DDL in its
docstring), the new `UserPrompts` model follows the dominant convention
in `handlers/models/` of keeping DDL in a sibling `.sql` file
(`users_bots_creation.sql:7-91` is the template). This task authors that
file end-to-end.

The DDL must match `UserPrompts` (TASK-1135) field-for-field but is
independent: this task can run in parallel with TASK-1135 as long as the
two agents agree on the schema documented in spec §2.

---

## Scope

- Create
  `packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql`
  containing:
  - `CREATE TABLE IF NOT EXISTS navigator.users_prompts (...)` with the
    composite PK `(user_id, prompt_id)` and FK `auth.users(user_id) ON
    DELETE CASCADE`.
  - `UNIQUE (user_id, chatbot_id, title)` to prevent duplicate titles for
    the same user/bot.
  - Indexes on `user_id` and `chatbot_id`.
  - An `update_users_prompts_updated_at()` function + `BEFORE UPDATE`
    trigger pattern copied (and renamed) from
    `users_bots_creation.sql:79-91`.
  - `COMMENT ON TABLE` and at least `COMMENT ON COLUMN` for `chatbot_id`,
    `is_public`, and `prompt_tags`.

**NOT in scope**:
- Python model (TASK-1135).
- Handler (TASK-1137).
- Running the DDL against a live database — that is a deployment
  concern handled by operators.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql` | CREATE | Full DDL for the new table. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Reference DDL

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
```

```sql
-- packages/ai-parrot/src/parrot/handlers/models/users_bots_creation.sql:75-91
CREATE INDEX IF NOT EXISTS idx_users_bots_user_id   ON navigator.users_bots(user_id);
CREATE INDEX IF NOT EXISTS idx_users_bots_enabled   ON navigator.users_bots(enabled);
CREATE INDEX IF NOT EXISTS idx_users_bots_chatbot_id ON navigator.users_bots(chatbot_id);

CREATE OR REPLACE FUNCTION update_users_bots_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_users_bots_updated_at ON navigator.users_bots;
CREATE TRIGGER trigger_users_bots_updated_at
    BEFORE UPDATE ON navigator.users_bots
    FOR EACH ROW
    EXECUTE FUNCTION update_users_bots_updated_at();
```

### Does NOT Exist
- ~~`auth.user`~~ (singular) — the FK table is `auth.users` (plural).
  Reference: `users_bots_creation.sql:14`.
- ~~A separate `auth.users_prompts` table~~ — the new table lives in the
  `navigator` schema, not `auth`.
- ~~`gen_random_uuid()` default~~ — the convention here is
  `uuid_generate_v4()` (matches `users_bots_creation.sql:13`). Do NOT
  switch to `pgcrypto`'s helper unless the entire schema does.

---

## Implementation Notes

### Full DDL template

```sql
-- Per-user prompt library.
-- Mirrors navigator.prompt_library structurally but keyed by
-- (user_id, prompt_id) so each user owns their private prompt collection.
-- ``chatbot_id`` is VARCHAR (not UUID) because it may hold either a
-- DB-backed chatbot UUID (stringified) or a registry agent slug.

CREATE TABLE IF NOT EXISTS navigator.users_prompts (
    -- Composite identity. user_id references the navigator-auth users
    -- table (auth.users.user_id) so deleting an account also reaps every
    -- prompt it owns.
    prompt_id      UUID NOT NULL DEFAULT uuid_generate_v4(),
    user_id        INTEGER NOT NULL
                   REFERENCES auth.users(user_id) ON DELETE CASCADE,

    -- Bot/agent binding. VARCHAR so we accept either a UUID string
    -- (for DB-backed chatbots) or a registry agent slug.
    chatbot_id     VARCHAR NOT NULL,

    -- Prompt body — mirrors public navigator.prompt_library.
    title          VARCHAR NOT NULL,
    query          TEXT    NOT NULL,
    description    TEXT,
    prompt_category VARCHAR,
    prompt_tags    VARCHAR[] DEFAULT '{}'::VARCHAR[],

    -- Reserved for future "promote to public" workflow.
    is_public      BOOLEAN NOT NULL DEFAULT FALSE,

    -- Metadata.
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    created_by     INTEGER,
    updated_at     TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (user_id, prompt_id),
    CONSTRAINT unq_users_prompts_user_bot_title
        UNIQUE (user_id, chatbot_id, title)
);

CREATE INDEX IF NOT EXISTS idx_users_prompts_user_id    ON navigator.users_prompts(user_id);
CREATE INDEX IF NOT EXISTS idx_users_prompts_chatbot_id ON navigator.users_prompts(chatbot_id);

CREATE OR REPLACE FUNCTION update_users_prompts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_users_prompts_updated_at ON navigator.users_prompts;
CREATE TRIGGER trigger_users_prompts_updated_at
    BEFORE UPDATE ON navigator.users_prompts
    FOR EACH ROW
    EXECUTE FUNCTION update_users_prompts_updated_at();

COMMENT ON TABLE  navigator.users_prompts IS
    'Per-user prompt library. user_id FK to auth.users with ON DELETE CASCADE; chatbot_id is VARCHAR so it accepts both UUID strings and registry agent slugs.';
COMMENT ON COLUMN navigator.users_prompts.chatbot_id IS
    'UUID string of a DB-backed chatbot OR registry slug of a code-defined agent (e.g. "web_search_agent").';
COMMENT ON COLUMN navigator.users_prompts.is_public IS
    'Reserved flag for a future public-promotion workflow. Default FALSE; today the row is always private to user_id.';
COMMENT ON COLUMN navigator.users_prompts.prompt_tags IS
    'Free-form VARCHAR[] tags, mirroring navigator.prompt_library.prompt_tags.';
```

### Key Constraints

- `chatbot_id` is `VARCHAR NOT NULL`. Do NOT make it nullable; per-user
  prompts always belong to a specific bot/agent.
- `is_public` is `NOT NULL DEFAULT FALSE`. Do NOT make it nullable.
- The composite PK MUST be `(user_id, prompt_id)` — same convention as
  `users_bots` (which is `(user_id, chatbot_id)` for that table; here
  `prompt_id` is the per-row PK).
- Schema name is hard-coded `navigator` in the DDL (matches the rest of
  the project's SQL files). The Python model uses `PARROT_SCHEMA` — the
  two MUST resolve to the same string in any environment that runs the
  DDL.

### References in Codebase
- `models/users_bots_creation.sql` — full reference template.
- `models/bots.py:558-598` — `PromptLibrary` (for field parity check).

---

## Acceptance Criteria

- [ ] File exists at
  `packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql`.
- [ ] Table `navigator.users_prompts` is creatable against a fresh
  Postgres instance with `uuid_generate_v4()` available (typically
  `CREATE EXTENSION IF NOT EXISTS "uuid-ossp"` already in place — same
  as `users_bots`).
- [ ] The DDL contains the composite PK, FK CASCADE, UNIQUE constraint,
  two indexes, the trigger function + trigger, and at least three
  `COMMENT ON COLUMN` lines.
- [ ] Field set matches `UserPrompts` from TASK-1135 (prompt_id, user_id,
  chatbot_id, title, query, description, prompt_category, prompt_tags,
  is_public, created_at, created_by, updated_at).
- [ ] Running `psql -1 -f users_prompts_creation.sql` against a fresh
  schema completes without error.

---

## Implementation Smoke

```bash
# Optional: validate syntax against a throwaway Postgres
docker run --rm -e POSTGRES_PASSWORD=x -d --name pg-smoke postgres:15
sleep 3
docker exec -i pg-smoke psql -U postgres -v ON_ERROR_STOP=1 \
    -c 'CREATE SCHEMA navigator; CREATE SCHEMA auth; CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
        CREATE TABLE auth.users (user_id INTEGER PRIMARY KEY);'
docker exec -i pg-smoke psql -U postgres -v ON_ERROR_STOP=1 \
    < packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql
docker rm -f pg-smoke
```

---

## Agent Instructions

1. Read spec §2 (Component Diagram), §5 (Acceptance Criteria — Pillar B),
   and §6 (DDL reference).
2. Read `users_bots_creation.sql` in full as the reference.
3. Write `users_prompts_creation.sql` per the template above.
4. (Optional) Run the smoke command in a throwaway container.
5. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-13
**Notes**: Created `users_prompts_creation.sql` with composite PK `(user_id, prompt_id)`, FK ON DELETE CASCADE, `chatbot_id VARCHAR NOT NULL`, `is_public BOOLEAN NOT NULL DEFAULT FALSE`, UNIQUE constraint, two indexes, updated_at trigger function and trigger, and 4 COMMENT ON lines. Matches `UserPrompts` model field-for-field.

**Deviations from spec**: none
