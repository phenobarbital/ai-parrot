# `parrot wiki` & `parrot claude` — LLM Wiki CLI Guide

> A practical reference for the **LLM Wiki** command-line tools (FEAT-260):
> `parrot wiki` builds and queries a machine-first knowledge graph of your
> repository, and `parrot claude` wires that graph into Claude Code so a
> coding assistant consults it instead of grepping raw files.

---

## Table of contents

- [What is the LLM Wiki?](#what-is-the-llm-wiki)
- [Entry points](#entry-points)
- [Quick start](#quick-start)
- [Core concepts](#core-concepts)
- [`parrot wiki` command reference](#parrot-wiki-command-reference)
  - [`build`](#parrot-wiki-build)
  - [`status`](#parrot-wiki-status)
  - [`query`](#parrot-wiki-query)
  - [`page`](#parrot-wiki-page)
  - [`related`](#parrot-wiki-related)
  - [`upsert`](#parrot-wiki-upsert)
  - [`export`](#parrot-wiki-export)
- [Querying an external / pre-built store](#querying-an-external--pre-built-store)
- [Project configuration (`.parrot/wiki.json`)](#project-configuration-parrotwikijson)
- [`parrot claude` command reference](#parrot-claude-command-reference)
  - [`install`](#parrot-claude-install)
  - [`status`](#parrot-claude-status)
  - [`uninstall`](#parrot-claude-uninstall)
  - [What `install` writes](#what-install-writes)
  - [The PreToolUse nudge hook](#the-pretooluse-nudge-hook)
  - [The `/parrotwiki` slash command](#the-parrotwiki-slash-command)
- [Typical workflows](#typical-workflows)
- [How it works under the hood](#how-it-works-under-the-hood)
- [Troubleshooting](#troubleshooting)

---

## What is the LLM Wiki?

Classic code search (grep/glob) re-scans raw files on every question and throws
the work away. The **LLM Wiki** flips that: it compiles your repository **once**
into a durable, cross-linked knowledge plane — one page per source file and
directory, plus typed edges between them — and lets agents ask **scoped,
token-budgeted questions** against it.

The build is **fully offline and deterministic**: no LLM, no embeddings, no
network. It uses Python's `ast` module for API outlines, markdown/rst heading
extraction for docs, and `git ls-files` for `.gitignore`-aware discovery. The
plane is a local **SQLite FTS5/BM25** database.

Two surfaces sit on top of it:

| Tool | Purpose |
| --- | --- |
| **`parrot wiki`** | Build, refresh, and query the knowledge graph (humans + scripts). |
| **`parrot claude`** | Install the wiki as Claude Code infrastructure so the assistant uses it automatically. |

---

## Entry points

The same CLI is exposed three ways:

```bash
parrot wiki <command>       # subcommand of the main parrot CLI
wikitoolkit <command>       # standalone console script (identical to `parrot wiki`)
parrot claude <command>     # the Claude Code integration installer
```

`wikitoolkit` is a thin console-script alias for `parrot wiki`, provided so a
coding assistant can invoke it cheaply (e.g. `wikitoolkit query "..."`). Use
whichever you prefer — they are the same commands.

> If `wikitoolkit` is "command not found" in an existing virtualenv, reinstall
> the package so the console script is registered:
> `uv pip install -e packages/ai-parrot` (or your usual editable install).

---

## Quick start

```bash
# 1. Build the wiki for the current repository (writes to .parrot/wiki/)
parrot wiki build

# 2. Ask a scoped question — returns a token-budgeted context pack
parrot wiki query "how does the agent crew orchestration work"

# 3. Read a full page returned by query
parrot wiki page file:parrot/bots/flows/crew/crew.py

# 4. Walk the graph from that page
parrot wiki related file:parrot/bots/flows/crew/crew.py

# 5. Check plane health / staleness
parrot wiki status

# Prefer a human-friendly table instead of the LLM context pack:
parrot wiki query "pgvector store" --table --body
```

To make Claude Code use the wiki automatically:

```bash
parrot claude install        # builds the plane (if needed) + wires everything
parrot claude status         # see what's installed
```

---

## Core concepts

**Pages.** Every scanned file becomes a `file:` page; every directory becomes a
`dir:` overview page. A page carries a title, a `summary`, a `body`, a
`category`, and a `token_count`.

**Concept ids** are stable and human-readable:

| Kind | Concept id | Example |
| --- | --- | --- |
| File page | `file:<relpath>` | `file:parrot/tools/base.py` |
| Directory page | `dir:<relpath>` | `dir:parrot/tools` |

**Categories:**

| Category | Applies to |
| --- | --- |
| `module` | Source code (`.py`, `.rs`, `.go`, `.ts`, `.sql`, …) |
| `document` | Docs (`.md`, `.rst`, `.txt`) |
| `config` | Config (`.toml`, `.yaml`, `.json`, `.ini`, …) |
| `overview` | Directory overview pages |

**Typed edges:**

| Relation | Meaning |
| --- | --- |
| `contains` | Directory → its child files/subdirectories |
| `references` | Python file → another file it imports (src-layout aware) |

**Storage layout** (default, under the repo root):

```
.parrot/
├── wiki.json          # project configuration (committed or ignored — your call)
└── wiki/
    ├── wiki.db        # SQLite FTS5/BM25 retrieval plane (pages + edges)
    └── sources/       # source manifest (SHA-1 + mtime for incremental upserts)
```

**Python API outline.** For `.py`/`.pyi` files the build extracts a compact API
outline (classes, functions, and their first docstring line) into the page body,
so a single page answers "what does this module expose?" without reading it.

---

## `parrot wiki` command reference

All commands accept `--path TEXT` to point at a repo root explicitly; by default
the root is auto-detected by walking up to the nearest `.parrot/wiki.json` (or,
failing that, the nearest `.git`).

### `parrot wiki build`

Generate or refresh the knowledge graph from the current repository. Deterministic
and offline; respects `.gitignore` via `git ls-files`.

```
parrot wiki build [OPTIONS]
```

| Option | Default | Description |
| --- | --- | --- |
| `--path TEXT` | auto-detect | Repo root. |
| `--name TEXT` | repo dir name | Wiki name. |
| `--backend [sqlite\|memory]` | `sqlite` | Retrieval-plane backend. |
| `--force` | off | Re-ingest every file, ignoring staleness. |
| `--no-git` | off | Use a filesystem walk instead of `git ls-files`. |
| `-q, --quiet` | off | Print only the final summary line. |

**Incremental by default.** Re-running `build` re-ingests only files whose
content hash or mtime changed since the last build; unchanged files are skipped.
Deleted or newly-ignored files have their pages pruned. Use `--force` to rebuild
everything.

```bash
parrot wiki build
parrot wiki build --name my-service --backend sqlite
parrot wiki build --force            # full rebuild
```

Example output:

```
Wiki 'ai-parrot' built at /repo/.parrot/wiki — 1756 ingested, 0 unchanged,
0 removed; 2202 pages, 6260 edges.
```

### `parrot wiki status`

Show plane statistics and source staleness.

```
parrot wiki status [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--path TEXT` | Repo root. |
| `--json` | Emit raw JSON. |

```bash
parrot wiki status
parrot wiki status --json
```

Reports page/edge/token counts, category breakdown, number of tracked sources,
and how many are stale (changed since the last build). Stale sources are a hint
to re-run `parrot wiki build`.

### `parrot wiki query`

Scoped question against the codebase KB (lexical BM25 search). This is the
primary entry point.

```
parrot wiki query [OPTIONS] QUESTION
```

| Option | Default | Description |
| --- | --- | --- |
| `--path TEXT` | auto-detect | Repo root. |
| `-n, --top-k INTEGER` | `12` | Max results to rank. |
| `--budget INTEGER` | `1200` | Token budget for the packed context. |
| `--category TEXT` | — | Filter by page category (`module`, `document`, …). |
| `--store TEXT` | — | Query a pre-built store directly (see [below](#querying-an-external--pre-built-store)). |
| `--backend [sqlite\|memory]` | `sqlite` | Backend for `--store`. |
| `--table` | off | Render a human-facing Rich table instead of the context pack. |
| `-b, --body` | off | Also fetch/render the full body of the top-ranked page. |
| `--json` | off | Emit raw JSON results. |

**Three output modes:**

- **Default (context pack)** — a token-budgeted block of ranked page stubs
  optimized for feeding to an LLM. Respects `--budget`.
- **`--table`** — a human-readable Rich table (`#`, Score, Category, Title,
  Summary). Add `--body` to also print the top hit's full body.
- **`--json`** — raw ranked rows (with normalized `[0,1]` scores) for scripting.

```bash
parrot wiki query "where is retry logic handled"
parrot wiki query "vector store" --category module --top-k 5
parrot wiki query "agent crew orchestration" --table --body
parrot wiki query "memory redis" --json | jq '.[0].concept_id'
```

If there are no hits, the command prints a friendly message suggesting a rebuild
or falling back to code search, and exits 0.

### `parrot wiki page`

Read one wiki page in full (progressive disclosure) — use the ids returned by
`query`.

```
parrot wiki page [OPTIONS] PAGE_ID
```

| Option | Description |
| --- | --- |
| `--path TEXT` | Repo root. |
| `--max-tokens INTEGER` | Truncate the body to roughly this many tokens. |
| `--store TEXT` | Read from a pre-built store directly. |
| `--backend [sqlite\|memory]` | Backend for `--store`. |
| `--json` | Emit raw JSON. |

```bash
parrot wiki page file:parrot/tools/base.py
parrot wiki page dir:parrot/tools --max-tokens 500
```

### `parrot wiki related`

List pages linked to `PAGE_ID` by typed edges.

```
parrot wiki related [OPTIONS] PAGE_ID
```

| Option | Default | Description |
| --- | --- | --- |
| `--path TEXT` | auto-detect | Repo root. |
| `--rel TEXT` | — | Filter by edge relation (e.g. `contains`, `references`). |
| `--direction [out\|in\|both]` | `both` | Edge direction to follow. |
| `--store TEXT` | — | Read from a pre-built store directly. |
| `--backend [sqlite\|memory]` | `sqlite` | Backend for `--store`. |
| `--json` | off | Emit raw JSON. |

```bash
parrot wiki related file:parrot/bots/agent.py --rel references --direction out
parrot wiki related dir:parrot/tools --rel contains
```

Output uses `→` for outgoing and `←` for incoming edges.

### `parrot wiki upsert`

Incrementally re-ingest specific files (or the files touched by the last git
commit). This is what the installed git `post-commit` hook runs.

```
parrot wiki upsert [OPTIONS] [PATHS]...
```

| Option | Description |
| --- | --- |
| `--path TEXT` | Repo root. |
| `--changed` | Upsert the files touched by the **last git commit** (merge-safe). |
| `-q, --quiet` | Suppress output (for git hooks). |

```bash
parrot wiki upsert parrot/tools/new_tool.py
parrot wiki upsert --changed          # what the post-commit hook calls
```

Deleted files have their pages removed. Directory overview pages are refreshed by
the next full `parrot wiki build`. `--changed` correctly handles **merge
commits** (it reports files relative to the first parent), so a `git merge`
doesn't leave the wiki stale.

### `parrot wiki export`

Export the wiki as a human-readable markdown bundle (one file per page with YAML
frontmatter, plus a root `index.md`).

```
parrot wiki export [OPTIONS]
```

| Option | Default | Description |
| --- | --- | --- |
| `--path TEXT` | auto-detect | Repo root. |
| `-o, --output TEXT` | `docs/wiki` | Output directory (relative to root). |

```bash
parrot wiki export
parrot wiki export -o site/kb
```

The export directory is automatically added to the wiki's `exclude_dirs` so the
next build does not ingest its own exported markdown back into itself.

---

## Querying an external / pre-built store

By default the read commands (`query`, `page`, `related`) resolve the plane from
`.parrot/wiki.json`. You can instead point them at **any** pre-built wiki store
directory with `--store`, or the `WIKI_STORE` environment variable:

```bash
# Explicit store directory
parrot wiki query "agent crew" --store docs/parrot --table

# Via environment (also honours .env through navconfig)
export WIKI_STORE=docs/parrot
export WIKI_STORE_BACKEND=sqlite      # optional, defaults to sqlite
parrot wiki query "agent crew"
```

This is useful for querying a richer, separately-built bundle — for example the
GraphIndex-enriched wiki produced by `scripts/build_llm_wiki.py` under
`docs/parrot/` — without touching the project's own `.parrot/wiki` plane. The
store format is identical (`SQLiteWikiStore` / FTS5), so `query`, `page`, and
`related` all work against it.

Resolution precedence for `--store` / `--backend`:

```
--store flag  >  WIKI_STORE env  >  project .parrot/wiki.json plane
--backend flag >  WIKI_STORE_BACKEND env  >  sqlite
```

---

## Project configuration (`.parrot/wiki.json`)

`parrot wiki build` and `parrot claude install` create `.parrot/wiki.json` at the
repo root. It records where the plane lives and how the repo is scanned, and is
what the Claude Code hook reads to find the wiki.

```json
{
  "wiki_name": "ai-parrot",
  "storage_dir": ".parrot/wiki",
  "backend": "sqlite",
  "include_suffixes": [],
  "exclude_dirs": [],
  "body_max_chars": 16000,
  "max_file_kb": 512,
  "claude": {
    "nudge_cooldown_seconds": 300,
    "nudge_tools": ["Grep", "Glob", "Read"]
  }
}
```

| Field | Default | Description |
| --- | --- | --- |
| `wiki_name` | repo dir name | Wiki identifier. |
| `storage_dir` | `.parrot/wiki` | Plane storage directory (relative to root, or absolute). |
| `backend` | `sqlite` | `sqlite` or `memory`. |
| `include_suffixes` | `[]` (scanner defaults) | File suffixes to scan. Empty = built-in code/doc/config set. |
| `exclude_dirs` | `[]` | Extra directories to prune. Bare name (`vendor`) prunes any dir of that name; a path with `/` (`docs/wiki`) prunes that prefix only. |
| `body_max_chars` | `16000` | Cap on stored page body length (≈ 4k tokens). |
| `max_file_kb` | `512` | Skip files larger than this many KiB. |
| `claude.nudge_cooldown_seconds` | `300` | Minimum seconds between two PreToolUse nudges. `0` disables throttling. |
| `claude.nudge_tools` | `["Grep","Glob","Read"]` | Tool names the nudge applies to. |

**Default exclusions** (always pruned): `.git`, `.venv`, `venv`, `node_modules`,
`build`, `dist`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`,
`.parrot`, `.claude`, `.worktrees`, and common lockfiles.

---

## `parrot claude` command reference

Install the LLM Wiki as **Claude Code infrastructure** so the assistant prefers
scoped wiki queries over grepping raw files, and keeps the graph fresh on every
commit.

### `parrot claude install`

```
parrot claude install [OPTIONS]
```

| Option | Default | Description |
| --- | --- | --- |
| `--path TEXT` | auto-detect | Repo root. |
| `--git-hook / --no-git-hook` | `--git-hook` | Install a git `post-commit` hook that upserts the wiki. |
| `--gitignore / --no-gitignore` | `--gitignore` | Add `.parrot/` to `.gitignore`. |
| `--build / --no-build` | `--build` | Build the wiki plane now if it doesn't exist yet. |

```bash
parrot claude install
parrot claude install --no-git-hook          # skip the auto-upsert hook
parrot claude install --no-build             # wire only; build later
```

Every step is **idempotent and marker-based** — re-running `install` updates only
what changed, and never clobbers your existing content.

### `parrot claude status`

```
parrot claude status [OPTIONS]      # --path TEXT, --json
```

Reports which integration pieces are currently installed (config, built plane,
CLAUDE.md section, PreToolUse hook, `/parrotwiki` command, git post-commit hook).

### `parrot claude uninstall`

```
parrot claude uninstall [OPTIONS]   # --path TEXT
```

Removes **only** the managed artifacts it installed (identified by markers),
leaving `.parrot/wiki.json` and the wiki plane itself in place.

### What `install` writes

| Artifact | Purpose |
| --- | --- |
| `.parrot/wiki.json` | Wiki config (created if absent). |
| **`CLAUDE.md`** (managed section) | Tells the assistant to prefer `wikitoolkit query "<question>"` over grepping. Delimited by `<!-- parrot:wiki:begin -->` … `<!-- parrot:wiki:end -->`. |
| **`.claude/settings.json`** (PreToolUse hook) | Merges a nudge hook (matcher `Grep\|Glob\|Read` → `wikitoolkit claude-hook`) into the existing settings without disturbing other hooks. |
| **`.claude/commands/parrotwiki.md`** | The `/parrotwiki` slash command. |
| **`.git/hooks/post-commit`** (optional) | Chained hook running `wikitoolkit upsert --changed --quiet` after each commit. Worktree-aware; skipped if an existing hook is not a POSIX-sh script. |
| **`.gitignore`** (optional) | Adds `.parrot/` (the local retrieval plane). |

### The PreToolUse nudge hook

Before search-style tool calls (`Grep`, `Glob`, `Read`), Claude Code invokes
`wikitoolkit claude-hook`. The hook:

- **Never blocks** — it emits *context only* (`additionalContext`), no permission
  decision, so the normal flow is untouched.
- **Never breaks the session** — any error exits 0 silently.
- **Is throttled** — at most one nudge per cooldown window (default 300 s,
  configurable via `claude.nudge_cooldown_seconds`), using atomic per-window
  stamp files so parallel tool calls don't spam.
- **Is scoped** — only fires when a built wiki exists; `Read` nudges only for
  source/doc files.

The nudge steers the assistant toward `wikitoolkit query "<question>"` before it
scans raw files.

### The `/parrotwiki` slash command

Inside Claude Code, `/parrotwiki` wraps the CLI:

```
/parrotwiki query how does ingest work
/parrotwiki page file:parrot/loaders/base.py
/parrotwiki related dir:parrot/tools
/parrotwiki status
/parrotwiki build
/parrotwiki --wiki [dir]      # export a human-readable markdown wiki
```

---

## Typical workflows

**Set up a coding assistant (recommended):**

```bash
parrot claude install         # builds the plane + wires CLAUDE.md, hook, command
parrot claude status          # verify
# Now Claude Code auto-consults the wiki; the post-commit hook keeps it fresh.
```

**Manual / scripted use (no Claude Code):**

```bash
parrot wiki build
parrot wiki query "how are tools registered" --json | jq -r '.[].concept_id'
parrot wiki page file:parrot/tools/__init__.py
```

**Keep it fresh:**

- With the git hook installed, every commit runs `wiki upsert --changed`.
- After large refactors or merges, run a full `parrot wiki build`.
- `parrot wiki status` flags stale sources.

**Query a richer external bundle:**

```bash
parrot wiki query "AgentsFlow DAG executor" --store docs/parrot --table --body
```

---

## How it works under the hood

- **Deterministic & offline.** No LLM/embeddings/network at build time. Python
  API outlines come from `ast`; discovery uses `git ls-files` (with a filesystem
  fallback under `--no-git`).
- **Incremental.** A source manifest tracks SHA-1 + mtime per file; unchanged
  files are skipped on rebuild. Re-ingesting a file atomically replaces its slice
  while preserving incoming edges to its stable `concept_id`.
- **Merge-safe refresh.** `wiki upsert --changed` uses `git diff-tree
  -m --first-parent`, so files introduced by a merge commit are re-ingested (a
  plain diff would report nothing for merges).
- **Machine-first retrieval.** BM25 over title/summary/body, scores normalized to
  `[0,1]`, packed to a token budget for LLM consumption.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Wiki not built yet` | Run `parrot wiki build`. |
| `wikitoolkit: command not found` | Reinstall the package so the console script registers (`uv pip install -e packages/ai-parrot`), or use `parrot wiki`. |
| `No wiki project found` | Run inside a repo (with `.git` or `.parrot/wiki.json`) or pass `--path`. |
| `No wiki database at <dir>/wiki.db` (with `--store`) | The store directory has no built plane — build it or point `--store` elsewhere. |
| Results look stale | Re-run `parrot wiki build`; check `parrot wiki status` for stale sources. |
| Existing `post-commit` hook not chained | It isn't a POSIX-sh script — add `wikitoolkit upsert --changed --quiet` to it manually. |
| Query returns nothing | Try broader terms, drop `--category`, or rebuild; fall back to code search. |

---

*Part of AI-Parrot (FEAT-260). Source: `parrot/knowledge/wiki/` — CLI in
`cli.py`, Claude Code integration in `claude_code/`.*
