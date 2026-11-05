# wikitoolkit Cheatsheet

Quick reference for the most useful commands of the AI-Parrot **LLM Wiki**
(`wikitoolkit` ≡ `parrot wiki`), the MCP toolkits (`parrot toolkits`), the
Claude Code / Codex / Gemini integration and the **Bookstore** library.

> Full guides: `docs/guides/llm-wiki-guide.md`,
> `wiki/integrations/runbooks/jira-issues-namespace.md`, `wiki/knowledge/bookstore-graph.md`,
> `wiki/knowledge/bookstore-codex.md`, `docs/guides/wiki-adr-decisions.md`.
>
> Note: `wikitoolkit export` writes **by default** to `docs/wiki/`. If you export
> the markdown bundle here, use `-o` with another folder so it does not get mixed with
> this file.

Always inside the repo venv:

```bash
source .venv/bin/activate
```

---

## 0. Installation

| What | Command |
|---|---|
| Wiki + loaders (PDF/DOCX/EPUB/MOBI) | `uv pip install 'ai-parrot[wiki]'` |
| Jira extractor | `uv pip install -e 'packages/ai-parrot[jira]'` |
| Bookstore + MCP server | `uv pip install 'ai-parrot[bookstore,mcp]'` |
| Leiden communities (optional) | `uv pip install leidenalg python-igraph` |
| JS/TS/Svelte/PHP/Rust/Perl symbols | included in `ai-parrot[wiki-languages]` (ast-grep). Without it there is an outline but **0 symbols**; `wikitoolkit status` reports it on the `Symbols:` line |
| Verify | `wikitoolkit --help` · `parrot --help` |

---

## 1. Basic cycle: build and query

```bash
wikitoolkit build                    # full repo graph (offline, no LLM)
wikitoolkit build --force            # re-ingest everything, ignore staleness
wikitoolkit build -q --no-graph      # without graph.html/graph.json
wikitoolkit build --no-export        # without the OKF markdown bundle
wikitoolkit build --backend arangodb # shared plane in ArangoDB

wikitoolkit status                   # statistics, namespaces, staleness
wikitoolkit status --json

wikitoolkit upsert path/a/archivo.py path/b/otro.py   # targeted re-ingest
wikitoolkit inbox                                  # ingest inbox/, verify and archive originals
wikitoolkit upsert --changed --quiet                    # whatever the last commit touched (git hook)
```

### Queries (progressive disclosure)

```bash
wikitoolkit query "how does the ingest pipeline work"          # ranked stubs, token budget
wikitoolkit query "compaction budget" -n 20 --budget 2000        # more results / more tokens
wikitoolkit query "memory render" --category module --table      # Rich table for humans
wikitoolkit query "graphindex" -b                                # + body of the top page
wikitoolkit query "..." --json

wikitoolkit page file:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
wikitoolkit page dir:packages/ai-parrot/src/parrot/memory --max-tokens 800
wikitoolkit related file:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
wikitoolkit related dir:packages/ai-parrot/src/parrot/memory --rel contains --direction out
```

Page ids: `file:<rel>`, `dir:<rel>`, `sym:<rel>#<qualname>`, `tag:<tag>`,
`book:<id>`, `issue:<hash>`, `spec:<FEAT>`, `task:<TASK>`. Those from a foreign
namespace come qualified: `issues::file:NAV-9372.md`.

**Query discipline**: search for the *thing* (symbol/module name), not your
hypothesis about it; if the first result points to a parent, follow up with
`page`/`related` before falling back to `grep`.

### Structural symbol plane (FEAT-498)

```bash
wikitoolkit symbols lookup AbstractBot                 # by name or qualname
wikitoolkit symbols lookup render_history --kind function --path-prefix packages/ai-parrot
wikitoolkit symbols outline packages/ai-parrot/src/parrot/bots/abstract.py --depth 2
wikitoolkit symbols outline "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.ask" --source
wikitoolkit symbols blast AbstractBot.get_client       # who depends on it (calls/extends/implements)
wikitoolkit symbols blast save_conversation_turn --depth 3 --no-tests --json
```

```bash
# Svelte: each .svelte is a symbol of kind `component`
wikitoolkit symbols lookup AdminBulkBar                 # the component (kind: component)
wikitoolkit symbols lookup "fieldsync/+page"            # SvelteKit route files: qualified with their directory
wikitoolkit symbols blast Spinner                        # who renders the component (follows `uses`, besides calls/extends/implements)

# Federated namespaces: foreign hits come qualified as <ns>::sym:…
wikitoolkit symbols lookup requireDashboardContainer                # broadcast (local + namespaces)
wikitoolkit symbols lookup requireDashboardContainer --ns svelte    # that namespace only
wikitoolkit symbols outline "svelte::src/lib/guard.ts"              # a qualified id is read in its own namespace
```

Notes:

- `wikitoolkit status` prints `Symbols   : enabled` or `disabled for javascript, php, … — pip install
  'ai-parrot[wiki-languages]'`; `build` warns once (WARNING) if it scanned code without the structural tier.
- Installing (or removing) the extra, or changing a rules file, automatically re-ingests the affected
  languages on the next normal `build` — `--force` is not needed.
- `blast` never crosses planes: within a namespace it follows only that namespace's edges.
- Local functions (`const onSave = () => …`) are `function` symbols; they do not appear in the `## API outline`.

Run `symbols blast` **before** touching a widely used function/class.

### Communities and grounding

```bash
wikitoolkit communities                 # Leiden/Louvain over the current store
wikitoolkit communities --inter         # meta-graph between communities
wikitoolkit communities --graph-kinds module,document --json
wikitoolkit ground "AbstractBot is the only writer of the history"   # requires .parrot/graph/ (sync_graph)
```

---

## 2. Integration with coding assistants

### Claude Code (`parrot claude`)

```bash
parrot claude install            # 7 idempotent steps (see table)
parrot claude install --no-git-hook --no-build --no-compaction
parrot claude install --tool-guards                # PreToolUse guard for large reads (FEAT-543)
parrot claude install --typesafe-api-key $KEY      # for the fast-jev-compaction plugin
parrot claude status [--json]
parrot claude uninstall          # removes the integration, keeps the plane
```

| Step | Artifact |
|---|---|
| 1 | `.parrot/wiki.json` (project config) |
| 2 | Managed section in `CLAUDE.md` (prefer `wikitoolkit query` over grep) |
| 3 | PreToolUse hook in `.claude/settings.json` (`wikitoolkit claude hook`) |
| 4 | `Bash(wikitoolkit:*)` / `Bash(parrot wiki:*)` permissions in `settings.local.json` |
| 5 | `wikitoolkit` entry in `.mcp.json` (stdio MCP server) |
| 6 | Slash command `/parrotwiki` (`.claude/commands/parrotwiki.md`) |
| 7 | Git `post-commit` → `wikitoolkit upsert --changed --quiet` |

Flags: `--bookstore/--no-bookstore` (installs the Bookstore MCP if there is an
indexed library), `--approve-mcp`, `--plugin-cli`, `--gitignore`.

Slash command inside Claude Code:

```
/parrotwiki query <question>      /parrotwiki remember <fact>
/parrotwiki page <id>             /parrotwiki note <id> <text>
/parrotwiki related <id>          /parrotwiki link <src> <dst>
/parrotwiki status                /parrotwiki memories
/parrotwiki build                 /parrotwiki audit
/parrotwiki --wiki [dir]          # exports a readable markdown bundle
```

Native MCP tools (`wikitoolkit mcp` server): `wiki_query`, `wiki_page`,
`wiki_related`, `wiki_remember`, `wiki_note`, `wiki_status`, `wiki_symbol_lookup`,
`wiki_code_outline`, `wiki_blast_radius`, `wiki_decision_why`,
`wiki_decisions_for_symbol`, `ledger_open/claim/close/ready/context`.

### Codex y Gemini / Antigravity

```bash
parrot codex install [--no-build] [--tool-guards]     # MCP + wiki and bookstore skills for Codex
parrot codex status --json · parrot codex uninstall
parrot gemini install · parrot gemini status · parrot gemini uninstall
```

### Manual git hook

```sh
#!/bin/sh
# .git/hooks/post-commit
wikitoolkit upsert --changed --quiet
```

---

## 3. Local MCP toolkits (`parrot toolkits`)

```bash
parrot toolkits list                         # status, hosts, drift, dependencies
parrot toolkits status [--host claude]       # config paths and health per host
parrot toolkits install browsing scraping --yes          # seeds .parrot/mcp-toolkits.yaml + registers
parrot toolkits install lsp --host claude --host codex
parrot toolkits enable memory --yes
parrot toolkits disable sdd-coder --yes      # unregisters but keeps the config
parrot toolkits uninstall lsp --yes
```

Toolkits available today: `bounded-source`, `browsing`, `database-query`, `lsp`,
`memory`, `querysource`, `scraping`, `sdd-coder`, `targeted-writer`.
Hosts: `claude | codex | google` (default: all detected).

---

## 4. Persistent memory (the agent forgets, the graph does not)

```bash
wikitoolkit remember "The sweep watermark lives in .parrot/jira_sync.json" \
  --category decision --title "Jira watermark" \
  --link file:packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py --rel about
wikitoolkit remember "..." --category lesson --source "https://..." --by human:jlara
wikitoolkit remember "..." --category concept --extract   # + LLM extraction to .parrot/graph (WIKI_EXTRACT_LLM)

wikitoolkit note file:packages/.../cli.py "ingest-jira never registers namespaces"
wikitoolkit link file:a.py file:b.py --rel references        # asserted edge, same plane
wikitoolkit memories [--category decision] [--limit 20]
wikitoolkit audit [--limit 50]                              # log of attributed writes
```

Memory categories: `note | decision | lesson | concept` (the repo page ones:
`module`, `symbol`, `document`, `overview`, `config`, ...). The id is a hash of
title+category, so re-remembering the same thing **updates** instead of duplicating.

### Sync authored knowledge with a shared plane (FEAT-461)

```bash
wikitoolkit sync push --env dev [--dry-run]    # local memories/notes/edges → dev plane
wikitoolkit sync pull --env dev [--all]        # excludes your own (human:<user>) unless --all
```

---

## 5. SDD work ledger (`wikitoolkit ledger`)

Shared plane in `<main>/.parrot/ledger/` (append-only `events.jsonl` +
rebuildable `ledger.db` index). It is fed by `/sdd-codereview`, `/sdd-done`
and the sdd-coder seats; `/sdd-fix` drains it.

```bash
wikitoolkit ledger open --kind bug --severity major \
  --discovered-from review:TASK-3115 \
  --about packages/ai-parrot/src/parrot/memory/render.py \
  --title "render_history ignores the budget" --body "..."

wikitoolkit ledger ready [--kind bug]                  # open and unclaimed (ordered by severity)
wikitoolkit ledger claim issue:5944887877e1 --actor human:jlara
wikitoolkit ledger unclaim issue:5944887877e1 --reason "not reproducible here"
wikitoolkit ledger close issue:5944887877e1 --reason "fixed" --resolved-by commit:<sha>
wikitoolkit ledger close issue:... --reason "..." --resolved-by task:TASK-3120

wikitoolkit ledger context packages/ai-parrot/src/parrot/memory/render.py --max-tokens 800
wikitoolkit ledger blockers FEAT-585                   # unacknowledged criticals that block the merge
wikitoolkit ledger acknowledge issue:... --reason "..." --actor human:jlara   # humans only
wikitoolkit ledger plan-fix [--severity major] [--lane fast|sdd] --json   # batch for /sdd-fix

wikitoolkit ledger ingest-sdd        # specs + task indexes → spec:/task: nodes
wikitoolkit ledger sync              # applies pending events to the index
wikitoolkit ledger rebuild           # rebuilds from the log (re-run ingest-sdd afterwards)
wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> [--no-reconcile] · wikitoolkit ledger compact
```

**Shared event log (FEAT-694).** `sdd/ledger/events.jsonl` (+ `sdd/ledger/archive/`) is a
git-tracked, append-only copy of the ledger events, merged by git with `merge=union`
(`.gitattributes`). The `parrot-ledger` post-merge, post-checkout and post-rewrite hooks import it into the
local ledger; the pre-commit block is a no-op since FEAT-758 — events reach `origin/dev` only through
`/sdd-done`'s outbox delivery (`wikitoolkit ledger outbox prepare|status|integrate`, see
`wiki/sdd-tooling/sdd/ledger-outbox.md`). `wikitoolkit ledger rotate-log --older-than-days N` is explicit maintenance;
`/sdd-done` no longer rotates. Existing checkouts: re-run `parrot claude install` once to upgrade the hooks.

Kinds: `bug | tech_debt | feature_gap | vulnerability`. Severities:
`critical | major | minor | low`. `--discovered-from`: `spec:<FEAT>`,
`task:<TASK>`, `review:<TASK>`.

---

## 6. Namespaces: federating several wikis

`ns add` is the **only** namespace writer; neither `build` nor `ingest-jira`
self-register.

| Kind | Flag | Points to |
|---|---|---|
| `path` | `--project <dir>` | another project with `.parrot/wiki.json` |
| `store` | `--store <dir>` | prebuilt store (`wiki.db` inside) |
| `database` | `--database <db>` | ArangoDB (`--backend arangodb`) or satellite backend (`--backend ontology_legal`) |
| `vault` | `--vault <dir>` | Obsidian vault (requires `.obsidian/`) |

```bash
wikitoolkit ns add asyncdb --project ~/proyectos/asyncdb --description "AsyncDB codebase"
wikitoolkit ns add issues  --store ~/.parrot/wikis/issues/.parrot/wiki --global --description "Jira"
wikitoolkit ns add notes   --vault ~/vaults/work-notes --global --weight 0.8
wikitoolkit ns add legal   --database legal_db --backend ontology_legal --credentials-env LEGAL_ARANGO
wikitoolkit ns list [--json]
wikitoolkit ns remove notes --global
```

- Without `--global` → the repo's `.parrot/wiki.json`; with `--global` →
  `${PARROT_HOME:-~/.parrot}/wikis.json`. The repo wins on a name collision.
- Names: `^[A-Za-z0-9][A-Za-z0-9_.:-]*$`; `all` and `local` are reserved.

```bash
wikitoolkit query "tenant in the URL"                 # all namespaces (default if there are any)
wikitoolkit query --ns issues "tenant in the URL"
wikitoolkit query --ns "issues,notes" "..."
wikitoolkit query --ns local "..."                   # the repo wiki only
wikitoolkit page issues::file:NAV-9372.md
wikitoolkit related notes::file:Retro.md
wikitoolkit query --store docs/parrot "..."          # any store, without registering it
```

Writes always go to the local plane; foreign planes are opened
read-only and there are **no edges between namespaces** (`link` rejects them).

---

## 7. Jira ticket plane (`ingest-jira`, FEAT-454)

Deterministic and LLM-free: each ticket from the JQL becomes a markdown file in
`${PARROT_HOME}/wikis/issues` (outside the repo, G8) and the plane is built.

```bash
# credentials (JiraToolkit's): JIRA_INSTANCE, JIRA_AUTH_TYPE (no default), JIRA_USERNAME,
# JIRA_API_TOKEN | JIRA_SECRET_TOKEN | JIRA_OAUTH_*; optional JIRA_WIKI_JQL, JIRA_WIKI_AC_FIELD

wikitoolkit ingest-jira --project NAV --backfill          # first load: --force + concurrency 16 + completeness check
wikitoolkit ingest-jira                                   # incremental from the watermark (daily cron)
wikitoolkit ingest-jira --jql 'project in (NAV, FORMS) AND updated >= -30d'
wikitoolkit ingest-jira --since 2026-09-01T00:00:00 --dry-run --json
wikitoolkit ingest-jira --force                           # re-renders the whole scope
wikitoolkit ingest-jira --no-build                        # documents only

# ONCE, by hand, after the first sweep:
wikitoolkit ns add issues \
  --store "${PARROT_HOME:-$HOME/.parrot}/wikis/issues/.parrot/wiki" \
  --global --description "Jira ticket corpus"

wikitoolkit query --ns issues "forms tenant"
wikitoolkit page issues::file:NAV-9372.md
```

```cron
17 6 * * *  cd /path/to/checkout && /path/to/.venv/bin/wikitoolkit ingest-jira --quiet >> /var/log/parrot/jira-ingest.log 2>&1
```

Everything written under `<!-- jira-sync:end -->` in a document survives every
re-sync. A `partial` run (errors) exits ≠ 0 and does **not** advance the watermark.
Comments and attachments are not synced in v1.

---

## 8. Obsidian

### Vault → wiki (the vault as source)

```bash
wikitoolkit build --path ~/vaults/work-notes          # auto-detects .obsidian/
wikitoolkit build --vault --path ~/folder/markdown   # forces vault mode
wikitoolkit ns add notes --vault ~/vaults/work-notes --global   # queryable from the repo
```

Extracts: notes → `file:` (category `document`), `[[wikilink]]` → `references`,
`![[embed]]` → `embeds`, `#tag` → `tagged` + `tag:` page, folders →
`contains`, YAML frontmatter indexed in FTS. With `vault_dir` in
`.parrot/wiki.json` the MCP exposes `vault_ingest`.

### Wiki → vault (`sync obsidian`, one-way mirror)

```bash
wikitoolkit sync obsidian --dry-run -v
wikitoolkit sync obsidian --vault ~/vaults/work-notes --ns local
wikitoolkit sync obsidian --ns all --category decision --category lesson --prune
```

Config in `.parrot/wiki.json` (flags override it per run):

```json
"obsidian_sync": {
  "vault_dir": "~/vaults/work-notes",
  "root_folder": "LLM Wiki",
  "categories": ["decision", "lesson", "note", "document"],
  "folders": { "decision": "Decisions", "lesson": "Lessons" },
  "namespaces": ["local", "issues"],
  "prune": false
}
```

Each note carries `wiki_sync` / `wiki_scope` / `wiki_id` frontmatter; `--prune`
only deletes notes with that marker. Edges between synced pages become
`[[wikilinks]]` in a `## Related` section (visible in the graph view).

---

## 9. Bookstore: indexed library (PageIndex)

Project library in `.parrot/library`, global in `~/.parrot/library`
(or `PARROT_LIBRARY_DIR`). Optional LLM: `PARROT_BOOKSTORE_LLM="provider:model"`
(+ `PARROT_BOOKSTORE_LLM_LIGHT`). Without an LLM, in-book search needs `bm25s`.

### Parse and catalog books

```bash
parrot bookstore locations                                # where each library is and its status
parrot bookstore add libro.pdf                            # pdf/md/txt/epub/mobi/docx → index + card
parrot bookstore add libro.epub --global --title "..." --author "..." --topic "..."
parrot bookstore add notas.md --no-llm                    # without LLM carding/summaries
parrot bookstore add libro.pdf --relate --llm anthropic:claude-haiku-4-5
parrot bookstore add-folder ~/libros -r --dry-run
parrot bookstore add-folder ~/libros -r --global --relate
parrot bookstore card <book_id> --refresh --llm anthropic:claude-haiku-4-5   # redo the card
parrot bookstore remove <book_id> --yes
```

### Query

```bash
parrot bookstore list [--json] [--by-community]
parrot bookstore show <book_id> [--json]                  # full card
parrot bookstore toc <book_id>                            # table of contents with node ids
parrot bookstore search "transactional isolation"          # cross-book
parrot bookstore search "..." --book <book_id>            # within one book
parrot bookstore search "..." --catalog-only              # cards only
```

### Book graph (FEAT-533)

```bash
parrot bookstore relate --all --no-llm          # Stage 1: same_author / shares_topic / same_era ... (no LLM)
parrot bookstore relate --all                   # + Stage 2 LLM (influenced_by, responds_to, parallels, contrasts_with), 1 prompt per book
parrot bookstore relate --communities-only      # Stage 3 only (Leiden/Louvain)
parrot bookstore relate <id1> <id2> --force     # re-judge already recorded pairs
parrot bookstore related <book_id> --rel same_author --depth 2 --json
parrot bookstore communities [--json]
```

### Books as a wiki plane

```bash
parrot bookstore export-wiki                    # <library>/wiki + registers the `bookstore` namespace in .parrot/wiki.json
parrot bookstore export-wiki --global           # global library → ~/.parrot/wikis.json
parrot bookstore export-wiki --out ~/wikis/books --no-register

wikitoolkit query --ns bookstore "stoicism and duty"
wikitoolkit page bookstore::book:<book_id>
wikitoolkit related bookstore::book:<book_id>
parrot bookstore communities                    # graph communities; graph.html is left in <library>/wiki
```

One page per book (`category=book`), one edge per relation; `wiki.db` is
rebuilt entirely on each export. A pre-existing `bookstore` namespace pointing to another
store is rejected: run `wikitoolkit ns remove bookstore` first.

### MCP server and skill

```bash
parrot bookstore mcp                            # stdio: bookstore_catalog_search, get_toc, search_book,
                                                #   read_section, search, related_books, communities, ...
parrot claude install                           # registers it if library.db exists (--no-bookstore to skip)
parrot codex install --no-build                 # same for Codex ($bookstore in the prompt)
```

Research funnel: `catalog_search` → `related_books`/`communities` →
`get_toc` → `search_book`/`search` → `read_section`; cite the `origin` of each
relation (`deterministic` / `llm` + confidence / `community`).

---

## 10. Supervised document ingestion (`ingest`, FEAT-402)

For PDF/DOCX/PPTX/XLSX/HTML/EPUB/MD/TXT corpora with editorial control: a
YAML charter (`.parrot/charter.yaml`, example in
`sdd/state/FEAT-402-supervised-wiki-ingestion/references/charter.example.yaml`)
defines scope, audience and thresholds; a lightweight model triages and only the gray zone
escalates to the heavy model. Exactly **one** mode per run.

```bash
export WIKI_LIGHTWEIGHT_MODEL=anthropic:claude-haiku-4-5
export WIKI_MODEL=anthropic:claude-sonnet-5

wikitoolkit ingest ~/docs/specs/ --dry-run                     # manifest, ingests nothing
wikitoolkit ingest ~/docs/specs/ --review .parrot/wiki/ingest-manifest.jsonl   # applies edited decisions
wikitoolkit ingest ~/docs/specs/ --interactive                 # asks per document
wikitoolkit ingest ~/docs/specs/ --auto --audit-rate 0.2       # charter thresholds decide
wikitoolkit ingest https://example.com/paper.pdf --interactive --fetch-timeout 60
wikitoolkit ingest ~/docs --no-recursive --charter other/charter.yaml --manifest /tmp/m.jsonl
wikitoolkit ingest roblox-api [--refresh]                      # federated plane of the Roblox API (FEAT-532)
```

---

## 11. Architectural decisions (`adr`)

```bash
wikitoolkit adr sync [paths...]                    # refreshes ADRs (docs/adr, docs/adrs, docs/decisions); no LLM
wikitoolkit adr lookup AbstractBot.save_conversation_turn --budget 2000
wikitoolkit adr why "why clients do not load history" --include-history
wikitoolkit adr generate sym:packages/.../abstract.py#AbstractBot   # candidates (requires generation_enabled + a model)
wikitoolkit adr review <decision_id> --action accept --expected-revision 1 --actor human:jlara --reason "..."
wikitoolkit adr review <decision_id> --action link --documented-id <adr_id> --expected-revision 2 --actor human:jlara
wikitoolkit adr export <decision_id>
```

---

## 11.1. Standup briefs and entities

```bash
wikitoolkit standup                              # daily brief in English
wikitoolkit standup --period week --language es  # weekly brief in Spanish
wikitoolkit standup --no-llm                     # without LLM summary
wikitoolkit standup --out ./standups             # archive directory (not a file name)
wikitoolkit standup --team                       # include the whole team
wikitoolkit standup --no-store --no-file --json  # JSON output only, write nothing
wikitoolkit entity add <type> <title>            # create a typed entity
wikitoolkit entity list                          # list entities
wikitoolkit entity reindex --store <path>        # reindex a foreign plane
```

Full reference: [standup.md](standup.md) (FEAT-627). For cron and back-fill, see the [standup runbook](../operations/runbooks/wiki-standup.md).
Lint reference: [lint.md](lint.md) (FEAT-625). Inbox pipeline reference: [inbox.md](inbox.md) (FEAT-626).

---

## 12. Export the wiki as markdown

```bash
wikitoolkit export -o docs/knowledge-base        # one .md per page + index.md (adds the dir to exclude_dirs)
/parrotwiki --wiki docs/knowledge-base           # same from Claude Code
```

---

## 13. Configuration and environments

- `.parrot/wiki.json` — base config (`wiki_name`, `storage_dir`, `backend`,
  `exclude_dirs`, `namespaces`, `vault_dir`, `obsidian_sync`, `sync_graph`,
  `claude.nudge_cooldown_seconds`, `decisions.*`, `symbol_depth`).
- `.parrot/wiki.<env>.json` — partial per-environment overlay, no credentials.
  Resolution: `WIKI_ENV > ENV > "local"`. This repo commits
  `wiki.local.json = {"backend": "sqlite"}` (offline, no VPN).
- `${PARROT_HOME:-~/.parrot}/wikis.json` — global namespace registry.
- Useful variables: `WIKI_STORE`, `WIKI_STORE_BACKEND`, `WIKI_ENV`,
  `WIKI_MODEL`, `WIKI_LIGHTWEIGHT_MODEL`, `WIKI_EXTRACT_LLM`,
  `PARROT_HOME`, `PARROT_LIBRARY_DIR`, `PARROT_BOOKSTORE_LLM`,
  `JIRA_WIKI_JQL`, `JIRA_WIKI_ISSUES_DIR`, `ARANGODB_*`.

---

## 14. Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `query --ns issues` / `--ns bookstore` returns nothing | namespace not registered | `wikitoolkit ns add ...` (or `export-wiki` without `--no-register`) and `ns list` |
| Stale results / new file does not appear | stale plane | `wikitoolkit upsert <paths>` o `wikitoolkit build` |
| Git hook does not run | `core.hooksPath` points to a nonexistent path | check `.git/config` |
| `ingest-jira` reports `partial` with 0 fetched | silent Jira Cloud auth failure / `JIRA_AUTH_TYPE` unset | rotate credentials, set `JIRA_AUTH_TYPE` |
| `ledger rebuild` lost specs/tasks | those nodes are not event-sourced | `wikitoolkit ledger ingest-sdd` |
| `link` rejects the edge | pages in different planes | there are no cross-namespace edges; use `query` |
| `bookstore mcp` does not start | no `library.db` | `parrot bookstore locations`, index a book |
| `wikitoolkit mcp` crashes in Claude Code | wiki not built in that repo | `wikitoolkit build` |
