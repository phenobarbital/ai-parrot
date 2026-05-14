---
id: F001
query_id: Q001+Q002
type: read
intent: Locate and inspect PromptLibrary model definition + embedded DDL
confidence: high
---

# F001 — `PromptLibrary` model (current state)

## Location
- File: `packages/ai-parrot/src/parrot/handlers/models/bots.py`
- Lines: 558-598
- Exported from: `packages/ai-parrot/src/parrot/handlers/models/__init__.py:8`

## Fields (current)
```python
class PromptLibrary(Model):
    prompt_id: uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)
    chatbot_id: uuid.UUID = Field(required=True)        # ← UUID-only, no agent_id support
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
```

## Embedded DDL (in docstring, lines 563-576)
```sql
CREATE TABLE IF NOT EXISTS navigator.prompt_library (
    prompt_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chatbot_id UUID,                       -- ← also UUID-only
    title varchar,
    query varchar,
    description TEXT,
    prompt_category varchar,
    prompt_tags varchar[],
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by INTEGER,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

## Notes
- No `agent_id` column exists.
- No `user_id` column exists (these are public prompts shared by all users of a chatbot).
- DDL is embedded in the model docstring — no separate `.sql` file (unlike `users_bots`).
- `PromptCategory` enum at lines 543-556 — values: TECH, TECH_OR_EXPLAIN, IDEA, EXPLAIN, ACTION, COMMAND, OTHER.

## Citations
- `packages/ai-parrot/src/parrot/handlers/models/bots.py:558-598`
- `packages/ai-parrot/src/parrot/handlers/models/__init__.py:8`
