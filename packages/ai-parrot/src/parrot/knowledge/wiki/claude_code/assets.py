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

#: Tool matcher for the PreToolUse nudge. Includes ``Bash`` so shell-based
#: searches (``grep``/``rg``/``find`` run via the Bash tool) are nudged too —
#: the hook decides per-command whether a given Bash call is actually a
#: repo search (see ``hook._should_nudge_bash``).
HOOK_MATCHER = "Grep|Glob|Read|Bash"

#: Managed-block markers inside .git/hooks/post-commit.
GIT_HOOK_BEGIN = "# >>> parrot-wiki post-commit >>>"
GIT_HOOK_END = "# <<< parrot-wiki post-commit <<<"

#: Permission allow-rules merged into .claude/settings.json so wiki
#: queries run without a permission prompt. Covers the bare CLI, the
#: ``parrot wiki`` alias, and the common venv-activation compound.
PERMISSION_RULES: tuple[str, ...] = (
    "Bash(wikitoolkit:*)",
    "Bash(parrot wiki:*)",
    "Bash(source .venv/bin/activate && wikitoolkit:*)",
    "Bash(source .venv/bin/activate && parrot wiki:*)",
)

#: Filename of the slash command (under .claude/commands/).
SLASH_COMMAND_FILENAME = "parrotwiki.md"

# --------------------------------------------------------------------------
# CLAUDE.md managed section
# --------------------------------------------------------------------------

CLAUDE_MD_SECTION = f"""{CLAUDE_MD_BEGIN}
## Codebase Knowledge Graph (LLM Wiki)

This repository maintains a machine-first knowledge graph of the
codebase (pages + typed edges over a local SQLite plane, built by
`wikitoolkit build`). For ANY question about the codebase — where
something lives, how modules relate, what a subsystem does — you MUST
run a scoped wiki query FIRST, before Grep/Glob/Read or any shell
search (`grep`/`rg`/`find`/`cat` via Bash):

- `wikitoolkit query "<question>"` — token-budgeted, ranked page
  stubs for a scoped question. ALWAYS start here.
- `wikitoolkit page <id>` — read one page in full (file summaries,
  API outlines, content). Use the ids returned by `query`.
- `wikitoolkit related <id>` — follow typed edges (`contains`,
  `references`) to neighbouring files/modules.
- `wikitoolkit status` — plane statistics and staleness.
- `wikitoolkit build` — refresh the graph after large changes
  (a git post-commit hook may already keep it fresh).

**Query discipline** (avoids the two most common ways the wiki
"fails" — which are usually caller error, not missing coverage):

1. **Query for the *thing*, not for your *hypothesis* about it.** The
   ranking is lexical — extra concept words steer it toward those
   concepts. To locate a class or feature, name the symbol/module/
   subsystem you want (`"attestation model service"`), not your theory
   about where it might live.
2. **Follow the thread before falling back.** If a result scores low
   or names a parent module, resolve it with `wikitoolkit page <id>`
   or `wikitoolkit related <id>` — one hop usually lands the real
   page. Do NOT jump to grep just because the first `query` didn't
   rank the exact page first.

Only fall back to Grep/Glob/Read (or shell search) once a clean query
*and* a page/related follow-up have genuinely come up empty — and say
so before you do. Consider `wikitoolkit build` if results look stale.

The `/parrotwiki` command wraps these (e.g. `/parrotwiki query how
does ingest work`, `/parrotwiki --wiki` to export a human-readable
markdown wiki).
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
    "STOP — this repository has an LLM-wiki knowledge graph and CLAUDE.md "
    "requires querying it BEFORE raw file scans (Grep/Glob/Read or "
    "grep/rg/find via Bash). Run `wikitoolkit query \"<question>\"` first "
    "(ranked, token-budgeted page stubs), then `wikitoolkit page <id>` / "
    "`wikitoolkit related <id>` to drill in. Only fall back to raw search "
    "after a query AND a page/related follow-up came up empty."
)
