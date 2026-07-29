---
type: Wiki Summary
title: parrot.knowledge.wiki.claude_code.installer
id: mod:parrot.knowledge.wiki.claude_code.installer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Idempotent installer for the Claude Code wiki integration.
relates_to:
- concept: func:parrot.knowledge.wiki.claude_code.installer.install_claude_integration
  rel: defines
- concept: func:parrot.knowledge.wiki.claude_code.installer.integration_status
  rel: defines
- concept: func:parrot.knowledge.wiki.claude_code.installer.uninstall_claude_integration
  rel: defines
- concept: mod:parrot.knowledge.wiki.claude_code
  rel: references
- concept: mod:parrot.knowledge.wiki.claude_code.assets
  rel: references
- concept: mod:parrot.knowledge.wiki.project
  rel: references
---

# `parrot.knowledge.wiki.claude_code.installer`

Idempotent installer for the Claude Code wiki integration.

``install_claude_integration`` wires the repository knowledge graph
into Claude Code:

1. persists ``.parrot/wiki.json`` (the config the hook reads);
2. appends a managed section to ``CLAUDE.md`` telling the assistant to
   prefer ``wikitoolkit query "<question>"`` over grepping raw files;
3. merges a ``PreToolUse`` nudge hook into ``.claude/settings.json``
   (matcher ``Grep|Glob|Read`` → ``wikitoolkit claude-hook``);
4. writes the ``/parrotwiki`` slash command;
5. optionally installs a chained git ``post-commit`` hook that runs
   ``wikitoolkit upsert --changed`` after every commit;
6. optionally git-ignores ``.parrot/``.

Every step is marker-based and re-runnable; ``uninstall`` removes
exactly the managed artifacts and nothing else.

## Functions

- `def install_claude_integration(root: Path, config: Optional[WikiProjectConfig]=None, git_hook: bool=True, gitignore: bool=True) -> list[str]` — Install the wiki ↔ Claude Code integration into a repository.
- `def uninstall_claude_integration(root: Path) -> list[str]` — Remove every managed artifact written by the installer.
- `def integration_status(root: Path) -> dict[str, Any]` — Report which integration pieces are currently installed.
