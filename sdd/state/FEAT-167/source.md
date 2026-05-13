---
kind: inline
jira_key: null
fetched_at: 2026-05-13T17:55:57Z
summary_oneline: "PromptLibrary supports public per-chatbot prompts only; need agent_id support and a new UserPrompts model for per-user prompts."
---

# Prompt Library Changes

Current `PromptLibrary` model only cover "public" prompts, prompts are per-chatbot and publicily available for all users.
But we need then a new model, `UserPrompts` for saving per-user and per-agent prompts.

# changes:
- prompt_library uses chatbot_id as uuid, but manually-created (by code) and AgentRegistry agents doesn't have chatbot_id as uuid, change to use chatbot_id or agent_id (for agents).
- modify `PromptLibraryManagement` to filter by chatbot_id or agent_id when GET retrieved a single bot instance
- Add the "ALTER TABLE" documentation to change the current `navigator.prompt_library` table.
- Create a new model `UserPrompts` with api `/api/v1/agents/user_prompts` allow users to save own prompts.
  constraint is user_id / chatbot_id (can be an string, not uuid)
- add in model documentation the "create table sentence", table will be `navigator.users_prompts`.
