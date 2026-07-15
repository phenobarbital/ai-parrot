"""Managed file templates for the Claude Code wiki integration.

Every artifact written by ``parrot claude install`` is delimited by
markers (or identified by the hook command string) so installs are
idempotent and ``parrot claude uninstall`` can remove exactly what was
added without touching user content.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Markers / identifiers
# --------------------------------------------------------------------------

#: Managed-block markers inside CLAUDE.md.
CLAUDE_MD_BEGIN = "<!-- parrot:wiki:begin -->"
CLAUDE_MD_END = "<!-- parrot:wiki:end -->"

#: Hook command written into .claude/settings.json — also the needle
#: used to find (and remove) our hook entries when merging settings.
HOOK_COMMAND = "wikitoolkit claude-hook"

#: Tool matcher for the PreToolUse nudge.
HOOK_MATCHER = "Grep|Glob|Read"

#: Managed-block markers inside .git/hooks/post-commit.
GIT_HOOK_BEGIN = "# >>> parrot-wiki post-commit >>>"
GIT_HOOK_END = "# <<< parrot-wiki post-commit <<<"

#: Filename of the slash command (under .claude/commands/).
SLASH_COMMAND_FILENAME = "parrotwiki.md"

# --------------------------------------------------------------------------
# CLAUDE.md managed section
# --------------------------------------------------------------------------

CLAUDE_MD_SECTION = f"""{CLAUDE_MD_BEGIN}
## Codebase Knowledge Graph (LLM Wiki)

This repository maintains a machine-first knowledge graph of the
codebase (pages + typed edges over a local SQLite plane, built by
`wikitoolkit build`). For questions about the codebase — where
something lives, how modules relate, what a subsystem does — PREFER
scoped wiki queries over reading whole files or grepping raw source:

- `wikitoolkit query "<question>"` — token-budgeted, ranked page
  stubs for a scoped question. Start here.
- `wikitoolkit page <id>` — read one page in full (file summaries,
  API outlines, content). Use the ids returned by `query`.
- `wikitoolkit related <id>` — follow typed edges (`contains`,
  `references`) to neighbouring files/modules.
- `wikitoolkit status` — plane statistics and staleness.
- `wikitoolkit build` — refresh the graph after large changes
  (a git post-commit hook may already keep it fresh).

The `/parrotwiki` command wraps these (e.g. `/parrotwiki query how
does ingest work`, `/parrotwiki --wiki` to export a human-readable
markdown wiki). Fall back to Grep/Glob/Read when the wiki has no
answer, and consider `wikitoolkit build` if results look stale.
{CLAUDE_MD_END}
"""

# --------------------------------------------------------------------------
# /parrotwiki slash command
# --------------------------------------------------------------------------

SLASH_COMMAND_MD = """---
description: Query or maintain the repository LLM-wiki knowledge graph (wikitoolkit)
argument-hint: [query <question> | page <id> | related <id> | status | build | --wiki [dir]]
allowed-tools: Bash(wikitoolkit:*)
---

# /parrotwiki — codebase knowledge graph

Arguments: `$ARGUMENTS`

This repository has an LLM-wiki knowledge base built from the source
tree (see the "Codebase Knowledge Graph" section of CLAUDE.md).
Interpret the arguments as one of the following actions and run the
matching `wikitoolkit` command with Bash:

- `query <question>` — run `wikitoolkit query "<question>"`. Read the
  most promising results with `wikitoolkit page <id>` and answer the
  question citing page ids. Prefer this over grepping raw files.
- `page <id>` — run `wikitoolkit page <id>` and summarise it.
- `related <id>` — run `wikitoolkit related <id>` and explain how the
  neighbours connect.
- `status` — run `wikitoolkit status` and report plane health.
- `build` — run `wikitoolkit build` and report what changed.
- `--wiki [dir]` — build a human-readable markdown wiki from the
  graph: run `wikitoolkit export -o <dir>` (default `docs/wiki`) and
  list what was written.
- no arguments — run `wikitoolkit status` and briefly explain the
  available actions above.

If `wikitoolkit` reports the wiki is not built yet, run
`wikitoolkit build` first, then retry the requested action.
"""

# --------------------------------------------------------------------------
# git post-commit hook block
# --------------------------------------------------------------------------

GIT_HOOK_BLOCK = f"""{GIT_HOOK_BEGIN}
# Keep the LLM-wiki knowledge graph in sync with the last commit.
# Installed by `parrot claude install`; remove with `parrot claude uninstall`.
wikitoolkit upsert --changed --quiet >/dev/null 2>&1 || true
{GIT_HOOK_END}
"""

GIT_HOOK_NEW_FILE = f"""#!/bin/sh
{GIT_HOOK_BLOCK}"""

# --------------------------------------------------------------------------
# PreToolUse nudge (emitted by the hook runtime)
# --------------------------------------------------------------------------

NUDGE_TEXT = (
    "This repository has an LLM-wiki knowledge graph of the codebase. "
    "Before scanning raw files, prefer a scoped query: "
    "`wikitoolkit query \"<question>\"` returns ranked, token-budgeted "
    "page stubs; follow up with `wikitoolkit page <id>` (full page) or "
    "`wikitoolkit related <id>` (typed edges). Fall back to direct "
    "Grep/Glob/Read when the wiki has no answer."
)
