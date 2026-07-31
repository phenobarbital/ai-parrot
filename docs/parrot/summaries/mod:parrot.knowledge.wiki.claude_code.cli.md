---
type: Wiki Summary
title: parrot.knowledge.wiki.claude_code.cli
id: mod:parrot.knowledge.wiki.claude_code.cli
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: '``parrot claude`` — install the LLM Wiki as Claude Code infrastructure.'
relates_to:
- concept: func:parrot.knowledge.wiki.claude_code.cli.claude
  rel: defines
- concept: func:parrot.knowledge.wiki.claude_code.cli.hook
  rel: defines
- concept: func:parrot.knowledge.wiki.claude_code.cli.install
  rel: defines
- concept: func:parrot.knowledge.wiki.claude_code.cli.status
  rel: defines
- concept: func:parrot.knowledge.wiki.claude_code.cli.uninstall
  rel: defines
- concept: mod:parrot.knowledge.wiki.claude_code.hook
  rel: references
- concept: mod:parrot.knowledge.wiki.claude_code.installer
  rel: references
- concept: mod:parrot.knowledge.wiki.cli
  rel: references
- concept: mod:parrot.knowledge.wiki.project
  rel: references
---

# `parrot.knowledge.wiki.claude_code.cli`

``parrot claude`` — install the LLM Wiki as Claude Code infrastructure.

Subcommands:
    install    Wire the repo's wiki into Claude Code (CLAUDE.md
               section, PreToolUse nudge hook, /parrotwiki command,
               git post-commit auto-upsert).
    uninstall  Remove every managed artifact.
    status     Show what is currently installed.
    hook       PreToolUse hook runtime (reads stdin; used internally).

## Functions

- `def claude() -> None` — Claude Code integration for the repository LLM Wiki.
- `def install(path_: Optional[str], git_hook: bool, gitignore: bool, build_now: bool) -> None` — Install the wiki toolkit as Claude Code infrastructure.
- `def uninstall(path_: Optional[str]) -> None` — Remove the Claude Code integration (keeps the wiki plane).
- `def status(path_: Optional[str], as_json: bool) -> None` — Show which integration pieces are installed.
- `def hook() -> None` — PreToolUse hook runtime (reads the payload from stdin).
