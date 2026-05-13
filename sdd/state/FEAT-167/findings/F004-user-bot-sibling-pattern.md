---
id: F004
query_id: Q005+Q009+Q010
type: read
intent: Sibling per-user model pattern to mirror for UserPrompts
confidence: high
---

# F004 — `UserBotModel` is the canonical per-user model pattern

## Model file
`packages/ai-parrot/src/parrot/handlers/models/users_bots.py:26-117`

Key shape (relevant excerpt):
```python
class UserBotModel(Model):
    # Composite identity
    chatbot_id: uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)
    user_id:    int       = Field(primary_key=True, required=True)
    # ... rest of fields ...
    class Meta:
        driver  = "pg"
        name    = "users_bots"
        schema  = PARROT_SCHEMA
        strict  = True
```

## DDL file
`packages/ai-parrot/src/parrot/handlers/models/users_bots_creation.sql:7-73`

Key elements:
```sql
CREATE TABLE IF NOT EXISTS navigator.users_bots (
    chatbot_id  UUID NOT NULL DEFAULT uuid_generate_v4(),
    user_id     INTEGER NOT NULL
                REFERENCES auth.users(user_id) ON DELETE CASCADE,
    -- ...
    PRIMARY KEY (user_id, chatbot_id),
    CONSTRAINT unq_users_bots_user_name UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_users_bots_user_id   ON navigator.users_bots(user_id);
CREATE INDEX IF NOT EXISTS idx_users_bots_chatbot_id ON navigator.users_bots(chatbot_id);
```

Plus an `updated_at` trigger (lines 79-91) and `COMMENT ON TABLE / COLUMN` lines.

## Conventions extracted from this model
1. **Separate `.sql` file** alongside the Python model (NOT embedded in the docstring as `PromptLibrary` currently does). The `__init__.py` for the package re-exports the model only; the SQL is consumed by migration tooling.
2. **`auth.users(user_id) ON DELETE CASCADE`** — required to reap per-user rows when the account is deleted.
3. **Composite PK** `(user_id, ...)` for per-user resources.
4. **`UNIQUE (user_id, name)`** to prevent duplicates per user.
5. **`updated_at` trigger** is the standard way to keep `updated_at` fresh.
6. **`COMMENT ON TABLE / COLUMN`** documents intent and any encryption notes.
7. **Schema constant**: use `PARROT_SCHEMA` from `parrot.conf` rather than hard-coding `"navigator"`.

## Apply to FEAT-167 `UserPrompts`
- New file: `packages/ai-parrot/src/parrot/handlers/models/users_prompts.py` (Python model).
- New file: `packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql` (DDL).
- Composite PK `(user_id, prompt_id)`; uniqueness constraint on `(user_id, chatbot_id, title)` (so the same user can repeat a title across different bots but not within the same bot).
- `chatbot_id` should be `VARCHAR` here (per the user's request that it "can be a string, not uuid") to accept either UUID strings or registry agent_id slugs.

## Citations
- `packages/ai-parrot/src/parrot/handlers/models/users_bots.py:26-117`
- `packages/ai-parrot/src/parrot/handlers/models/users_bots_creation.sql:7-91`
- `packages/ai-parrot/src/parrot/handlers/models/__init__.py:3-34`
