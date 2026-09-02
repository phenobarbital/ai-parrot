"""Managed file templates for the Claude Code wiki integration.

Every artifact written by ``parrot claude install`` is delimited by
markers (or identified by the hook command string) so installs are
idempotent and ``parrot claude uninstall`` can remove exactly what was
added without touching user content.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.mcp.toolkit_config import ToolkitSection

# --------------------------------------------------------------------------
# Markers / identifiers
# --------------------------------------------------------------------------

#: Managed-block markers inside CLAUDE.md.
CLAUDE_MD_BEGIN = "<!-- parrot:wiki:begin -->"
CLAUDE_MD_END = "<!-- parrot:wiki:end -->"

#: Hook command written into .claude/settings.json — also the needle
#: used to find (and remove) our hook entries when merging settings.
#: When the installer can resolve an absolute path to the binary, the
#: full path replaces the bare name (worktrees don't inherit the venv's
#: ``$PATH``, so the bare name would fail there).  This constant is
#: still the *identification needle* used by ``_is_our_hook`` — it is
#: always a substring of the resolved command.
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
    # FEAT-498: structural-plane MCP tools (read-only, same trust level
    # as the other wikitoolkit MCP tools).
    "mcp__wikitoolkit__wiki_symbol_lookup",
    "mcp__wikitoolkit__wiki_code_outline",
    "mcp__wikitoolkit__wiki_blast_radius",
)

#: Filename of the slash command (under .claude/commands/).
SLASH_COMMAND_FILENAME = "parrotwiki.md"

#: Default .mcp.json entry for the wikitoolkit MCP stdio server (FEAT-403).
#: The installer replaces ``"wikitoolkit"`` with the resolved absolute
#: path via :func:`mcp_json_entry` so the server starts in worktrees too.
MCP_JSON_ENTRY: dict = {
    "command": "wikitoolkit",
    "args": ["mcp"],
    "env": {},
}


# --------------------------------------------------------------------------
# Binary resolution — used by the installer to write absolute paths
# --------------------------------------------------------------------------


def resolve_wikitoolkit_bin(root: Path) -> str:
    """Return the absolute path to the ``wikitoolkit`` binary.

    Resolution order:

    1. ``<root>/.venv/bin/wikitoolkit`` — the project venv (most common
       with ``uv`` / ``pip install -e .``).
    2. ``shutil.which("wikitoolkit")`` — globally installed or on
       ``$PATH`` at install time.
    3. Bare ``"wikitoolkit"`` — fallback; works only when the venv is
       activated at hook-execution time.
    """
    venv_bin = root / ".venv" / "bin" / "wikitoolkit"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("wikitoolkit")
    if found:
        return found
    return "wikitoolkit"


def hook_command(root: Path) -> str:
    """Build the ``PreToolUse`` hook command with an absolute path."""
    return f"{resolve_wikitoolkit_bin(root)} claude-hook"


def mcp_json_entry(root: Path) -> dict:
    """Build the ``.mcp.json`` entry with an absolute path."""
    return {
        "command": resolve_wikitoolkit_bin(root),
        "args": ["mcp"],
        "env": {},
    }


def resolve_parrot_bin(root: Path) -> str:
    """Return the absolute path to the ``parrot`` binary.

    Mirrors :func:`resolve_wikitoolkit_bin`'s resolution order:

    1. ``<root>/.venv/bin/parrot`` — the project venv (most common with
       ``uv`` / ``pip install -e .``).
    2. ``shutil.which("parrot")`` — globally installed or on ``$PATH`` at
       install time.
    3. Bare ``"parrot"`` — fallback; works only when the venv is activated
       at invocation time (e.g. the MCP host activates it before spawning
       the process).
    """
    venv_bin = root / ".venv" / "bin" / "parrot"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("parrot")
    if found:
        return found
    return "parrot"


def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:
    """Build the ``.mcp.json`` entry for one exposed toolkit (FEAT-485).

    Args:
        root: Project root — used to resolve the ``parrot`` binary.
        name: Toolkit name (e.g. ``"scraping"``) as it appears under
            ``.parrot/mcp-toolkits.yaml``'s ``toolkits:`` mapping.
        section: The toolkit's resolved config section, for its ``env``
            mapping.

    Returns:
        ``{"command": <abs parrot bin>, "args": ["mcp-local", name],
        "env": dict(section.env)}``.
    """
    return {
        "command": resolve_parrot_bin(root),
        "args": ["mcp-local", name],
        "env": dict(section.env),
    }


def git_hook_block(root: Path) -> str:
    """Build the ``post-commit`` hook block with an absolute path."""
    wt_bin = resolve_wikitoolkit_bin(root)
    return (
        f"{GIT_HOOK_BEGIN}\n"
        f"# Keep the LLM-wiki knowledge graph in sync with the last commit.\n"
        f"# Installed by `parrot claude install`; "
        f"remove with `parrot claude uninstall`.\n"
        f"{wt_bin} upsert --changed --quiet >/dev/null 2>&1 || true\n"
        f"{GIT_HOOK_END}\n"
    )


def git_hook_new_file(root: Path) -> str:
    """Build a fresh ``post-commit`` hook file with an absolute path."""
    return f"#!/bin/sh\n{git_hook_block(root)}"


def permission_rules(root: Path) -> tuple[str, ...]:
    """Return permission rules including absolute-path variants.

    Extends the static :data:`PERMISSION_RULES` with rules that match
    the resolved binary path so wiki commands work in worktrees (where
    ``wikitoolkit`` is not on ``$PATH``).
    """
    resolved = resolve_wikitoolkit_bin(root)
    if resolved == "wikitoolkit":
        return PERMISSION_RULES
    return PERMISSION_RULES + (f"Bash({resolved}:*)",)


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

These same operations are also exposed as native MCP tools —
`wiki_query`, `wiki_page`, `wiki_related`, `wiki_remember`, `wiki_note`,
`wiki_status` — via the `wikitoolkit` MCP stdio server registered in
this repo's `.mcp.json` (FEAT-403). If they appear in your tool list,
prefer calling them directly; they have equal standing with Grep/Read
at tool-selection time instead of competing via a Bash-invoked CLI.

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

**Saving knowledge (persistent memory).** The wiki is also your
durable memory — what you save here survives this session and is
found by future `wikitoolkit query` calls ("the agent forgets, the
graph does not"). When you learn a durable fact, make a decision, or
extract a lesson worth keeping, SAVE it:

- `wikitoolkit remember "<fact>" --category [note|decision|lesson|concept]
  [--title "<short title>"] [--link <page_id> --rel <relation>]` —
  file new knowledge (idempotent: same title+category updates the
  existing memory). Link it to the pages it is about.
- `wikitoolkit note <page_id> "<text>"` — append an attributed,
  dated note to an existing page.
- `wikitoolkit link <src_id> <dst_id> --rel <relation>` — connect
  two pages with a typed, asserted edge.
- `wikitoolkit memories` — list saved memories;
  `wikitoolkit audit` — the attributed write log.

Save selectively: durable decisions, gotchas, and cross-file
relationships — not session chatter. Every write is attributed and
auditable.

The `/parrotwiki` command wraps these (e.g. `/parrotwiki query how
does ingest work`, `/parrotwiki remember <fact>`, `/parrotwiki --wiki`
to export a human-readable markdown wiki).
{CLAUDE_MD_END}
"""

# --------------------------------------------------------------------------
# /parrotwiki slash command
# --------------------------------------------------------------------------

SLASH_COMMAND_MD = """---
description: Query or maintain the repository LLM-wiki knowledge graph (wikitoolkit)
argument-hint: [query <question> | page <id> | related <id> | remember <fact> | note <id> <text> | link <a> <b> | memories | audit | status | build | --wiki [dir]]
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
- `remember <fact>` — save durable knowledge: run
  `wikitoolkit remember "<fact>" --category <note|decision|lesson|concept>`
  (add `--title` for a short handle and `--link <page_id>` to connect
  it to the pages it is about). Report the saved page id.
- `note <id> <text>` — run `wikitoolkit note <id> "<text>"` to append
  an attributed note to an existing page.
- `link <a> <b>` — run `wikitoolkit link <a> <b> --rel <relation>`
  to connect two pages (default relation `references`).
- `memories` — run `wikitoolkit memories` and summarise what has
  been saved.
- `audit` — run `wikitoolkit audit` and summarise recent writes.
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
    'grep/rg/find via Bash). Run `wikitoolkit query "<question>"` first '
    "(ranked, token-budgeted page stubs), then `wikitoolkit page <id>` / "
    "`wikitoolkit related <id>` to drill in. Only fall back to raw search "
    "after a query AND a page/related follow-up came up empty."
)
