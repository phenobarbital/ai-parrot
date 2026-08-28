# LLM Wiki — Complete Guide

> The definitive guide to AI-Parrot's machine-first knowledge graph: build it,
> query it, teach it what you know, federate multiple corpora, and wire it into
> Claude Code, Codex, and Gemini so every coding session starts smarter.

---

## Table of Contents

- [What Is LLM Wiki](#what-is-llm-wiki)
- [Quick Start](#quick-start)
- [Building the Wiki](#building-the-wiki)
  - [Repository Scan (default)](#repository-scan-default)
  - [Obsidian Vault Scan](#obsidian-vault-scan)
  - [Incremental Updates](#incremental-updates)
- [Querying](#querying)
  - [query — Search the Knowledge Graph](#query-search-the-knowledge-graph)
  - [page — Read a Full Page](#page-read-a-full-page)
  - [related — Follow Typed Edges](#related-follow-typed-edges)
  - [status — Check Graph Health](#status-check-graph-health)
- [Persistent Memory](#persistent-memory)
  - [remember — Save Durable Knowledge](#remember-save-durable-knowledge)
  - [note — Annotate an Existing Page](#note-annotate-an-existing-page)
  - [link — Connect Two Pages](#link-connect-two-pages)
  - [memories — List Saved Knowledge](#memories-list-saved-knowledge)
  - [audit — Review the Write Log](#audit-review-the-write-log)
- [Coding Assistant Integration](#coding-assistant-integration)
  - [Claude Code](#claude-code)
  - [Codex (OpenAI)](#codex-openai)
  - [Gemini (Google)](#gemini-google)
  - [MCP Server (Native Tools)](#mcp-server-native-tools)
- [Git Hooks — Auto-Refresh on Commit](#git-hooks-auto-refresh-on-commit)
- [Namespaces — Multi-Wiki Federation](#namespaces-multi-wiki-federation)
  - [Namespace Kinds](#namespace-kinds)
  - [Registering a Namespace](#registering-a-namespace)
  - [Querying Across Namespaces](#querying-across-namespaces)
  - [How Federation Works](#how-federation-works)
- [Obsidian Vaults as Wiki Sources](#obsidian-vaults-as-wiki-sources)
- [Document Ingestion](#document-ingestion)
  - [Supervised Ingestion (wikitoolkit ingest)](#supervised-ingestion-wikitoolkit-ingest)
  - [Jira Ticket Extraction (wikitoolkit ingest-jira)](#jira-ticket-extraction-wikitoolkit-ingest-jira)
- [Storage Backends](#storage-backends)
  - [SQLite (default)](#sqlite-default)
  - [ArangoDB](#arangodb)
  - [InMemory / OKF Bundle](#inmemory-okf-bundle)
  - [Backend Comparison](#backend-comparison)
- [Exporting the Wiki](#exporting-the-wiki)
- [Configuration Reference](#configuration-reference)
  - [Project Config (.parrot/wiki.json)](#project-config-parrotwikijson)
  - [Environment Variables](#environment-variables)
- [CLI Reference](#cli-reference)
- [Architecture](#architecture)

---

## What Is LLM Wiki

Classic RAG re-synthesizes an answer from raw text on every query and throws
the work away. An **LLM Wiki** (after Andrej Karpathy's framing) flips that:
the system compiles sources into **durable, cross-linked pages** and **files
its own knowledge back** into the repository. Each conversation can leave the
knowledge base *better than it found it*.

AI-Parrot's LLM Wiki is a **machine-first knowledge graph** built from your
codebase, documents, Obsidian vaults, and Jira tickets. It stores:

- **Pages** — one per source file, directory, document, ticket, or memory.
  Each has a concept ID, category, summary, body, and token count.
- **Typed edges** — `contains`, `references`, `embeds`, `tagged`, `defines`,
  `extends`, `mentions`, `explains`.
- **Full-text search** — BM25-ranked retrieval via FTS5 (SQLite) or
  ArangoSearch (ArangoDB).
- **Vector embeddings** — optional per-page embeddings for semantic re-ranking.

The CLI is `wikitoolkit` (also available as `parrot wiki`). It runs
**deterministically and offline** — no LLM, no API key, no network for the
default build path.

---

## Quick Start

```bash
# 1. Build the knowledge graph from the current repo (offline, no LLM)
wikitoolkit build

# 2. Install the coding-assistant integration (Claude Code)
parrot claude install

# 3. Query it
wikitoolkit query "how does the ingest pipeline work?"
wikitoolkit page file:parrot/knowledge/wiki/cli.py
wikitoolkit related file:parrot/knowledge/wiki/cli.py

# 4. Save something you learned
wikitoolkit remember "The sweep watermark lives in .parrot/jira_sync.json" \
  --category decision --link file:parrot/knowledge/wiki/jira_sync.py
```

From now on, every `git commit` auto-refreshes the graph via the post-commit
hook, and every Claude Code session consults it before grepping raw files.

---

## Building the Wiki

### Repository Scan (default)

```bash
wikitoolkit build
```

Scans the repository deterministically — no LLM, no embeddings, no network —
and writes the wiki plane under `.parrot/wiki/`:

- One **`file:<path>` page** per source file: extracted summary (module
  docstring / first heading), a Python **API outline** (classes, functions,
  docstrings via `ast`), and the content head for lexical search.
- One **`dir:<path>` overview page** per directory, listing children.
- **`contains` edges** (directory → file) and **`references` edges** between
  Python files derived from their imports (src-layouts resolve correctly).

File discovery respects `.gitignore` (via `git ls-files`), skips binaries,
lockfiles, and oversized files. Re-builds are incremental: sources are tracked
with SHA-1 + mtime, so unchanged files are skipped and deleted files are
pruned.

#### Language support

The scanner produces API outlines for:

| Language | Method |
|----------|--------|
| Python | `ast`-based (built-in) |
| JavaScript / TypeScript | tree-sitter |
| Rust | tree-sitter |
| PHP | tree-sitter |
| Perl | tree-sitter |

Other file types get a summary (first heading / docstring) and content body
only.

#### Build options

```
wikitoolkit build [OPTIONS]

  --path DIR            Repo root (auto-detected)
  --name TEXT           Wiki name (default: repo directory name)
  --backend TEXT        sqlite | memory | arangodb (default: sqlite)
  --force               Re-ingest every file, ignoring staleness
  --no-git              Do not use git for file discovery
  --vault / --no-vault  Force Obsidian vault mode (auto-detected via .obsidian/)
  --no-export           Skip OKF markdown bundle export
  --no-graph            Skip graph.html / graph.json generation
  --graph-kinds TEXT    Page categories in graph.html (default: module,document,overview)
  -q, --quiet           Only the final summary line
```

Build also produces:
- **OKF markdown bundle** (`index.md` + per-page files) — human-browsable
- **Interactive graph** (`graph.html` / `graph.json`) — visual knowledge map
- **Build report** (`wiki_stats.json`) — statistics and language breakdown

### Obsidian Vault Scan

When the target directory contains `.obsidian/`, the build switches to
**vault mode** automatically (or force it with `--vault`):

```bash
# Auto-detected (has .obsidian/)
wikitoolkit build --path ~/vaults/my-notes

# Forced
wikitoolkit build --vault --path ~/some/markdown/folder
```

Vault scan produces:
- One `file:<relpath>` page per `.md` note
- `[[wikilink]]` → `references` edges
- `![[embed]]` → `embeds` edges
- `#tag` → `tagged` edges + `tag:<tagname>` tag pages
- Folder containment → `contains` edges

Excluded directories: `.obsidian`, `.trash`, `.git`, `.hg`, `.svn`, `.parrot`.

See [Obsidian Vaults as Wiki Sources](#obsidian-vaults-as-wiki-sources) for
more details.

### Incremental Updates

```bash
# Update specific files
wikitoolkit upsert path/to/file.py path/to/other.py

# Update files changed in the last commit (used by the git hook)
wikitoolkit upsert --changed

# Quiet mode (for hooks)
wikitoolkit upsert --changed --quiet
```

The `upsert` command:
- Gets changed files via `git diff-tree HEAD` (handles merge commits)
- Filters through the same relevance checks as full build
- Removes pages for deleted files
- Waits up to 3 seconds for the write lock (skips if a full build is running)

---

## Querying

### query — Search the Knowledge Graph

```bash
wikitoolkit query "how does the ingest pipeline work?"
```

Returns ranked, token-budgeted page stubs — enough context to decide which
pages to read in full, without dumping entire files into your context.

```
wikitoolkit query QUESTION [OPTIONS]

  -n, --top-k INT      Max results to rank (default: 12)
  --budget INT          Token budget for packed context (default: 1200)
  --category TEXT       Filter by page category
  --ns TEXT             Namespace: a name, comma-list, "all", or "local"
  --body / -b           Also fetch the full body of the top-ranked page
  --table               Render a human-facing Rich table
  --json                Emit raw JSON results
  --store DIR           Read a pre-built store directly
  --backend TEXT        Backend for --store (default: sqlite)
```

### page — Read a Full Page

```bash
wikitoolkit page file:parrot/knowledge/wiki/cli.py
```

Progressive disclosure: read one page in full (file summary, API outline,
content).

```
wikitoolkit page PAGE_ID [OPTIONS]

  --max-tokens INT      Truncate the body to roughly this many tokens
  --ns TEXT             Namespace selector
  --json                Emit raw JSON
  --store DIR           Read a pre-built store directly
  --backend TEXT        Backend for --store
```

Page IDs may carry a namespace prefix: `issues::file:NAV-9372.md`,
`notes::file:Retro.md`. Local IDs stay bare.

### related — Follow Typed Edges

```bash
wikitoolkit related file:parrot/knowledge/wiki/cli.py
wikitoolkit related file:parrot/knowledge/wiki/cli.py --rel contains --direction out
```

Walks the graph from a page along typed edges.

```
wikitoolkit related PAGE_ID [OPTIONS]

  --rel TEXT            Filter by edge relation (e.g. contains, references)
  --direction TEXT      out | in | both (default: both)
  --ns TEXT             Namespace selector
  --json                Emit raw JSON
  --store DIR           Read a pre-built store directly
  --backend TEXT        Backend for --store
```

### status — Check Graph Health

```bash
wikitoolkit status
```

Reports: wiki name, backend, storage dir, page/edge/token counts, categories,
language breakdown, tracked/stale sources, and registered namespaces.

```
wikitoolkit status [OPTIONS]

  --ns TEXT             Namespace selector
  --json                Emit raw JSON
```

---

## Persistent Memory

The wiki is also your **durable memory** — what you save here survives sessions
and is found by future `wikitoolkit query` calls. The agent forgets; the graph
does not.

### remember — Save Durable Knowledge

```bash
# Save a decision
wikitoolkit remember "We chose SQLite over Postgres for the wiki store \
  because the typical scale is 10^3-10^4 pages" --category decision

# Save a lesson and link it to relevant pages
wikitoolkit remember "The sweep watermark must NOT advance on partial failure" \
  --category lesson \
  --link file:parrot/knowledge/wiki/jira_sync.py --rel references

# Save a concept with a custom title
wikitoolkit remember "OKF frontmatter is the deterministic metadata contract \
  for all wiki documents" --category concept --title "OKF frontmatter contract"
```

```
wikitoolkit remember TEXT [OPTIONS]

  --title TEXT          Short title (default: first 80 chars of TEXT)
  --category TEXT       note | decision | lesson | concept (default: note)
  --link ID             Page ID to link the memory to (repeatable)
  --rel TEXT            Relation for --link edges (default: references)
  --ns TEXT             Target namespace (writes to ONE plane; "all" rejected)
  --source TEXT         Citation URI
  --by TEXT             Identity asserting this memory (auto-resolved)
  --extract             Run LLM entity/relation extraction (requires WIKI_EXTRACT_LLM)
  --json                Emit raw JSON
  --store DIR           Target store
  --backend TEXT        Backend for --store
```

**How it works:**

- Page ID is deterministic: `mem-` + SHA1(`{title}::{category}`), first 12
  hex chars. Re-remembering the same title+category **updates** instead of
  duplicating.
- Identity is auto-resolved: explicit `--by` > `CLAUDE_AGENT_ID` /
  `PARROT_AGENT_ID` env (prefixed `agent:`) > local user (prefixed `human:`).
- When `sync_graph` is enabled in `.parrot/wiki.json`, the memory is also
  mirrored into the GraphIndex plane as an audited commit.

### note — Annotate an Existing Page

```bash
wikitoolkit note file:parrot/tools/__init__.py \
  "The meta_path finder redirects parrot.tools.<x> -> parrot_tools.<x>"
```

Appends a dated, attributed note to the page body:

> **Note (2026-08-24, human:jesus):** The meta_path finder redirects
> parrot.tools.\<x\> -> parrot_tools.\<x\>

```
wikitoolkit note PAGE_ID TEXT [OPTIONS]

  --by TEXT             Identity asserting this note (auto-resolved)
  --ns TEXT             Target namespace
  --json                Emit raw JSON
  --store DIR           Target store
  --backend TEXT        Backend
```

### link — Connect Two Pages

```bash
wikitoolkit link file:parrot/bots/agent.py file:parrot/tools/__init__.py \
  --rel references
```

Creates a typed, asserted edge between two existing pages. Both pages must
live in the same plane (no cross-namespace edges).

```
wikitoolkit link SRC DST [OPTIONS]

  --rel TEXT            Edge relation (default: references)
  --by TEXT             Identity (auto-resolved)
  --ns TEXT             Namespace (both pages must be in the same plane)
  --json                Emit raw JSON
  --store DIR           Target store
  --backend TEXT        Backend
```

### memories — List Saved Knowledge

```bash
wikitoolkit memories
wikitoolkit memories --category decision --limit 10
```

Lists memories and agent-authored pages, newest first.

```
wikitoolkit memories [OPTIONS]

  --category TEXT       Filter by category (note, decision, lesson, concept)
  --limit INT           Max rows (default: 50)
  --json                Emit raw JSON
  --store DIR           Target store
  --backend TEXT        Backend
```

### audit — Review the Write Log

```bash
wikitoolkit audit
```

Shows the WikiBookkeeper operation log and GraphIndex commit history — every
write is attributed and timestamped.

```
wikitoolkit audit [OPTIONS]

  --limit INT           Max entries per plane (default: 30)
  --json                Emit raw JSON
  --store DIR           Target store
  --backend TEXT        Backend
```

---

## Coding Assistant Integration

### Claude Code

The full-featured integration. Install with:

```bash
parrot claude install
```

This performs 7 idempotent steps:

| Step | Artifact | Purpose |
|------|----------|---------|
| 1 | `.parrot/wiki.json` | Project config (created if missing) |
| 2 | `CLAUDE.md` managed section | Instructs Claude to prefer `wikitoolkit query` over raw file scans |
| 3 | PreToolUse hook in `.claude/settings.json` | Nudges Claude toward the wiki before `Grep`/`Glob`/`Read`/`Bash` |
| 4 | Permission rules in `.claude/settings.local.json` | Auto-allows `Bash(wikitoolkit:*)` and `Bash(parrot wiki:*)` |
| 5 | `.mcp.json` entry | Registers the wikitoolkit MCP stdio server |
| 6 | `/parrotwiki` slash command | `.claude/commands/parrotwiki.md` |
| 7 | Git `post-commit` hook | Runs `wikitoolkit upsert --changed --quiet` after every commit |

Options:

```
parrot claude install [OPTIONS]

  --path DIR                  Repo root (auto-detected)
  --git-hook / --no-git-hook  Install git post-commit hook (default: yes)
  --gitignore / --no-gitignore  Add .parrot/ to .gitignore (default: yes)
  --build / --no-build        Build the wiki now if not already built (default: yes)
```

Other commands:

```bash
parrot claude status      # Show what's installed
parrot claude uninstall   # Remove all managed artifacts (keeps the wiki plane)
```

#### How a Claude Code session flows

1. You ask: *"how does the wiki ingest pipeline work?"*
2. Claude reaches for Grep → the **PreToolUse hook** fires and injects a nudge.
3. Claude runs `wikitoolkit query "wiki ingest pipeline"` — gets ranked stubs
   for a few hundred tokens instead of several full files.
4. `wikitoolkit page file:…ingest.py` gives the API outline and content;
   `wikitoolkit related` walks imports.
5. On `git commit`, the **post-commit hook** upserts changed files so the
   graph is already fresh for the next question.

#### The /parrotwiki slash command

Available actions:

```
/parrotwiki query <question>       # Search the knowledge graph
/parrotwiki page <id>              # Read a full page
/parrotwiki related <id>           # Follow edges
/parrotwiki status                 # Graph health
/parrotwiki build                  # Rebuild
/parrotwiki remember <fact>        # Save knowledge
/parrotwiki note <id> <text>       # Annotate a page
/parrotwiki link <src> <dst>       # Connect two pages
/parrotwiki memories               # List saved knowledge
/parrotwiki audit                  # Review write log
/parrotwiki --wiki [dir]           # Export human-readable markdown wiki
```

#### PreToolUse hook details

The hook (`wikitoolkit claude-hook`) reads the tool payload from stdin and
emits a non-blocking `additionalContext` nudge. It:

- Only fires when the repo has a built wiki
- Throttles: at most one nudge per cooldown window (default 60 seconds,
  configurable via `claude.nudge_cooldown_seconds` in `.parrot/wiki.json`)
- Never blocks the permission flow
- Always exits 0 — a broken hook can never break a session

### Codex (OpenAI)

```bash
wikitoolkit codex install
```

Writes:
- A managed instruction block in `AGENTS.md`
- A skill file at `.codex/skills/parrot-wiki/SKILL.md`
- A PreToolUse hook in `.codex/hooks.json` matching `Bash|Grep|Glob|Read`

The hook emits an advisory `systemMessage` nudge toward `wikitoolkit query`.

### Gemini (Google)

```bash
wikitoolkit gemini install
```

Writes:
- A managed instruction block in `GEMINI.md`
- A skill file at `.gemini/skills/parrot-wiki/SKILL.md`
- An AfterTool hook in `.gemini/settings.json` matching
  `run_shell_command|read_file|read_many_files|grep_search|search_file_content|glob|list_directory`

### MCP Server (Native Tools)

The wikitoolkit MCP server exposes six native tools that appear alongside
`Grep`, `Read`, and other built-in tools — no shell overhead, no competing
for tool-selection:

| Tool | Description |
|------|-------------|
| `wiki_query` | Search the knowledge graph. Returns ranked page stubs. |
| `wiki_page` | Read a full wiki page by ID. |
| `wiki_related` | Follow typed edges from a page. |
| `wiki_remember` | Save durable knowledge (decisions, gotchas, cross-file relationships). |
| `wiki_note` | Append a dated note to an existing page. |
| `wiki_status` | Check graph health: page count, staleness, last build time. |

When an Obsidian vault is configured, an additional `vault_ingest` tool is
available for rebuilding the vault plane.

Configuration in `.mcp.json`:

```json
{
  "mcpServers": {
    "wikitoolkit": {
      "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/wikitoolkit",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

The MCP server resolves registered namespaces at startup, so all federated
corpora are available through the native tools with no extra configuration.

---

## Git Hooks — Auto-Refresh on Commit

The `parrot claude install` command (and `wikitoolkit codex install`) installs
a git **post-commit hook** that keeps the wiki fresh:

```bash
# What the hook runs after every commit:
wikitoolkit upsert --changed --quiet >/dev/null 2>&1 || true
```

The hook:
- Uses an **absolute binary path** so it works in git worktrees
- Is **silent** (stdout/stderr redirected to /dev/null)
- **Never fails the commit** (`|| true`)
- **Chains politely** into existing hooks (checks shebang compatibility)
- **Skips gracefully** if a full build holds the write lock

What `upsert --changed` does:
- Gets the file list from `git diff-tree HEAD` (handles merge commits via
  `-m --first-parent`)
- Re-ingests modified/added files through the same pipeline as `build`
- **Removes pages** for deleted files
- Waits up to 3 seconds for the write lock, then skips if busy

### Manual hook installation

If you did not use `parrot claude install`, add this to
`.git/hooks/post-commit`:

```bash
#!/bin/sh
# Keep the LLM-wiki knowledge graph in sync with the last commit.
/path/to/.venv/bin/wikitoolkit upsert --changed --quiet >/dev/null 2>&1 || true
```

Make it executable: `chmod +x .git/hooks/post-commit`

---

## Namespaces — Multi-Wiki Federation

Namespaces let you federate **multiple wiki planes** behind a single query
surface. Your codebase wiki, Obsidian notes, Jira tickets, and external
documentation can all be searched together.

### Namespace Kinds

| Kind | CLI flag | What it points at | Use case |
|------|----------|-------------------|----------|
| `path` | `--project <dir>` | Root of another wiki project (loads its `.parrot/wiki.json`) | Another repo's codebase wiki |
| `store` | `--store <dir>` | Pre-built store directory (`wiki.db` inside) | Off-repo corpus (Jira issues, generated docs) |
| `database` | `--database <name>` | ArangoDB (default) or a satellite-registered backend's database holding the plane | Server-hosted shared wiki |
| `vault` | `--vault <dir>` | Obsidian vault root (requires `.obsidian/`) | Personal/team notes |

### Registering a Namespace

```bash
# Register an Obsidian vault
wikitoolkit ns add notes --vault ~/vaults/my-notes \
  --description "Personal notes" --global

# Register a pre-built store (e.g. Jira issues)
wikitoolkit ns add issues --store ~/.parrot/wikis/issues/.parrot/wiki \
  --description "Jira ticket corpus" --global

# Register another project's codebase wiki
wikitoolkit ns add asyncdb --project ~/proyectos/asyncdb \
  --description "AsyncDB codebase"

# Register an ArangoDB-hosted wiki
wikitoolkit ns add legislation --database wiki_legislation \
  --credentials-env LEGAL_ARANGO \
  --description "Legislation corpus" --weight 0.8

# Register a --database entry on a satellite-registered backend instead of
# arangodb (FEAT-449 M7 — e.g. parrot_tools.legal's "ontology_legal")
wikitoolkit ns add legal --database legal_db --backend ontology_legal \
  --description "Legal ontology tenant, read-only"

# List registered namespaces
wikitoolkit ns list

# Remove a namespace
wikitoolkit ns remove notes --global
```

Full `ns add` options:

```
wikitoolkit ns add NAME [OPTIONS]

  --project DIR         Another wiki project root (kind: path)
  --store DIR           Pre-built store directory (kind: store)
  --backend TEXT        For --store: sqlite | memory (default: sqlite).
                        For --database: arangodb (default) or a
                        satellite-registered backend name (e.g.
                        ontology_legal, FEAT-449 M7); not validated
                        against the registry here — an unknown name
                        surfaces as a ValueError when the namespace is
                        actually opened.
  --database TEXT       ArangoDB (or registered extra backend) database name (kind: database)
  --credentials-env TEXT  Env var prefix for ArangoDB credentials (default: ARANGODB)
  --vault DIR           Obsidian vault root (kind: vault; requires .obsidian/)
  --description TEXT    What this namespace holds
  --weight FLOAT        Score multiplier when merging results (0.0-1.0, default: 1.0)
  --global              Write to ~/.parrot/wikis.json instead of the repo's wiki.json
```

Exactly one of `--project` / `--store` / `--database` / `--vault` is required.

#### Registry files

- **Repo-local**: `.parrot/wiki.json` → `namespaces` field
- **Per-user global**: `~/.parrot/wikis.json` (at `PARROT_HOME/wikis.json`)

Repo declarations win over global ones on a name clash.

### Querying Across Namespaces

```bash
# Default: search ALL registered namespaces
wikitoolkit query "forms tenant problem"

# Search only one namespace
wikitoolkit query --ns issues "forms tenant problem"

# Search a subset
wikitoolkit query --ns "issues,notes" "forms tenant problem"

# Search only the local (codebase) wiki
wikitoolkit query --ns local "forms tenant problem"

# Foreign page IDs come back prefixed
wikitoolkit page issues::file:NAV-9372.md
wikitoolkit related notes::file:Retro.md
```

Foreign page IDs are always qualified (`<namespace>::<id>`); local IDs stay
bare. Pass a qualified ID verbatim to `page` / `related`.

### How Federation Works

The `FederatedWikiStore`:
1. Reads fan out **concurrently** to local + all namespace stores
2. Results are **normalized per namespace** (min-max [0,1]), **weighted**, and
   merged
3. Writes go to the **local plane only**
4. Foreign planes are always opened **read-only**
5. A broken namespace is a note, not a failure — the query proceeds without it

Namespace name rules: `^[A-Za-z0-9][A-Za-z0-9_.:-]*$`, no `::`, not `all` or
`local` (reserved).

---

## Obsidian Vaults as Wiki Sources

Obsidian vaults are first-class wiki sources. The vault scanner
(`vault_scan.py`) understands Obsidian's conventions:

### What gets extracted

| Obsidian feature | Wiki representation |
|------------------|---------------------|
| `.md` note | `file:<relpath>` page (category `"document"`) |
| `[[wikilink]]` | `references` edge (resolved within the vault) |
| `![[embed]]` | `embeds` edge |
| `#tag` | `tagged` edge + `tag:<tagname>` tag page |
| Folder structure | `contains` edges + `dir:<path>` overview pages |
| YAML frontmatter | Preserved in page body (queryable via FTS) |
| Aliases | Included in the page title/body for search |

Unresolved wikilinks (pointing outside the vault) are dropped from edges but
counted in the build stats.

### Building from a vault

```bash
# Auto-detected (has .obsidian/)
wikitoolkit build --path ~/vaults/work-notes

# Manual vault mode
wikitoolkit build --vault --path ~/some/markdown/folder
```

### Registering as a namespace

```bash
# Register so the vault is searchable from your repo
wikitoolkit ns add notes --vault ~/vaults/work-notes \
  --description "Work notes vault" --global
```

### Vault ingestion via MCP

When a vault is configured in `.parrot/wiki.json` (field `vault_dir`), the
MCP server exposes a `vault_ingest` tool that rebuilds the vault plane:

```json
// .parrot/wiki.json
{
  "wiki_name": "codebase",
  "vault_dir": "~/vaults/work-notes"
}
```

---

## Document Ingestion

### Supervised Ingestion (wikitoolkit ingest)

For ingesting document corpora (PDF, DOCX, PPTX, XLSX, HTML, EPUB, Markdown,
plain text) with editorial control:

```bash
# Dry run — see what would be ingested
wikitoolkit ingest ~/documents/specs/ --dry-run

# Interactive — approve each document
wikitoolkit ingest ~/documents/specs/ --interactive

# Automatic — charter-driven thresholds decide
wikitoolkit ingest ~/documents/specs/ --auto --charter .parrot/charter.yaml

# Ingest a single URL
wikitoolkit ingest https://example.com/paper.pdf --interactive
```

```
wikitoolkit ingest SOURCE [OPTIONS]

  --charter PATH          Editorial charter YAML (default: .parrot/charter.yaml)
  --dry-run               Triage all, emit manifest, ingest nothing
  --review PATH           Apply human-edited decisions from a manifest.jsonl
  --interactive           Prompt per-document before applying
  --auto                  Charter thresholds decide; flags audit sample
  --extract               EXPERIMENTAL: include extracted claims in manifest
  --lightweight-model TEXT  Stage-1 triage model (default: $WIKI_LIGHTWEIGHT_MODEL)
  --model TEXT            Stage-2 escalation model (default: $WIKI_MODEL)
  --audit-rate FLOAT      Fraction of --auto decisions flagged for audit (default: 0.1)
  --manifest PATH         Manifest output path
  --recursive / --no-recursive  Walk directories recursively (default: yes)
  --fetch-timeout FLOAT   URL fetch timeout in seconds (default: 30)
```

Exactly one mode required: `--dry-run`, `--review`, `--interactive`, or
`--auto`.

### Jira Ticket Extraction (wikitoolkit ingest-jira)

Extract your Jira ticket corpus into a federated `issues` namespace. See the
[Jira Ticket Extractor guide](./jira-ticket-extractor.md) for full setup
instructions.

```bash
# Full backfill
wikitoolkit ingest-jira

# Incremental daily sweep (what the cron runs)
wikitoolkit ingest-jira --quiet
```

```
wikitoolkit ingest-jira [OPTIONS]

  --jql TEXT           JQL scope (default: $JIRA_WIKI_JQL)
  --project TEXT       Shorthand for `project = <KEY>`
  --since DATE         Override the stored watermark (ISO-8601)
  --issues-dir PATH    Output directory (default: $JIRA_WIKI_ISSUES_DIR)
  --build / --no-build Build the plane after emitting (default: build)
  --enrich             Opt-in LLM summary (default: off)
  --force              Re-render everything, ignoring watermark
  --dry-run            Report what would change; write nothing
  --json               Emit SweepReport as JSON
  -q, --quiet          Only the final summary line
```

---

## Storage Backends

The wiki supports three storage backends. Choose based on your deployment
needs.

### SQLite (default)

**Zero deployment, single-file, recommended for most uses.**

```bash
wikitoolkit build --backend sqlite   # or just: wikitoolkit build
```

| Property | Detail |
|----------|--------|
| Storage | Single `wiki.db` file in WAL journal mode |
| FTS engine | FTS5 with BM25 ranking, `unicode61` tokenizer |
| Vector search | Brute-force cosine scan (appropriate at wiki scale) |
| Dependency | `aiosqlite` (included in base install) |
| Multi-writer | WAL mode (single machine) |
| Scale | 10³–10⁴ pages |

The SQLite backend stores everything in `.parrot/wiki/wiki.db`:
- 6 tables: `meta`, `sources`, `pages`, `edges`, `pages_fts` (FTS5), `embeddings`
- Read-only mode (for federated namespaces) uses a connection ladder:
  `immutable=1` for quiescent planes → `mode=ro` when a writer is active

Configuration:

```json
// .parrot/wiki.json
{
  "wiki_name": "codebase",
  "backend": "sqlite",
  "storage_dir": ".parrot/wiki"
}
```

### ArangoDB

**Server-hosted, multi-language FTS, native graph edges. For teams sharing a
wiki or projects needing multi-language search.**

```bash
wikitoolkit build --backend arangodb
```

| Property | Detail |
|----------|--------|
| Storage | ArangoDB server (5 collections prefixed `wiki_`) |
| FTS engine | ArangoSearch with BM25, configurable text analyzers |
| Multi-language FTS | Yes — comma-separated analyzers (e.g. `text_en,text_es`) |
| Vector search | Brute-force cosine (no native ArangoDB vector index) |
| Dependency | `asyncdb[arangodb]` (in `databases` extras) |
| Multi-writer | Server-managed multi-client |
| Scale | Server-scale, shareable across projects |
| Graph features | Native edge collection (graph traversal possible) |

#### Installation

```bash
# Install the ArangoDB driver
pip install 'ai-parrot[databases]'
# or specifically:
uv pip install 'asyncdb[arangodb]'
```

#### Environment variables

The connection credentials are resolved from environment variables with a
configurable prefix (default: `ARANGODB`):

| Variable | Default | Description |
|----------|---------|-------------|
| `ARANGODB_HOST` | `127.0.0.1` | ArangoDB server host |
| `ARANGODB_PORT` | `8529` | ArangoDB server port |
| `ARANGODB_PROTOCOL` | `http` | Connection protocol (`http` or `https`) |
| `ARANGODB_USERNAME` | `root` | Authentication username |
| `ARANGODB_PASSWORD` | *(empty)* | Authentication password |

You can use a different prefix per wiki (useful when connecting to multiple
ArangoDB instances):

```bash
# Production wiki credentials
export PROD_ARANGO_HOST=arango.prod.internal
export PROD_ARANGO_PORT=8529
export PROD_ARANGO_USERNAME=wiki_svc
export PROD_ARANGO_PASSWORD=secret
```

#### Configuration

```json
// .parrot/wiki.json
{
  "wiki_name": "my-project",
  "backend": "arangodb",
  "storage_dir": ".parrot/wiki",
  "arango_database": "wiki_my_project",
  "arango_credentials_env": "ARANGODB",
  "arango_text_analyzer": "text_en"
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `arango_database` | `wiki_{wiki_name}` | ArangoDB database name |
| `arango_credentials_env` | `ARANGODB` | Env var prefix for connection credentials |
| `arango_text_analyzer` | `text_en` | ArangoSearch text analyzer(s); comma-separated for multi-language |

#### Multi-language search

ArangoDB's key advantage is native multi-language full-text search. Configure
multiple analyzers:

```json
{
  "arango_text_analyzer": "text_en,text_es,text_pt"
}
```

This creates an ArangoSearch view with all three analyzers, so queries in
English, Spanish, or Portuguese all match correctly with language-aware
stemming and stop-word removal.

Available built-in analyzers: `text_en`, `text_es`, `text_de`, `text_fr`,
`text_pt`, `text_it`, `text_zh`, `text_ja`, `text_ko`, and
[many more](https://docs.arangodb.com/stable/index-and-search/analyzers/#text).

#### ArangoDB collections

The backend creates 5 collections (prefixed `wiki_`):

| Collection | Type | Purpose |
|------------|------|---------|
| `wiki_pages` | Document | Page bodies (keyed by percent-encoded concept_id) |
| `wiki_edges` | Edge | Typed relations (`_from`/`_to` for native graph traversal) |
| `wiki_embeddings` | Document | Per-page vector arrays |
| `wiki_sources` | Document | Source tracking (SHA-1 + mtime) |
| `wiki_meta` | Document | Metadata (schema version, wiki name) |

Plus an ArangoSearch view: `{wiki_name}_pages_view` for BM25 lexical search.

#### Registering an ArangoDB namespace

```bash
# Register a remote ArangoDB wiki as a namespace
wikitoolkit ns add legislation \
  --database wiki_legislation \
  --credentials-env LEGAL_ARANGO \
  --description "Legislation corpus" \
  --weight 0.8

# The namespace store opens read-only with a connection probe + timeout
```

#### Read-only federation with ArangoDB

When a namespace is registered with `--database`, the federation layer:
1. Probes the database from `_system` (no provisioning on foreign namespaces)
2. Verifies the `wiki_pages` collection exists
3. Opens the store **read-only** — no database or collection creation
4. Applies a configurable timeout (default: 5 seconds) so an unreachable
   ArangoDB server doesn't block the query

### InMemory / OKF Bundle

**File-based, human-browsable markdown. For development, testing, and
OKF-compatible export.**

```bash
wikitoolkit build --backend memory
```

| Property | Detail |
|----------|--------|
| Storage | Directory of OKF v0.1 markdown files with YAML frontmatter |
| FTS engine | TF-IDF (in-process, title boosted 3×) |
| Vector search | Brute-force cosine |
| Dependency | `pyyaml` (included in base install) |
| Human-browsable | Yes (plain markdown files) |
| Scale | 10³–10⁴ pages |

### Backend Comparison

| Feature | SQLite | ArangoDB | InMemory |
|---------|--------|----------|----------|
| **Deployment** | Zero (single file) | Requires server | Zero (directory) |
| **FTS engine** | FTS5 / BM25 | ArangoSearch / BM25 | TF-IDF |
| **Multi-language FTS** | No (`unicode61` only) | Yes (configurable analyzers) | No |
| **Vector search** | Brute-force cosine | Brute-force cosine | Brute-force cosine |
| **Edges** | SQL table | Native edge collection | In-memory adjacency |
| **Human-browsable** | No (binary) | ArangoDB Web UI | Yes (markdown files) |
| **Multi-writer** | WAL (single machine) | Server-managed | No locking |
| **Read-only federation** | Yes (immutable/ro) | Yes (probe + verify) | Yes |
| **Dependency** | `aiosqlite` (base) | `asyncdb[arangodb]` (extras) | `pyyaml` (base) |
| **Best for** | Single dev, CI, most repos | Teams, multi-language, shared corpus | Dev, testing, export |

> **Note**: There is no PostgreSQL wiki backend. Postgres/pgvector is used
> elsewhere in AI-Parrot for vector stores (`parrot.stores.pgvector`), but the
> wiki retrieval plane uses SQLite or ArangoDB only.

---

## Exporting the Wiki

Export the knowledge graph as a human-readable markdown bundle:

```bash
# Default: export to docs/wiki/
wikitoolkit export

# Custom output directory
wikitoolkit export -o docs/knowledge-base
```

```
wikitoolkit export [OPTIONS]

  -o, --output DIR      Output directory (default: docs/wiki)
```

Writes one markdown file per page (YAML frontmatter + body) plus a root
`index.md`. Automatically adds the export directory to `exclude_dirs` in the
config so subsequent builds don't ingest the exported markdown back.

Use `/parrotwiki --wiki` from Claude Code for the same operation.

---

## Configuration Reference

### Project Config (.parrot/wiki.json)

Created by `wikitoolkit build` or `parrot claude install`. Located at the
repo root: `.parrot/wiki.json`.

```json
{
  "wiki_name": "codebase",
  "storage_dir": ".parrot/wiki",
  "backend": "sqlite",
  "include_suffixes": [],
  "exclude_dirs": [],
  "body_max_chars": 16000,
  "max_file_kb": 512,
  "sync_graph": false,
  "vault_dir": null,
  "arango_database": null,
  "arango_credentials_env": "ARANGODB",
  "arango_text_analyzer": "text_en",
  "claude": {
    "nudge_cooldown_seconds": 60,
    "nudge_tools": ["Grep", "Glob", "Read", "Bash"]
  },
  "namespaces": {
    "notes": {
      "vault": "~/vaults/work-notes",
      "description": "Work notes",
      "weight": 1.0
    },
    "issues": {
      "store": "~/.parrot/wikis/issues/.parrot/wiki",
      "description": "Jira ticket corpus",
      "weight": 1.0
    },
    "shared-docs": {
      "database": "wiki_shared_docs",
      "credentials_env": "DOCS_ARANGO",
      "description": "Shared documentation wiki",
      "weight": 0.8
    }
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `wiki_name` | repo dir name | Wiki identifier |
| `storage_dir` | `.parrot/wiki` | Where the plane lives |
| `backend` | `sqlite` | `sqlite` / `memory` / `arangodb` |
| `include_suffixes` | `[]` | Only scan files with these suffixes (empty = all) |
| `exclude_dirs` | `[]` | Skip these directories |
| `body_max_chars` | `16000` | Max chars per page body |
| `max_file_kb` | `512` | Skip files larger than this |
| `sync_graph` | `false` | Mirror writes to the GraphIndex plane |
| `vault_dir` | `null` | Obsidian vault path (enables `vault_ingest` MCP tool) |
| `arango_database` | `wiki_{name}` | ArangoDB database name |
| `arango_credentials_env` | `ARANGODB` | Env var prefix for ArangoDB credentials |
| `arango_text_analyzer` | `text_en` | ArangoSearch text analyzer(s) |
| `claude.nudge_cooldown_seconds` | `60` | Min seconds between PreToolUse nudges |
| `claude.nudge_tools` | `["Grep","Glob","Read","Bash"]` | Tools the hook intercepts |
| `namespaces` | `{}` | Federated namespace declarations |

### Environments — per-env overlays, precedence, and sync (FEAT-461)

The committed base `.parrot/wiki.json` is one config, but a repo often
needs a *different* plane per environment: a local, zero-VPN SQLite plane
when a teammate has no `ENV` exported, and the shared ArangoDB plane under
`ENV=dev`/`ENV=prod`. Per-environment **overlay files** — optional,
partial configs — layer on top of the base without duplicating it.

#### Env resolution

The active environment is resolved, on every call, in this order:

```
WIKI_ENV  >  ENV  >  "local"
```

`WIKI_ENV` is the escape hatch for when the wiki's plane and navconfig's
credential environment must differ. **This repo commits
`.parrot/wiki.local.json` = `{"backend": "sqlite"}`, so an unset `ENV`
gets you a fully offline, no-VPN sqlite plane out of the box** — the
payoff this feature exists for.

#### Overlay files

`.parrot/wiki.{env}.json` is a *partial* config — every field optional,
shallow-merged over the base at load time (`namespaces` merges per-key;
every other field the overlay sets replaces the base's value verbatim).
Overlays carry **no credential fields** (no host/port/username/password)
— those always resolve via navconfig from `env/{ENV}/.env`, never from a
committed JSON file. An unknown or secret-like key in an overlay is a
hard load error, not a silent pass-through.

```json
// .parrot/wiki.local.json (committed in this repo)
{
  "backend": "sqlite"
}
```

```json
// .parrot/wiki.dev.json (generated by `wikitoolkit build` if missing)
{
  "backend": "arangodb",
  "arango_database": "wiki_ai-parrot",
  "arango_credentials_env": "ARANGODB",
  "arango_text_analyzer": "text_en"
}
```

- **Missing overlay** → read commands (`query`/`page`/`related`/`status`)
  fall back to the base config silently; `status` reports
  `base (no overlay)`.
- **`wikitoolkit build`** generates the ACTIVE env's overlay when it does
  not exist yet: `local` → `{"backend": "sqlite"}`; every other env →
  the base's Arango settings mirrored verbatim (same database name —
  environments never get a suffixed database; separation comes from the
  per-`ENV` server/credentials, not the name). An existing overlay is
  never clobbered, and a one-off `--backend` flag is never frozen into a
  freshly generated overlay's derivation.

#### Backend precedence

One rule, applied everywhere a backend is chosen (`build`, `_open_store`,
the read/write store resolvers):

```
--backend flag  >  environment (overlay value / WIKI_STORE_BACKEND)  >  base wiki.json
```

#### ⚠️ Plane selection is not credential selection

**An unset `ENV` selects the local *plane* (sqlite) — it does NOT change
which credentials navconfig loads.** Any shared namespace or sync target
that still reaches ArangoDB in local mode resolves its host/user/password
from `env/.env` (the *dev* credentials) exactly as it would with
`ENV=dev` set — navconfig's own "no `ENV` ⇒ `env/.env`" convention is
untouched by this feature; only the wiki's *plane* choice diverges from
it. In local mode, an unreachable shared namespace degrades gracefully
(skipped with a one-line note, bounded connect timeout, local results
still returned) — the PRIMARY plane never falls back automatically.

#### Sync — moving authored knowledge between planes

`wikitoolkit sync push|pull` moves memory pages (`remember`), attributed
notes, and the `asserted` edges between them — never repo-scanned
(`ingest`) pages, and never deletes (no tombstones in v1: a memory
deleted locally reappears on the next `pull` if it still exists remotely
— recover with the git history of `.parrot/wiki.local.json`'s plane, or
delete it on both sides).

```bash
# Push local memories/notes to the shared dev plane
wikitoolkit sync push --env dev

# Pull from the shared plane — excludes YOUR OWN records by default
wikitoolkit sync pull --env dev

# Pull everything, including records you authored yourself
wikitoolkit sync pull --env dev --all

# Preview without applying anything
wikitoolkit sync push --env dev --dry-run
```

- **Conflict rule**: last-write-wins per record by `updated_at` — the
  side with the newer stamp wins; the loser is still recoverable from the
  bookkeeper audit log (`wikitoolkit audit`).
- **Author filter** (`pull` only): records whose `asserted_by` matches
  your local identity (`human:<user>`) are excluded by default, so
  syncing never lets a stale remote copy silently overwrite your own
  freshly-authored memory. `--all` switches to pure last-write-wins.
- **Note merge**: notes are never dropped by a sync. Both sides' notes on
  a page are unioned (date-ordered, keyed by author+date+text) into
  whichever side's body wins the conflict — a note added on either plane
  survives every subsequent push/pull.
- Every applied change is logged to the bookkeeper (`SYNC_PUSH`/
  `SYNC_PULL`); `--dry-run` computes and prints the report but applies
  and logs nothing.

#### Sync — mirroring wiki planes into an Obsidian vault

`wikitoolkit sync obsidian` is the third sync direction: a **one-way**
projection of wiki planes into an Obsidian vault as markdown notes
(the reverse of vault ingestion via `build --vault` or a `vault`-kind
namespace). Which page **categories** sync and which vault **folder**
each one maps onto is configuration, under `obsidian_sync` in
`.parrot/wiki.json`:

```jsonc
{
  "obsidian_sync": {
    "vault_dir": "~/vaults/notes",        // target vault (falls back to vault_dir)
    "root_folder": "LLM Wiki",            // subtree holding every synced note
    "categories": ["concept", "entity"],  // empty = all categories
    "folders": {"concept": "Concepts"},   // category -> folder override
    "namespaces": ["local", "issues"],    // planes to mirror ('all' = local + every ns)
    "prune": false                        // delete notes whose page vanished
  }
}
```

```bash
# Mirror the configured planes/categories into the vault
wikitoolkit sync obsidian

# Ad-hoc overrides (flags win over config for this run)
wikitoolkit sync obsidian --vault ~/vaults/notes --ns local,issues \
  --category concept --category entity

# Preview, then apply with pruning of vanished pages
wikitoolkit sync obsidian --dry-run -v
wikitoolkit sync obsidian --prune
```

- **Layout**: `<root_folder>/[<namespace>/]<category folder>/<page>.md` —
  the local plane writes directly under the root folder; each foreign
  namespace gets its own subtree. Category folders default to the OKF
  export pluralization (`entity` → `entities/`) unless overridden via
  `folders`.
- **Frontmatter marker**: every synced note carries `wiki_sync:
  <wiki_name>`, `wiki_scope: <wiki_name>@<repo-root digest>`, `wiki_id:
  <concept_id>` and `namespace: <plane>` (plus `aliases`, `tags:
  [wiki/<category>]`, `summary`, `updated`), so notes are searchable in
  Obsidian and safely identifiable as managed.
- **Edges become wikilinks**: edges between two synced pages render as a
  `## Related` section of `[[wikilinks]]`, so the wiki graph shows up in
  Obsidian's graph view.
- **Idempotent**: rendering is deterministic — an unchanged page is
  reported `unchanged` and never rewritten.
- **Prune is marker-guarded**: `--prune` (or `"prune": true`) deletes
  only notes whose `wiki_scope` matches THIS project exactly (name +
  repo-root digest — two projects sharing a vault, even with the same
  `wiki_name`, can never prune each other) and whose page vanished or is
  no longer selected; hand-written notes are never touched, and a
  namespace that was skipped this run is left alone.
- Applied runs are logged to the bookkeeper as `SYNC_OBSIDIAN`;
  `--dry-run` applies and logs nothing.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PARROT_HOME` | `~/.parrot` | Root for all parrot data (wikis, registries) |
| `WIKI_ENV` | *(none)* | Active wiki environment override — `WIKI_ENV` > `ENV` > `"local"` (FEAT-461) |
| `WIKI_STORE` | *(none)* | Override: read a pre-built store directly |
| `WIKI_STORE_BACKEND` | `sqlite` | Backend for `WIKI_STORE` (also honoured by `build`, FEAT-461) |
| `WIKI_MODEL` | *(none)* | LLM for `ingest` stage-2 and page generation |
| `WIKI_LIGHTWEIGHT_MODEL` | *(none)* | LLM for `ingest` stage-1 triage |
| `WIKI_EXTRACT_LLM` | *(none)* | LLM for `remember --extract` entity extraction |
| `CLAUDE_AGENT_ID` | *(none)* | Identity for `remember`/`note`/`link` attribution |
| `PARROT_AGENT_ID` | *(none)* | Fallback identity for attribution |
| `ARANGODB_HOST` | `127.0.0.1` | ArangoDB host (prefix configurable) |
| `ARANGODB_PORT` | `8529` | ArangoDB port |
| `ARANGODB_PROTOCOL` | `http` | ArangoDB protocol |
| `ARANGODB_USERNAME` | `root` | ArangoDB username |
| `ARANGODB_PASSWORD` | *(empty)* | ArangoDB password |

---

## CLI Reference

Quick reference for all `wikitoolkit` commands:

| Command | Description |
|---------|-------------|
| `build` | Generate/refresh the knowledge graph from the repo or vault |
| `upsert [paths] [--changed]` | Incrementally re-ingest specific files or last-commit changes |
| `query <question>` | BM25-ranked search → token-budgeted page stubs |
| `page <id>` | Read one page in full |
| `related <id>` | Follow typed edges from a page |
| `status` | Plane statistics, namespaces, staleness |
| `remember <text>` | Save a fact/decision/lesson to the graph (persistent memory) |
| `note <page_id> <text>` | Append an attributed note to a page |
| `link <src> <dst>` | Connect two pages with a typed edge |
| `memories` | List saved memories and authored pages |
| `audit` | Review the write log and graph commits |
| `export [-o dir]` | Export as human-readable markdown bundle |
| `ingest <source>` | Supervised charter-driven document ingestion |
| `ingest-jira` | Extract Jira tickets into the `issues` namespace |
| `communities` | Show detected code communities |
| `ground <claim>` | Check a claim against the knowledge graph |
| `ns list` | List registered namespaces |
| `ns add <name>` | Register a new namespace |
| `ns remove <name>` | Remove a namespace |
| `claude install/status/uninstall` | Full Claude Code integration |
| `codex install` | Codex (OpenAI) integration |
| `gemini install` | Gemini (Google) integration |
| `mcp` | Start the MCP stdio server |
| `claude-hook` | PreToolUse hook runtime (internal) |

All read commands accept `--store`, `--backend`, and `--ns` for direct store
access and namespace scoping.

---

## Architecture

```
                        ┌─────────────────────────────────┐
                        │       Coding Assistants          │
                        │  Claude Code · Codex · Gemini    │
                        └──────────┬──────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
              PreToolUse     MCP Server     /parrotwiki
              hook nudge     (6 tools)     slash command
                    │              │              │
                    └──────────────┼──────────────┘
                                   │
                        ┌──────────▼──────────────┐
                        │     wikitoolkit CLI       │
                        │  query · page · related   │
                        │  remember · note · link   │
                        │  build · upsert · ingest  │
                        └──────────┬──────────────┘
                                   │
                        ┌──────────▼──────────────┐
                        │   FederatedWikiStore     │
                        │  (concurrent fan-out,    │
                        │   normalize, weight,     │
                        │   merge, qualify)         │
                        └──────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
     ┌────────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
     │  Local plane     │  │  Namespace A   │  │  Namespace B   │
     │  (SQLite/Arango) │  │  (store/vault) │  │  (database)    │
     │  read + write    │  │  read-only     │  │  read-only     │
     └─────────────────┘  └────────────────┘  └────────────────┘

Data flow:

  Source code ──→ build ──→ wiki.db (pages + edges + FTS + embeddings)
  Obsidian vault ──→ build --vault ──→ wiki.db (notes + wikilinks + tags)
  Documents ──→ ingest ──→ wiki.db (charter-driven, LLM-triaged)
  Jira tickets ──→ ingest-jira ──→ markdown → build --vault → wiki.db
  Agent knowledge ──→ remember/note/link ──→ wiki.db (attributed, auditable)

  git commit ──→ post-commit hook ──→ upsert --changed ──→ wiki.db (incremental)
```

---

## See Also

- [LLM Wiki architecture (3-layer)](../llm-wiki.md) — PageIndex + GraphIndex
  + Ontology composition
- [WikiToolkit as Claude Code infrastructure](../wiki-claude-code.md) —
  focused guide on the Claude Code integration
- [Jira Ticket Extractor](./jira-ticket-extractor.md) — setup guide for
  the `issues` namespace
- [Jira Wiki Agent Integration](./jira-wiki-agent-integration.md) — adding
  the issues namespace to an existing agent
- [PageIndex](../pageindex.md) — tree-based RAG for structured documents
