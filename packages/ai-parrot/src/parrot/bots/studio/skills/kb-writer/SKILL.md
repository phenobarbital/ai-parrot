---
name: kb-writer
description: Conventions for writing knowledge-base files for an existing agent
triggers:
  - write a kb file
  - add knowledge
  - update knowledge base
  - kb file
category: agent-development
---

# KB Writer

Knowledge-base files give an existing agent extra reference material at
answer time. They live flat under `AGENTS_DIR/<agent_name>/kb/` — no
subdirectories.

## Rules

1. The target agent must already exist — check with
   `list_existing_agents` first; if it doesn't, build the agent (see the
   agent-builder skill) before writing KB content for it.
2. Filenames must be a single path segment (no `/`) with a `.md` or
   `.txt` extension.
3. Write clear, self-contained sections — the retrieval layer chunks
   these files, so avoid content that only makes sense with hidden
   context from earlier in the document.
4. Call `write_kb_file(agent_name, filename, content)`. The response
   always reports `reload_required: true` — tell the user the agent must
   be reloaded (or restarted) before the new content is used; this skill
   never triggers a reload itself.

Keep each file focused on one topic — prefer several small, well-titled
files over one large dump.
