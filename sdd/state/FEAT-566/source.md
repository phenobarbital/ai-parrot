---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: SDD Work Ledger — discovered work, spec graph and insights on the LLM Wiki plane

**Date**: 2026-09-13
**Author**: Jesus Lara (drafted with Claude)
**Status**: exploration
**Recommended Option**: B
**Inspiration**: `gastownhall/beads` (`bd ready` / `bd update --claim` / `bd close` / `discovered-from` / `bd remember` / `bd prime` / `bd compact`)

---

## Problem Statement

The SDD pipeline (`/sdd-brainstorm → /sdd-proposal → /sdd-spec → /sdd-task → /sdd-start → /sdd-done`) tracks *planned* work well: per-spec task indexes under `sdd/tasks/index/*.json`, a deterministic `close_task.sh`, and `/sdd-next` computing readiness from `depends_on`. What it does not track is everything an agent learns **while** executing a task and decides not to act on:

1. **Discovered work is dropped.** A bug spotted by the worker mid-task, or a 🟡 Major / 🔴 Critical finding that `/sdd-codereview` confirms but leaves unfixed because it is outside the task's scope, has no sink. The review report template has no "Deferred" bucket, saving the report is optional and uncommitted (`sdd/reviews/` holds 5 files against 3427 completed tasks), and `done-with-issues` is a terminal status whose detail lives only in free text. Nothing aggregates these, so nothing ever schedules them.
2. **Specs are files, not nodes.** `spec:` ↔ `task:` ↔ code relationships exist implicitly (task files list Scope/Files; specs list modules) but are not queryable. "Which open specs touch `BaseWikiStore.upsert_pages`?" or "what is the blast radius of FEAT-532?" cannot be asked.
3. **Insights have no provenance.** `wiki_remember` exists (`mem-<sha1[:12]>` pages, `origin="memory"`) but the link to *where the insight came from* (task, review finding, symbol) is optional and usually absent; `bd prime`-style scoped injection is impossible without it.
4. **The wiki plane does not exist inside worktrees.** `find_project_root()` returns the linked worktree root (its `.git` *file* satisfies `.exists()`), `.parrot/*` is gitignored, so `DevLoopWikiSearch.from_project()` returns `None` in every `feat-FEAT-NNN-*` worktree. Any "write from the worktree" design must first decide **where** the shared state lives — and the owner's constraint is explicit: `sdd-*` agents write to the **main worktree's** `.parrot/`, never to per-worktree copies that would need merge/conflict resolution.

Who is affected: the SDD worker (Claude Code / Codex subprocess), `/sdd-codereview`, `/sdd-next`, `/sdd-done`, and `dev_loop`'s research node. Why now: `wikitoolkit mcp` is already mounted in Claude Code, the structural plane (`sym:` pages, FEAT-498) gives stable ids to point at, and the review-coverage number above shows the leak is real.

## Constraints & Requirements

- **Shared state lives in the main worktree's `.parrot/`.** Agents running inside `.claude/worktrees/<name>` resolve and write there. No per-worktree ledger copies, no git merge of ledger state. (Owner constraint.)
- **SQLite is the default wiki backend and must stay safe under N concurrent worktree agents on one host.** Today: WAL is on (`WIKI_SCHEMA_SQL` line 1), `busy_timeout` is never set, `_migrate()` issues an `UPDATE meta …` on *every* connection (write lock even for readers), and a full `build` holds the advisory `wiki.lock` for minutes. A ledger write must never fail because a structural rebuild is running.
- **Recording must never block or fail the agent.** Filing a finding is a side effect of the real task; if the index is locked, the record must still be durable.
- **Ids stable across branches and machines.** Hash-based (beads' lesson), never sequential — `.id_ledger.json` CAS-on-push is fine for TASK/FEAT ids but too heavy for something an agent does ten times per session.
- **Provenance mandatory.** Every issue and insight carries `discovered-from`/`derived-from` (a `task:`/`spec:`/`review:` id) and, when applicable, `about` (`sym:`/`file:` ids from the structural plane).
- **No new heavy dependency.** Reuse `SQLiteWikiStore`, `WikiPageRecord`, edges with `provenance`, `wikitoolkit mcp`, the Claude Code installer. Dolt/Postgres/Arango are not required for v1; the Arango/Postgres backends must remain possible.
- **Structural plane semantics are branch-dependent.** `file:<rel>` / `sym:<rel>#<qualname>` pages reflect *one* checkout's content. A shared structural plane must not be silently overwritten with feature-branch content by a worktree agent.
- **Language split:** all identifiers, page ids, event kinds and docs in English.
- **Validation-first:** a spike proves (a) common-dir resolution from a linked worktree, (b) N writers on the shared SQLite file with the proposed pragmas, (c) append-only log atomicity, before `/sdd-spec`.

---

## Options Explored

### Option A: One shared `wiki.db` at the main worktree, everything as pages

Resolve the shared root via the git common dir and point *all* wiki access — structural plane, remember/note, and the new `spec:`/`task:`/`issue:`/`insight:` pages — at `<main>/.parrot/wiki/wiki.db`. Issues are pages with a mutable `status` field in the body/frontmatter; `bd ready` is a query over pages + edges.

✅ **Pros:**
- One graph, one store, one set of tools; `neighbors()` crosses `issue:` → `sym:` natively.
- Smallest surface: no new DB, no new file format.

❌ **Cons:**
- Every ledger write contends with structural writes on the same file. `build` holds `wiki.lock` for minutes; `replace_source_slice` commits per source but a repo scan is hundreds of them. With the default 5 s timeout an agent filing a bug during a rebuild gets `database is locked`.
- Mutable status inside page bodies is not event-sourced: no audit trail, no idempotent replay, no rebuild if the DB is lost.
- Structural pages written from a worktree would inject feature-branch content into the shared (base-branch) plane — the content-divergence problem is unsolved, not just the locking one.
- `_migrate()`'s per-connection `UPDATE` becomes a hot spot with many concurrent readers.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` (already used) | async SQLite | already the store driver |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/store.py::SQLiteWikiStore` — pages/edges/FTS/neighbors.
- `knowledge/wiki/project.py::find_project_root` — needs a common-dir-aware variant.

---

### Option B: Shared root + separate **ledger plane** (append-only event log + `ledger.db` index) — *recommended*

Two changes in `project.py`: `find_shared_root()` resolves the **main worktree** (`.git` file → `gitdir:` → `commondir`, exactly what `installer._git_hook_path` already does for hooks; `PARROT_SHARED_ROOT` env override), and a second storage dir `<main>/.parrot/ledger/`.

The ledger plane has two layers:

1. **`events.jsonl`** — the source of truth. One JSON object per line, appended with `O_APPEND` in a single `write()` (< 4 KiB per event). Event id = `sha1(kind|subject|actor|ts|payload)[:12]`. Kinds: `issue.opened / claimed / closed / superseded / linked`, `task.started / closed`, `spec.registered`, `insight.recorded / superseded`. Appending needs no SQLite lock and cannot fail on contention; it is the durable record.
2. **`ledger.db`** — a `SQLiteWikiStore` instance (same class, different `storage_dir`) that is a **rebuildable index** of the log: reduce events → `issue:<hash>`, `task:<TASK-ID>`, `spec:<FEAT-ID>`, `insight:<hash>` pages, edges `discovered-from`, `derived-from`, `about`, `blocks`, `implements`, `touches`, `supersedes`, `duplicates`. `wikitoolkit ledger rebuild` replays the log. Writes are write-through: append event, then best-effort upsert into `ledger.db`; if the upsert fails (locked), the next `ledger sync` repairs from the log (idempotent by event id).

Structural plane policy in v1: the shared `wiki.db` reflects the **base branch** (built and `--changed`-upserted in the main worktree by the existing post-commit hook, plus `post-merge`); **linked worktrees never write it**. The hook block and `ast_edit`'s synchronous upsert become no-ops when `git rev-parse --git-dir != --git-common-dir`. Worktree agents read it (slightly stale for files they themselves edited — which they already hold in context) and reference `sym:` ids that stay valid after merge.

SQLite hardening (benefits both DBs): pass `timeout=` (→ `busy_timeout`) in `aiosqlite.connect`, `BEGIN IMMEDIATE` for write paths, and make `_migrate()` read the version before issuing the `UPDATE` so readers never take a write lock.

Query surface: MCP tools `ledger_open`, `ledger_ready`, `ledger_claim`, `ledger_close`, `ledger_context`; CLI mirror `wikitoolkit ledger …` for the bash/jq-based slash commands; `ledger` registered as a **federation namespace** so `wiki_query` / `wiki_related` see both planes without a new read path.

✅ **Pros:**
- Locking risk is confined to a tiny, low-volume file that nothing long-running ever touches; a structural rebuild cannot block a `ledger_open`.
- Recording is lock-free and durable; the index is disposable. Same shape as beads' original JSONL+cache split.
- Event-sourced status gives audit trail, idempotent replay, atomic claim (`INSERT … WHERE NOT EXISTS` under `BEGIN IMMEDIATE`) and `compact` as a *view* operation.
- Cross-plane edges are just ids; `neighbors()` already returns dangling targets (`LEFT JOIN pages`), so `issue:` → `sym:` works before/after the symbol page exists.
- Structural-plane divergence is solved by policy (read-only from worktrees), not by machinery.

❌ **Cons:**
- Two SQLite files under `.parrot/`; a "whole graph" query goes through the federation layer (which qualifies foreign ids with `ns::` — see Open Questions).
- The base-branch-only structural plane is stale for the files a worktree is editing until merge. Acceptable in v1; an overlay per worktree is a later feature.
- One more file format to document (`events.jsonl` schema, versioned).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` | ledger index | already a dependency; add `timeout=` |
| stdlib `json`, `os.open(O_APPEND)`, `hashlib` | event log | no new deps |
| `click` | `wikitoolkit ledger` group | already the CLI framework |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/store.py::SQLiteWikiStore`, `WikiPageRecord`, `neighbors`, `search_fts`, `create_wiki_store` — the ledger index *is* a wiki store.
- `knowledge/wiki/project.py::wiki_write_lock`, `WikiProjectConfig.storage_path/db_path` — add `ledger_path`.
- `knowledge/wiki/claude_code/installer.py::_git_hook_path` — extract the `gitdir:`/`commondir` walk into `project.resolve_git_common_dir()`.
- `knowledge/wiki/tools.py::WikiRememberTool` — becomes `insight.recorded` with mandatory provenance when called with `derived_from`.
- `knowledge/wiki/federation.py::FederatedWikiStore` + `wikitoolkit ns add` — mount `ledger` as a namespace.
- `knowledge/wiki/bookkeeper.py::WikiBookkeeper.log_operation` — the audit-line pattern (`log.md`) is the ancestor of `events.jsonl`; keep both or fold `REMEMBER`/`NOTE` into events.
- `flows/dev_loop/wiki_search.py::DevLoopWikiSearch.build_research_context` — extend with ledger context (the `bd prime` analogue, scoped by `about` ∩ task scope).
- `scripts/sdd/close_task.sh`, `.claude/commands/sdd-start.md` §4/§8, `sdd-codereview.md` §5, `sdd-next.md`, `sdd-done.md` §7 — emission and consumption points.

---

### Option C: Git-tracked ledger per branch (`sdd/ledger/events.jsonl`, `merge=union`), no shared DB

Beads-classic without the cache: the event log lives **in the repo**, committed on the feature branch by the slash commands (task-scoped `git add`, as today), merged into `dev` with the feature. `.gitattributes: sdd/ledger/events.jsonl merge=union`. Readiness is computed by `jq` over the log, like `/sdd-next` does over the indexes today. Wiki pages for `issue:`/`insight:` are ingested from the log by the post-commit hook in the main worktree.

✅ **Pros:**
- Zero concurrency machinery: no shared file, no SQLite contention, nothing outside git.
- The ledger travels with the repo (clones, CI, other machines), reviewable in PRs.
- Consistent with how `sdd/tasks/index/*.json` already flows.

❌ **Cons:**
- **Violates the owner constraint**: state is per worktree until merge. An issue filed in worktree A is invisible to `/sdd-next` on `dev` and to worktree B; two worktrees closing/claiming the same item diverge until merge. `merge=union` handles line-level conflicts but not semantic ones (double claim).
- `/sdd-next` and `/sdd-start` run on the base branch / worktree respectively; cross-worktree awareness would again rely on `git worktree list` heuristics.
- The "prime" context can only include what has been merged.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jq`, git `merge=union` | readiness + merge | no Python changes for the ledger itself |

🔗 **Existing Code to Reuse:**
- `.claude/commands/sdd-next.md` jq pipeline; `scripts/sdd/heal_orphans.sh` as the model for post-merge reconciliation.

*(Worth keeping as the **export** format of Option B: `/sdd-done --merge` snapshots `ledger.db` → `sdd/ledger/issues.jsonl` on `dev` for backup, PR visibility and other machines — exactly beads' `issues.jsonl` role.)*

---

### Option D: Separate service-backed tracker (Postgres via `asyncdb`, or ArangoDB alongside GraphIndex)

Stand up the ledger as its own store outside `.parrot/`: Postgres tables (`ledger_events`, `ledger_items`, `ledger_edges`) behind an `asyncdb` model, or an ArangoDB graph next to the existing `wiki_pages`/`wiki_edges` collections, with MCP tools in front.

✅ **Pros:**
- True multi-writer, multi-host concurrency; no SQLite locking discussion at all.
- Natural fit when several developers/machines share one SDD backlog; Arango gives real graph traversals.

❌ **Cons:**
- Requires a running service for a *local* dev loop; the whole `wikitoolkit` value is that it works offline in `.parrot/`.
- Duplicates the page/edge/FTS/tool surface the wiki already has, or forces the wiki to the Arango backend for everyone.
- Over-scoped for a single-developer, single-host workflow; the beads authors explicitly moved to Dolt only for multi-agent *fleet* scenarios.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` / `asyncpg` | Postgres ledger | already in the stack |
| `python-arango` | graph ledger | `arango_store.py` already exists |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/arango_store.py`, `postgres_store.py` — as an alternative *backend* for Option B's `ledger.db` later, not as a separate system.

---

## Recommendation

**Option B** is recommended because it satisfies the owner constraint (one shared `.parrot/` at the main worktree) while separating the three problems that "write from worktrees" actually bundles:

1. **Location** — resolved deterministically from git's common dir; nothing to configure, and the same walk the hook installer already performs.
2. **Contention** — the ledger is its own low-volume SQLite file plus a lock-free append log, so the only long-running writer in the system (`build`) can never block a `ledger_open`. WAL + `busy_timeout` + `BEGIN IMMEDIATE` + the `_migrate()` fix cover N local agents comfortably at tens of writes per session; the log makes the index disposable if that ever proves wrong.
3. **Content divergence** — the structural plane stays a base-branch snapshot; worktrees read, never write. This is a policy line in the hook and in `ast_edit`, not new infrastructure, and it is the right default even without the ledger.

What we trade: a second DB file and a slightly stale structural view inside worktrees. Both are cheap. Option D remains available as a backend swap (`ledger.db` is a `BaseWikiStore`; Arango/Postgres backends exist) if the workflow ever becomes multi-host. Option C's git-tracked JSONL survives as the export.

---

## Feature Description

### User-Facing Behavior

- **`/sdd-codereview`** gains a mandatory *Deferred findings* table. Every CONFIRMED 🔴/🟡 finding not fixed in-review is filed with `wikitoolkit ledger open --kind bug --severity major --discovered-from task:TASK-NNN --about "sym:<rel>#<qualname>" --title … --body …` and the report shows the resulting `issue:` id. A review with unfixed confirmed findings and an empty Deferred table is invalid.
- **Worker in `/sdd-start`** (and dev_loop's development node) files anything out-of-scope it notices the same way, then continues. Rule text mirrors beads: *use the ledger for all discovered work; never leave TODO comments or markdown lists as the only record.*
- **`/sdd-next`** lists unblocked TASKs **and** open `issue:` items (kind, severity, discovered-from), sorted by priority; an issue can be promoted with `/sdd-task --from-issue <id>` (creates a TASK, links `implements`, marks the issue `superseded`).
- **`/sdd-start` prime step**: before §7, the command injects `ledger_context` for the task's Scope/Files — open issues and insights whose `about` edges intersect the task's `file:`/`sym:` set, plus insights `derived-from` the same spec. This is `bd prime`, scoped by the graph instead of "all memories".
- **`/sdd-done`** ("landing the plane"): §7 prints open issues discovered from this feature's tasks and refuses `--merge` if any 🔴 is open and unacknowledged (`--ack-open-critical`). On merge it exports `sdd/ledger/issues.jsonl` and commits it with the merge commit.
- **`wiki_remember`** from an SDD context requires `derived_from` (task/spec/review id); `about` optional. Unprovenanced remembers remain allowed outside SDD but are flagged by `wikitoolkit ledger audit`.
- **`wikitoolkit ledger compact --older-than 30d`** folds closed issues per `spec:` into a `digest:` page with `supersedes` edges. Events are never deleted.

### Internal Behavior

1. `project.find_shared_root()` → main worktree (common dir walk; `PARROT_SHARED_ROOT` override; falls back to `find_project_root()` when not a linked worktree). `WikiProjectConfig.ledger_path(root)` → `<shared>/.parrot/ledger/`.
2. `LedgerLog.append(event)` — validates the Pydantic event model, serialises to one line, `os.write` on an `O_APPEND` fd. Returns the event id.
3. `LedgerIndex` (a `SQLiteWikiStore` over `ledger.db`) — `apply(event)` reduces to page upserts + edges under `BEGIN IMMEDIATE`; `rebuild()` truncates and replays; `sync()` applies events after the last applied id (stored in `meta`). Claims: `issue.claimed` is applied only if the current status is `open` (checked inside the same immediate transaction) — the atomic `--claim`.
4. `LedgerService` — the tool/CLI facade: `open`, `ready`, `claim`, `close`, `link`, `context`, `compact`, `audit`. `context(scope)` = FTS + `neighbors(rel="about")` over the given `file:`/`sym:` ids, packed with `pack_results`.
5. SDD ingestion — `wikitoolkit ledger ingest-sdd` scans `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` **in the main worktree** into `spec:`/`task:` pages with `implements`/`blocks`/`touches` edges (from the task's Scope/Files section resolved to `file:` ids). Runs from the post-commit/post-merge hook in the main worktree; worktree-side status changes arrive as `task.started`/`task.closed` events emitted by `sdd-start` §4 and `close_task.sh`.
6. Federation — `wikitoolkit ns add ledger --path <shared>/.parrot/ledger` at install time so `wiki_query`/`wiki_related` read both planes.
7. Structural-plane write policy — `assets.git_hook_block` and `ast_edit` check `is_linked_worktree(root)`; if true, skip the structural upsert (log a debug line). `post-merge` hook added in the main worktree so `dev` merges refresh the plane.

### Edge Cases & Error Handling

- **`ledger.db` locked** → the event is already on disk; `apply` retries once after `busy_timeout`, then returns `{"status": "logged", "indexed": false}`. `ledger sync` heals.
- **Event > 4 KiB** → reject at validation (bodies are truncated to a summary; long content goes into the page body via a follow-up `issue.linked` to a `note:` page).
- **Same finding filed twice** (two reviewers) → deterministic id from `(kind, title, discovered_from)` makes `open` idempotent; `duplicates` edge when titles differ but `about` + fingerprint match (heuristic, non-blocking).
- **Log corruption / partial line** → `rebuild` skips unparsable lines and reports them; never raises.
- **Not a git repo / `PARROT_SHARED_ROOT` points elsewhere** → shared root = project root; ledger still works single-checkout.
- **Worktree running an old `wikitoolkit`** → the hook block resolves an absolute binary today (`resolve_wikitoolkit_bin`); the ledger CLI must be present in that binary or the slash command fails loudly (`exit 4`), never silently skipping the record.
- **Sync `sqlite3` connection in `sources.py`** → unchanged; it never touches `ledger.db`.
- **Dangling `about` targets** (symbol renamed) → surfaced by `ledger audit` using the existing `broken_edges()` API; the issue stays open.

---

## Capabilities

### New Capabilities
- `wiki-shared-root`: main-worktree resolution of `.parrot/` from linked worktrees (`find_shared_root`, `resolve_git_common_dir`, `is_linked_worktree`, env override).
- `wiki-ledger-log`: append-only `events.jsonl` with Pydantic event models and hash ids.
- `wiki-ledger-index`: `ledger.db` reducer/rebuild/sync, atomic claim, compact, audit.
- `wiki-ledger-tools`: MCP tools + `wikitoolkit ledger` CLI group + federation namespace registration.
- `sdd-ledger-integration`: emission points in `sdd-start`, `close_task.sh`, `sdd-codereview` (Deferred table), consumption in `sdd-next`, `sdd-done`, `sdd-task --from-issue`, prime context.
- `sdd-graph-ingest`: `spec:`/`task:` pages and edges from `sdd/specs` + `sdd/tasks/index`.

### Modified Capabilities
- `wiki-store-sqlite`: `busy_timeout`, `BEGIN IMMEDIATE` on write paths, read-before-write in `_migrate()`.
- `wiki-claude-code-hooks`: hook block skips structural upsert in linked worktrees; `post-merge` installed alongside `post-commit`.
- `wiki-remember`: optional `derived_from` / `about` args, mandatory in SDD context; emits `insight.recorded`.
- `dev-loop-research-context`: `DevLoopWikiSearch` resolves the shared root and appends ledger context.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/wiki/project.py` | extends | `find_shared_root`, `resolve_git_common_dir`, `is_linked_worktree`, `ledger_path` |
| `knowledge/wiki/store.py` | modifies | pragmas/timeout, `BEGIN IMMEDIATE`, `_migrate` read-first — behaviour-preserving |
| `knowledge/wiki/ledger/` (new) | new | `events.py`, `log.py`, `index.py`, `service.py`, `sdd_ingest.py` |
| `knowledge/wiki/tools.py`, `mcp_server.py` | extends | `ledger_*` tools; `wiki_remember` provenance args |
| `knowledge/wiki/cli.py` | extends | `wikitoolkit ledger` group |
| `knowledge/wiki/claude_code/{assets,installer}.py` | modifies | worktree guard in hook block; `post-merge`; `ns add ledger` at install |
| `knowledge/wiki/federation.py` | depends on | ledger mounted as a namespace |
| `flows/dev_loop/wiki_search.py`, `nodes/research.py` | extends | shared root + ledger context |
| `.claude/commands/sdd-{start,next,done,codereview,task}.md` | modifies | emission/consumption steps (prose + bash) |
| `scripts/sdd/close_task.sh` | modifies | emit `task.closed` |
| `sdd/WORKFLOW.md` | modifies | new command rows; quality rule "file discovered work" |
| `.gitignore` / `sdd/ledger/issues.jsonl` | new | export snapshot tracked; `.parrot/ledger/` ignored |

No breaking API changes. New optional config keys in `.parrot/wiki.json` (`ledger.enabled`, `ledger.max_event_bytes`).

---

## Code Context

### User-Provided Code
_None — constraints were given in prose: sdd-* agents must write to the main worktree's `.parrot/`; SQLite concurrency across worktrees is the concern._

### Verified Codebase References
_All paths relative to `packages/ai-parrot/src/parrot/knowledge/wiki/` unless noted; verified against `main` on 2026-09-13._

#### Classes & Signatures
```python
# From project.py:640
def find_project_root(start: Path | None = None) -> Path | None:
    # walks current + parents; returns dir with .parrot/wiki.json, else nearest dir where (candidate / ".git").exists()
    # NOTE: a linked worktree's .git is a FILE → .exists() is True → returns the worktree root

# From project.py:65
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:
    # flock(LOCK_EX|LOCK_NB) on <storage_dir>/wiki.lock; advisory; build refuses, upsert waits briefly

# From project.py:34-43
PARROT_DIR = ".parrot"; CONFIG_FILENAME = "wiki.json"; LOCK_FILENAME = "wiki.lock"; GLOBAL_REGISTRY_FILENAME = "wikis.json"
# project.py:399  WikiProjectConfig.storage_dir default ".parrot/wiki"; :472 storage_path(root); :477 db_path(root) = storage_path/"wiki.db"
# project.py:940  parrot_home() honours PARROT_HOME, else ~/.parrot

# From store.py:299
class WikiPageRecord(BaseModel):
    concept_id: str; node_id: Optional[str]; title: str = ""; category: str = "concept"  # open string
    summary: str = ""; body: str = ""; source_id: Optional[str]; token_count: int = 0
    origin: str = "ingest"        # "ingest" | "authored" | "memory"
    asserted_by: Optional[str]    # "agent:<id>" | "human:<user>"
    updated_at: Optional[str]; content_hash: Optional[str]

# From store.py:819
@asynccontextmanager
async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:   # connection PER CALL; schema replay only if probe short-counts
# store.py:1049-1059  _migrate(conn): PRAGMA table_info + ALTER TABLE …; then
#   UPDATE meta SET value = ? WHERE key = 'schema_version' AND value != ?   ← runs on EVERY connection
# store.py:54   WIKI_SCHEMA_SQL starts with "PRAGMA journal_mode = WAL;"  (only replayed on schema creation)
# store.py:1113-1128  _insert_edges_conn accepts (src,dst,rel) or (src,dst,rel,provenance); PK (src,dst,rel); INSERT OR REPLACE
# store.py:1176
async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str,str,str]]] = None) -> dict[str, Any]
# store.py:1582
async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10)   # excludes category='archive' when category is None
# store.py:1672
async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both")  # LEFT JOIN pages → dangling targets returned
# store.py:1763-1787  lint API: orphan_sources(), broken_edges(), missing_bodies()   (no CLI surface today)
# store.py:1795
def create_wiki_store(storage_dir, wiki_name, backend, **kwargs)   # "sqlite" | "memory" | "arangodb" | "postgres" | registered extras
# store.py:401
def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None

# From tools.py:272
class WikiRememberTool: name = "wiki_remember"   # input tools.py:130 WikiRememberInput(fact, category="note", title=None, link_page_id=None, rel="references")
#   page id "mem-" + sha1(f"{title}::{category}")[:12]; origin="memory"; asserted_by="agent:mcp"; edge only if link_page_id (provenance "asserted", tools.py:327)
# tools.py:354  class WikiNoteTool: name = "wiki_note"  (read-modify-write body append; writes no edges)
# toolkit.py:882
async def remember(self, wiki_name: str, text: str, title: Optional[str] = None, category: str = "note", related_pages: Optional[list[str]] = None) -> dict[str, Any]

# From claude_code/installer.py:619
def _git_hook_path(root: Path) -> Optional[Path]:   # .git file → "gitdir:" → <gitdir>/commondir → <common>/hooks/post-commit
# claude_code/assets.py:47-48 GIT_HOOK_BEGIN/END markers; :166 git_hook_block(root) → "<abs>/wikitoolkit upsert --changed --quiet >/dev/null 2>&1 || true"

# From federation.py:599
class FederatedWikiStore(BaseWikiStore):
    def __init__(self, local: BaseWikiStore, local_name: str = "local", handles: list[NamespaceHandle] | None = None, skipped=None, *, qualify_local: bool = False, origin_local=None)
    # reads fan out over namespaces; writes go to local; foreign ids qualified "ns::<id>"

# From flows/dev_loop/wiki_search.py
class DevLoopWikiSearch:
    @classmethod
    def from_project(cls, root: Optional[Path] = None) -> Optional["DevLoopWikiSearch"]   # None if plane not built; never raises
    async def build_research_context(self, query: str, budget_tokens: int = 4000) -> Optional[str]
```

#### Verified Imports
```python
from parrot.knowledge.wiki.project import find_project_root, load_project_config, WikiProjectConfig, wiki_write_lock
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store, register_wiki_backend
from parrot.knowledge.wiki.federation import FederatedWikiStore
from parrot.knowledge.wiki.tools import WikiRememberTool, WikiNoteTool, create_wiki_tools
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch
```

#### Key Attributes & Constants
- `conf.WORKTREE_BASE_PATH` → default `BASE_DIR/.claude/worktrees` (`parrot/conf.py:828-829`); every dispatcher refuses a cwd outside it.
- `scripts/sdd/sdd_meta.py:164` `WORKTREE_ROOT = ".claude/worktrees"`; worktree names `feat-<FEAT-ID>-<slug>` / `hotfix-<JIRA-KEY>-<slug>`; `base_ref = "origin/<base_branch>"`.
- Per-spec index (`sdd/tasks/index/<slug>.json`): header `feature, feature_id, spec, type, base_branch, created_at, completed_at, tasks[]`; task `id, slug, title, feature, spec, status, priority, effort, depends_on[], assigned_to, file` (+ `started_at`, `completed_at`, `verification`). Statuses: `pending | in-progress | done | done-with-issues`.
- `scripts/sdd/close_task.sh <TASK-ID> <feature-slug> [verified|partial|forced]` — `git mv` active→completed, jq-stamps status, hard-verifies (exit 3).
- `/sdd-start` commits on the **feature branch inside the worktree** (§4 index flip, §7.6 code, §8 close). `/sdd-done` runs **on the base branch**, merges via PR (default) or `--merge`, never onto `main`.
- `/sdd-codereview` report buckets: 🔴 Critical / 🟡 Major / 🟢 Minor; adversarial reviewer is `codex` only; saving the report is optional (`sdd/reviews/TASK-<NNN>-review.md`).
- `.parrot/*` is gitignored (`.gitignore:382`) with the single negation `!.parrot/wiki.local.json` (content `{"backend": "sqlite"}`; read by no wiki code).
- `wikitoolkit` CLI groups today: `mcp, build, upsert, query, page, related, status, communities, export, remember, note, link, memories, audit, ground, ingest, ingest-jira`, groups `symbols`, `ns`, `sync`, per-agent `claude|codex|gemini|google`.

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit lint`~~ — no such subcommand; the lint API (`orphan_sources/broken_edges/missing_bodies`) has no CLI surface.
- ~~`find_shared_root`, `resolve_git_common_dir`, `is_linked_worktree`~~ — nothing in `wiki/` or `flows/dev_loop/` resolves the git common dir except `installer._git_hook_path` (hooks only).
- ~~`PRAGMA busy_timeout`, `PRAGMA synchronous`, `BEGIN IMMEDIATE`~~ — not set anywhere in `wiki/`; the only pragma is WAL at schema creation.
- ~~a "Deferred" / "Out of scope" / "follow-up task" section in `/sdd-codereview`~~ — none; no instruction files unfixed findings anywhere.
- ~~any backlog / issue / tech-debt ledger under `sdd/`, `.claude/`, `wiki/`~~ — `sdd/tasks/.id_ledger.json` is only the TASK/FEAT id allocator.
- ~~atomic task claim~~ — `/sdd-start` claiming is a jq status flip + commit; no lock or lease.
- ~~`sdd/state/<ID>/state.json` as task-execution state~~ — that directory is `/sdd-proposal` research state; `sdd-start/next/done/codereview/status` never read it. Task state is `sdd/tasks/index/*.json`.
- ~~`sdd/tasks/index/_orphans.json`~~ — referenced by `/sdd-next`/`/sdd-status` but not present in the current tree.
- ~~`WikiToolkit.note()`~~ — no such method; note exists only as `WikiNoteTool` and `wikitoolkit note`.
- ~~per-worktree `.parrot/` provisioning in dev_loop~~ — nothing creates, copies or links a plane into a worktree; `from_project` simply returns `None` there.
- ~~`.parrot/wiki.json` in the repo~~ — not tracked; `find_project_root` always takes the `.git` fallback here.
- ~~edge `rel` / `provenance` enums or validation~~ — both are open strings (`extracted` / `asserted` are the only provenance values written).

---

## Parallelism Assessment

- **Internal parallelism**: yes, three lanes after a small foundation task. Lane 1 (`project.py` shared root + `store.py` hardening) unblocks everything; Lane 2 (`wiki/ledger/` log+index+service+CLI+MCP) and Lane 3 (SDD command prose + `close_task.sh` + `sdd_ingest`) are independent once Lane 1 lands and the event schema is frozen in the spec; Lane 4 (dev_loop context, federation mount, hook worktree guard) can proceed against Lane 2's interface.
- **Cross-feature independence**: touches `store.py` (shared with the ast-grep structural plane design, FEAT-498 lineage — `content_hash`, `symbols`), `claude_code/assets.py`/`installer.py` (same design adds `post-checkout/post-merge/post-rewrite`), and `flows/dev_loop/wiki_search.py`. Coordinate the hook changes with that feature: land the `is_linked_worktree` guard once, used by both.
- **Recommended isolation**: `mixed` — one worktree for Lane 1 (sequential, small), then per-lane worktrees.
- **Rationale**: the foundation is a handful of functions everything imports; the rest is additive modules and markdown, which merge cleanly.

---

## Open Questions

- [ ] Federation vs. dedicated read path: `FederatedWikiStore` qualifies foreign ids as `ns::<id>`; do `issue:` → `sym:` edges resolve across the namespace boundary in `wiki_related`, or does the ledger need its own `related` tool in v1? — *Owner: Jesus* (spike)
- [ ] Should `sdd/ledger/issues.jsonl` (Option C export) be committed on every `/sdd-done --merge`, or only on release cut? — *Owner: Jesus*
- [ ] Structural plane in worktrees: is "read-only, base-branch snapshot" acceptable for `ast_edit`'s synchronous upsert (it would be skipped in worktrees), or does that feature need a per-worktree overlay DB from day one? — *Owner: Jesus* (coordinate with the ast-grep design)
- [ ] Event size cap: 4 KiB (single-`write()` atomicity comfort zone) vs. larger with a file lock on the log. — *Owner: Jesus* (spike measures interleaving with N=8 writers)
- [ ] Should `/sdd-insight` (transcript analysis, currently strictly read-only on `sdd/`) emit `insight.recorded` events, or stay a reporting tool? — *Owner: Jesus*
- [ ] Who may `close` an issue: only a TASK that `implements` it, or any agent with a reason (beads allows any)? — *Owner: Jesus*
- [ ] Compaction policy: age-based (`--older-than`) only, or also count-based per spec? Digest page category name (`digest:` vs reuse of `archive`, which `search_fts` already excludes by default). — *Owner: Jesus*
