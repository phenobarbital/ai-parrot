# WikiToolkit as Claude Code infrastructure

> Install the LLM-Wiki knowledge graph (FEAT-260) as coding-assistant
> infrastructure for the current repository — graphify-style. One
> command builds a machine-first KB graph of the codebase; another
> wires Claude Code to consult it before grepping raw files.

## TL;DR

```bash
# 1. Generate the KB graph from the current repository (offline, no LLM)
wikitoolkit build

# 2. Install the Claude Code integration
parrot claude install

# 3. Ask scoped questions (what the assistant now does automatically)
wikitoolkit query "where is the ingest pipeline implemented?"
```

## The retrieval plane

`wikitoolkit build` scans the repository deterministically — no LLM,
no embeddings, no network — and writes the FEAT-260 machine plane
(SQLite FTS5/BM25 + typed edges) under `.parrot/wiki/`:

- one **`file:<path>` page** per source file: extracted summary
  (module docstring / first heading), a Python **API outline**
  (classes, functions, docstrings via `ast`), and the content head
  for lexical search;
- one **`dir:<path>` overview page** per directory, listing children;
- **`contains` edges** (directory → file) and **`references` edges**
  between Python files derived from their imports (src-layouts
  resolve correctly, e.g. `packages/x/src/pkg/mod.py` ⇒ `pkg.mod`).

File discovery respects `.gitignore` (via `git ls-files`), skips
binaries, lockfiles, and oversized files. Re-builds are incremental:
sources are tracked with SHA-1 + mtime in the same SQLite plane, so
unchanged files are skipped and deleted files are pruned.

## CLI reference (`wikitoolkit` = `parrot wiki`)

| Command | Purpose |
| ------- | ------- |
| `wikitoolkit build` | Generate/refresh the KB graph from the repo (`--force`, `--backend sqlite\|memory`, `--name`). |
| `wikitoolkit query "<question>"` | Scoped question → ranked, token-budgeted page stubs (`--top-k`, `--budget`, `--json`). |
| `wikitoolkit page <id>` | Read one page in full (`--max-tokens`). |
| `wikitoolkit related <id>` | Follow typed edges (`--rel`, `--direction`). |
| `wikitoolkit upsert [paths...] [--changed]` | Incrementally re-ingest files (used by the git hook). |
| `wikitoolkit status` | Plane statistics + source staleness. |
| `wikitoolkit export -o docs/wiki` | Export a human-readable markdown wiki (OKF bundle + index). |

The repo config lives at `.parrot/wiki.json`
(`parrot.knowledge.wiki.project.WikiProjectConfig`): wiki name,
backend, include/exclude filters, body caps, and the Claude hook
settings.

## `parrot claude install`

Wires the wiki into Claude Code for this repository. Every artifact
is marker-based, idempotent, and reversible with
`parrot claude uninstall`:

1. **`.parrot/wiki.json`** — project config (created if missing).
2. **`CLAUDE.md` managed section** — tells the assistant to prefer
   scoped `wikitoolkit query "<question>"` calls over reading whole
   reports or grepping raw files (delimited by
   `<!-- parrot:wiki:begin/end -->`).
3. **PreToolUse hook** in `.claude/settings.json` — before
   search-style tool calls (`Grep|Glob|Read`), Claude Code runs
   `wikitoolkit claude-hook`, which injects a non-blocking
   `additionalContext` nudge toward the graph path. It never touches
   the permission flow, throttles itself (default: one nudge per
   300 s, `claude.nudge_cooldown_seconds`), only fires when a built
   plane exists, and always exits 0 — a broken hook can never block a
   session.
4. **`/parrotwiki` slash command** (`.claude/commands/parrotwiki.md`)
   — `query <question>`, `page <id>`, `related <id>`, `status`,
   `build`, and `--wiki [dir]` to build a markdown wiki from the
   graph (wraps `wikitoolkit export`).
5. **git `post-commit` hook** — auto-upserts the wiki after every
   commit (`wikitoolkit upsert --changed --quiet`). Chains politely
   into an existing post-commit hook and is removed cleanly on
   uninstall. Skip with `--no-git-hook`.
6. **`.gitignore`** — adds `.parrot/` (skip with `--no-gitignore`).

By default `install` also builds the plane on first run
(`--no-build` to skip). `parrot claude status` shows what is
installed.

## How an assistant session flows

1. You ask Claude Code: *"how does the wiki ingest pipeline work?"*
2. Claude reaches for Grep → the PreToolUse hook injects the nudge.
3. Claude runs `wikitoolkit query "wiki ingest pipeline"` and gets
   ranked stubs (`file:...ingest.py`, `dir:...wiki`, ...) for a few
   hundred tokens instead of several full files.
4. `wikitoolkit page file:...ingest.py` gives the API outline and
   content; `wikitoolkit related` walks imports.
5. On `git commit`, the post-commit hook upserts changed files, so
   the graph is already fresh for the next question.

## Testing

```bash
pytest tests/knowledge/wiki/test_repo_scan.py \
       tests/knowledge/wiki/test_cli.py \
       tests/knowledge/wiki/test_claude_code.py -v
```

## Read next

- [LLM Wiki](./llm-wiki.md) — the 3-layer architecture and agent-side
  `LLMWikiToolkit`.
- [PageIndex](./pageindex.md) — the writable page tree used by the
  LLM ingest path.
