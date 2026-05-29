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
