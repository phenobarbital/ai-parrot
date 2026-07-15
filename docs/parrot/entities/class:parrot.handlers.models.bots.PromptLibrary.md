---
type: Wiki Entity
title: PromptLibrary
id: class:parrot.handlers.models.bots.PromptLibrary
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: PromptLibrary.
---

# PromptLibrary

Defined in [`parrot.handlers.models.bots`](../summaries/mod:parrot.handlers.models.bots.md).

```python
class PromptLibrary(Model)
```

PromptLibrary.

Saving information about Prompt Library.

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
