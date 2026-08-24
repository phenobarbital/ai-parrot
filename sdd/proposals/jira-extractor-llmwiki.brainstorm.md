---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Jira Ticket Extractor → LLM Wiki (`issues` namespace)

**Date**: 2026-08-24
**Author**: Jesus Lara (brainstorm: Claude session 2026-08-24)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Every architectural decision, bug reproduction, customer complaint and
acceptance criterion this team produces lands in Jira — and stays there.
Claude Code cannot reach it. The only path today is `JiraToolkit`, an
agent-facing toolkit: an LLM must decide to call a tool, form a JQL, pay
for the round-trip, and read a JSON envelope. That is fine for "transition
NAV-9269 to Done"; it is useless for "what do we already know about the
forms tenant-in-URL problem", because the answer requires *ranked retrieval
across the whole ticket corpus*, which is exactly what the LLM Wiki does
and what a tool call does not.

Meanwhile the repo already has a knowledge plane Claude Code queries
first (`wikitoolkit query`, plus the six native MCP tools), and FEAT-450
gave it namespaces so a second corpus can be federated in behind
`ns::id`. The ticket corpus is the single largest body of institutional
knowledge not in it.

**Who is affected**: every Claude Code session in this repo (a spec author
who needs the ticket's real acceptance criteria; a debugging session that
should find the three earlier tickets about the same failure), and the
human operators who currently answer those questions from memory.

**Why now**: FEAT-450 (namespaces) and FEAT-451 (`ingest` + document
frontmatter) both just landed. The federation plumbing, the deterministic
frontmatter contract, and the vault-scan build path that turns a folder of
markdown into a queryable plane all exist. The remaining gap is a
deterministic Jira → markdown emitter — a few hundred lines, not a
subsystem.

---

## Constraints & Requirements

- **Zero-LLM default.** The sweep is a cron-safe routine: every frontmatter
  field must be a Jira field or a pure function of one. Byte-deterministic
  for identical input, same contract as `wikitoolkit build`. An opt-in
  `--enrich` flag may add an LLM summary; the default path must never call
  a model.
- **One document per ticket, updatable.** Re-running must update the
  document in place (stable filename + stable `concept_id`), never create a
  second copy, never accumulate duplicate pages or edges.
- **Incremental.** Scope is declared as JQL; each run pulls only issues with
  `updated >=` the last watermark. A daily/weekly cron must stay cheap as
  the corpus grows.
- **Namespaced.** The corpus is a separate plane registered as the `issues`
  namespace (FEAT-450), reachable via `wikitoolkit query --ns issues` and
  the default broadcast. It must never be written into the repo plane that
  the git post-commit hook rebuilds.
- **Off-repo storage.** Generated markdown lives outside the git repo at a
  configurable path (default under `PARROT_HOME`), so internal ticket prose
  and customer names never enter git history or GitHub.
- **No new core dependency.** `jira>=3.10` is an optional extra
  (`ai-parrot-tools[jira]`, host `agents`/`mcp` extras) — never a hard core
  import. Lazy import with an actionable install message.
- **No duplicated Jira code.** `JiraToolkit` and the new sweep must share
  one Jira read implementation, with full auth parity including OAuth 2.0
  3LO.
- **No email in the plane.** Person pages carry display name + accountId
  only.
- **`build` stays untouched** for repo scanning — the same hard non-goal
  FEAT-402 and FEAT-451 both respected.

---

## Options Explored

### Option A: Issue vault — deterministic emitter + the existing vault build path

Split the feature at the markdown boundary, and let already-shipped code
own everything after it.

1. **Shared interface** — a new core package `parrot/interfaces/jira/`
   (client + models) holding the read surface: JQL search with pagination,
   issue fetch, changelog fetch, project/field metadata, and every auth
   mode. `jira` is imported lazily. `JiraToolkit` is refactored to consume
   it, so there is exactly one Jira read implementation. This mirrors
   `parrot/interfaces/obsidian/`, whose own docstring states its purpose:
   *"One vault-access + parsing core reused by ObsidianToolkit, the loaders,
   and wiki vault_scan"*.
2. **Emitter** — a new `wikitoolkit ingest-jira` command: resolve JQL +
   watermark → fetch issues → render one markdown file per ticket into the
   issues directory, with deterministic YAML frontmatter, `[[NAV-1234]]`
   wikilinks for ticket relations, and `#tags`. It also emits one note per
   person, project, component and label.
3. **Build + register** — no new plane code at all. `wikitoolkit build
   <issues-dir> --vault` runs `scan_vault`, which already turns wikilinks
   into `references` edges, `#tags` into first-class tag pages, and folders
   into `contains` pages, writing `<issues-dir>/.parrot/wiki/wiki.db`. Then
   `wikitoolkit ns add issues --store <issues-dir>/.parrot/wiki --global`
   makes it queryable.

The graph is therefore *authored in markdown* and *compiled by existing
code*. The extractor's only job is emitting good markdown.

✅ **Pros:**
- Adds no plane-writing, edge-indexing, staleness or pruning code — the
  vault path already does incremental build, OKF export and `graph.html`.
- Relations come free: a `[[NAV-1200]]` wikilink in a blocked ticket
  becomes a real edge; `#bug`, `#project/NAV` become tag pages that
  aggregate tickets with no extra work.
- The markdown corpus is the deliverable the user asked for: portable,
  greppable, human-readable, diffable, browsable in Obsidian, and
  independent of the plane (rebuildable at any time from files).
- Trivially testable: the emitter is a pure function (issue JSON →
  markdown string). No DB, no LLM, no network in its unit tests.
- Re-sync safety is a file operation (rewrite the file, rebuild), not a
  transactional plane surgery.

❌ **Cons:**
- Two steps (emit, then build) — must be wrapped in one command or a
  documented runbook, or operators will forget the build.
- Edge relations on the vault path are the open strings vault_scan emits
  (`references`, `embeds`, `tagged`), so a wikilink cannot by itself carry
  `blocks` vs `duplicates`; the precise relation must be recovered from the
  frontmatter or asserted afterwards with `wikitoolkit link`.
- Content is duplicated (files + plane bodies), so the plane can drift from
  the files until the next build.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jira>=3.10` | Jira REST client (pycontribs) | Already an extra: `ai-parrot-tools[jira]:51`, host `agents`/`mcp` extras pin `jira==3.10.5`. Lazy import only. |
| `PyYAML` | Deterministic frontmatter dump | Already used by `documents.render_frontmatter` and `okf.frontmatter`. |
| `click` | CLI command | The `wikitoolkit` CLI is already click-based. |
| `pydantic` v2 | `JiraIssue` / `IssueFrontmatter` models | Project standard. |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/vault_scan.py:118` `scan_vault()` — folder of
  markdown → `RepoScan` (pages + edges + tag pages), zero LLM, zero
  embeddings.
- `parrot/knowledge/wiki/cli.py:1044` `build` with the existing
  `--vault/--no-vault` flag (`cli.py:1071-1081`) — forces vault mode
  without requiring an `.obsidian/` directory.
- `parrot/knowledge/wiki/cli.py:1826` `ns add --store` — the only writer of
  namespace entries; exactly what TASK-2382 used for the notes plane.
- `parrot/interfaces/obsidian/` — the shared-interface precedent to copy
  for `parrot/interfaces/jira/`.
- `parrot/auth/jira_oauth.py:86` `JiraOAuthManager` / `:59` `JiraTokenSet`
  — already in **core**, so 3LO parity needs no new dependency direction.
- `parrot/knowledge/wiki/documents.py:209` `render_frontmatter()` — the
  determinism contract (fixed key order, sorted collections, `None`
  omitted) to mirror for `IssueFrontmatter`.
- `parrot/knowledge/graphindex/builder.py:667-704` — the canonical lazy
  optional-dependency import pattern.

---

### Option B: Direct plane writer

Skip files. The extractor builds `WikiPageRecord`s and `(src, dst, rel)`
edge tuples and writes them straight into the issues plane via
`replace_source_slice()`, one source slice per ticket.

✅ **Pros:**
- One step, one command, nothing to forget; no files/plane drift window.
- Full control of typed edges: `blocks`, `duplicates`, `part_of` can be
  written exactly, using the real OKF `RelationType` vocabulary rather than
  vault_scan's three open strings.
- `replace_source_slice()` already gives correct idempotent re-ingest
  semantics (deletes the slice's pages/edges, preserves inbound edges).

❌ **Cons:**
- Loses the artifact the user explicitly asked for ("one document per Jira
  ticket"): nothing to read, diff, grep, browse in Obsidian, or hand to a
  non-Claude consumer. The corpus exists only as a SQLite blob.
- The plane becomes the only copy: a corrupted or deleted `wiki.db` means a
  full re-fetch from Jira, and there is no offline fallback.
- Re-implements what the build path already does (tag pages, directory
  pages, staleness, pruning, OKF export, `graph.html`) or silently goes
  without them.
- Harder to test: every test needs a store fixture instead of asserting on
  a rendered string.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jira>=3.10` | Jira REST client | Same lazy-import constraint. |
| `pydantic` v2 | Issue + page models | Project standard. |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/store.py:215` `WikiPageRecord`, `:906`
  `add_edges()`, `:928` `replace_source_slice()`.
- `parrot/knowledge/wiki/sources.py:68` `SourceCollectionManager` —
  `add_source()`, `mark_ingested()`, `find_by_uri()` for the sync ledger.

---

### Option C: A fourth SOURCE shape on `wikitoolkit ingest`

Teach FEAT-451's widened `SOURCE` argument a `jira:` shape, so
`wikitoolkit ingest "jira:project = NAV AND updated >= -7d"` flows through
the existing acquisition → triage → manifest → HITL pipeline.

✅ **Pros:**
- No new command; the whole FEAT-402/451 apparatus (source ledger,
  document metadata columns, frontmatter projection, decision log, audit
  sampling) applies unchanged.
- Charter-driven triage would let an operator declare *which* tickets are
  wiki-worthy rather than ingesting everything.

❌ **Cons:**
- Fights the pipeline's contract. `ingest` is **LLM-and-charter-driven by
  design**: triage scores each document with a model and routes borderline
  cases to human manifest review. Bolting a zero-LLM cron sweep onto it
  means either paying LLM spend per ticket per run, or adding a bypass flag
  that hollows out the pipeline's purpose.
- The acquisition layer is document-shaped: `resolve_sources()`
  (`documents.py:154`) returns `DocumentRef`s from filesystem paths and
  URLs, and `DocumentAcquirer._acquire_via_loader` (`:632`) calls a
  file loader. A Jira issue is a record, not a file to load — it would need
  a synthetic branch through most of that machinery.
- HITL manifest review in an unattended cron job is a contradiction.
- `DocumentMetadata`'s field vocabulary (`page_count`, `word_count`,
  `loader`) does not describe a ticket; everything real would land in
  `extra`.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jira>=3.10` | Jira REST client | Same lazy-import constraint. |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/documents.py:454` `DocumentAcquirer`, `:154`
  `resolve_sources()`, `:72` `DocumentMetadata`, `:124` `TriageProvenance`.
- `parrot/knowledge/wiki/ingest.py` `WikiIngestOrchestrator`.

---

### Option D (unconventional): Obsidian-native issue vault with a human region

Option A, taken one step further: make the issues directory a **genuine
Obsidian vault** (an `.obsidian/` directory), and give every generated
ticket document a sync marker:

```markdown
<!-- jira-sync:end — everything below is yours; the extractor never touches it -->
```

The extractor owns only the region *above* the marker (frontmatter +
generated fields + description + AC + history) and preserves the tail
verbatim on every re-sync. Humans open the corpus in Obsidian and annotate
tickets in place; agents append findings through the same region with
`wikitoolkit note`. Because the vault is real, the FEAT-450 `vault`
namespace kind applies directly, and the corpus becomes a two-way
knowledge surface rather than a read-only mirror.

✅ **Pros:**
- The corpus accumulates knowledge Jira does not have: "we tried this, it
  didn't work", links to the actual fix, tribal context.
- Human annotations survive every re-sync — the property that decides
  whether people trust a generated corpus enough to write in it.
- Obsidian gives graph view, backlinks and search over tickets for free,
  for humans, with no code.

❌ **Cons:**
- Introduces a merge contract (generated region vs human region) that must
  be honored exactly, or a bad re-sync silently eats someone's notes — the
  single highest-consequence failure mode in this whole feature.
- Encourages hand-editing of the generated region, which the extractor will
  then overwrite; needs a loud comment banner and a documented rule.
- `ns add --vault` requires `.obsidian/` (`cli.py:1864`), so the
  directory must be a real vault, not just vault-shaped.

📊 **Effort:** Medium (as an increment on A)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | No new packages | Reuses `parrot/interfaces/obsidian/` parsing. |

🔗 **Existing Code to Reuse:**
- `parrot/interfaces/obsidian/models.py:38` `ObsidianNote` (frontmatter,
  links, tags, aliases already parsed).
- `parrot/knowledge/wiki/vault_scan.py:58` `VAULT_EXCLUDE_DIRS` — already
  excludes `.parrot` so the vault's own plane is never re-ingested as
  notes.

---

## Recommendation

**Option A** is recommended, with **Option D's sync-marker discipline
adopted as a v1 design constraint** (not deferred).

The decisive argument is that Option A writes almost no new
infrastructure. The graph construction, incremental staleness, pruning, OKF
export and `graph.html` generation the corpus needs already exist behind
`build --vault`; the namespace registration already exists behind `ns add
--store`; the determinism contract already exists in
`documents.render_frontmatter`. What is genuinely missing is a pure
function from issue JSON to a markdown string, and a shared Jira read
interface. That is the whole feature. Option B would hand-roll a second
copy of the plane-writing path to gain typed edges; Option C would fight a
pipeline explicitly built around LLM triage and human review.

What Option A trades away is **edge relation fidelity**. `scan_vault`
emits `references` for every resolved wikilink, so the graph cannot
distinguish `blocks` from `duplicates` from wikilinks alone. This is
acceptable because the distinction is preserved *losslessly in the
frontmatter* (`blocks: [NAV-1200]`, `duplicates: [NAV-980]`), which is
FTS-indexed and read by any agent opening the page — and because the
relation can be upgraded later with `wikitoolkit link --rel blocks` without
re-designing anything. Retrieval quality does not depend on the edge label;
navigability does, and `references` already gives navigability.

Folding in D's marker now rather than later is a deliberate call: the
"human region" is ~10 lines of split-and-preserve logic if designed into
the writer from the start, and a data-loss migration if retrofitted after
people have annotated files.

---

## Feature Description

### User-Facing Behavior

An operator configures scope and storage once:

```bash
export JIRA_INSTANCE=https://trocglobal.atlassian.net
export JIRA_AUTH_TYPE=basic_auth
export JIRA_USERNAME=... JIRA_API_TOKEN=...

wikitoolkit ingest-jira --jql "project = NAV" --since 2025-01-01
# → 412 issues fetched, 412 documents written, 38 person notes,
#   6 project notes to ~/.parrot/wikis/issues/

wikitoolkit build ~/.parrot/wikis/issues --vault
wikitoolkit ns add issues --store ~/.parrot/wikis/issues/.parrot/wiki \
  --global --description "Jira tickets (NAV): requirements, AC, history"
```

Thereafter a daily cron runs the incremental pair:

```bash
wikitoolkit ingest-jira && wikitoolkit build ~/.parrot/wikis/issues --vault -q
# → 14 issues changed since 2026-08-23T04:00Z, 14 documents updated
```

And Claude Code simply asks:

```bash
wikitoolkit query "tenant in URL forms bug" --ns issues
wikitoolkit page "issues::file:NAV-9372.md"
wikitoolkit related "issues::file:NAV-9372.md"
```

Each ticket document looks like:

```markdown
---
type: Issue
key: NAV-9372
title: Forms — tenant must be part of the URL
status: Done
resolution: Fixed
category: Bug
project: NAV
priority: High
assignee: Jesus Lara
assignee_id: 5b10a2...
reporter: Ana Ruiz
reporter_id: 5b10ac...
created_at: '2026-06-02T10:14:00+00:00'
updated_at: '2026-08-19T16:03:00+00:00'
resolved_at: '2026-08-19T16:03:00+00:00'
labels: [forms, multitenant]
components: [navigator-forms]
epic: NAV-9000
blocks: [NAV-9370]
url: https://trocglobal.atlassian.net/browse/NAV-9372
sync:
  fetched_at: '2026-08-24T04:00:11+00:00'
  extractor_version: 1
---

# NAV-9372 — Forms: tenant must be part of the URL

#bug #project/NAV #component/navigator-forms

## Motivation
<rendered description>

## Acceptance Criteria
<rendered AC field>

## Relations
- blocks [[NAV-9370]]
- part of epic [[NAV-9000]]
- assigned to [[people/jesus-lara]]

## History
| When | Field | From | To |
|---|---|---|---|
| 2026-08-19 | status | In Review | Done |

## Attachments & Links
- `error-trace.log` (12 KB)
- PR: https://github.com/phenobarbital/...

<!-- jira-sync:end — everything below is yours; the extractor never touches it -->
```

### Internal Behavior

Four responsibilities, cleanly separated:

1. **`parrot/interfaces/jira/`** (core, new). A `JiraInterface` owning
   connection + auth resolution (every mode `JiraToolkit` supports today,
   including OAuth 3LO via the already-core `JiraOAuthManager`) and the read
   surface: paginated JQL search, issue fetch with a declared field set,
   full changelog, project/field metadata. Returns validated pydantic
   models, not raw dicts. `jira` is imported lazily; a missing package
   raises an actionable install error. `JiraToolkit` is refactored to
   delegate here, keeping its envelope/permission/structured-output layers
   intact — the toolkit becomes the *agent-facing* skin over a shared core,
   exactly as `ObsidianToolkit` is over `parrot/interfaces/obsidian`.
2. **Renderer** (pure). `JiraIssue` → `(filename, markdown)`. Deterministic
   frontmatter projection with fixed key order and sorted collections;
   category from issuetype, tags from labels + components + project,
   motivation from the description, AC from the AC field, relations as
   wikilinks, history from the changelog, attachments as references only.
   No comments (explicit scope decision). No network, no LLM, no I/O.
3. **Sweep** (`wikitoolkit ingest-jira`). Resolves scope (`--jql`, or
   configured default) and the watermark, pages through matching issues,
   renders each, and writes it — preserving anything below the sync marker.
   Emits satellite notes for people, projects, components and labels.
   Advances the watermark only after a fully successful run. Reports
   counts: fetched / written / unchanged / skipped.
4. **Build + register** (existing code, unchanged). `build --vault`
   compiles the folder into the plane; `ns add --store` registers it once.

### Edge Cases & Error Handling

- **`jira` not installed** → single actionable error naming the extra, no
  traceback.
- **Auth not configured** → refuse before fetching anything; never a
  half-written corpus. (`JiraToolkit` already models this: no auth means an
  unauthenticated state that errors explicitly, `jiratoolkit.py:766-776`.)
- **Silent Jira Cloud auth failure** (HTTP 200 + empty results +
  `X-Seraph-Loginreason: AUTHENTICATED_FAILED`) → the exact trap
  `jira_get_projects` already documents (`jiratoolkit.py:2254-2266`); an
  empty result set must be probed, not treated as "nothing changed", or the
  watermark advances over a corpus that was never fetched.
- **Ticket key renamed / moved project** → the old file becomes an orphan;
  it must be detected and removed, or the plane keeps a ghost page forever.
- **Ticket deleted or access revoked** → the document is kept but marked
  stale (`sync.unreachable_since`), never silently deleted.
- **Partial run** (network drop at issue 300 of 412) → written documents
  stay, the watermark does NOT advance, next run re-covers the window.
  Idempotent by construction: the same issue renders the same bytes.
- **Human-edited region** → preserved byte-for-byte. If the marker is
  missing (hand-created file), append the marker rather than overwriting.
- **Description in ADF** (Jira Cloud rich text) → must be converted to
  markdown deterministically; unconvertible nodes degrade to plain text
  rather than raising.
- **Concurrent runs** → the plane already refuses two writers
  (`wiki_write_lock`, `cli.py:1105-1113`); the emitter needs the same guard
  on the issues directory.
- **Unresolved wikilink** (a ticket references one outside the JQL scope)
  → `scan_vault` drops the edge and counts it in
  `VaultScanStats.unresolved_links`; the frontmatter still records the key,
  so nothing is lost, and the sweep should report the count so operators
  can widen the JQL.

---

## Capabilities

### New Capabilities
- `jira-issue-interface`: shared, core, lazily-imported Jira read interface
  (`parrot/interfaces/jira/`) with full auth parity; single implementation
  consumed by both `JiraToolkit` and the wiki sweep.
- `jira-wiki-sync`: `wikitoolkit ingest-jira` — deterministic, zero-LLM
  Jira → markdown emitter with JQL scope, `updated >=` watermark,
  in-place document update, satellite entity notes, and sync-marker
  preservation.

### Modified Capabilities
- `wikitoolkit-ingest-documents` (FEAT-451) — **no behavior change**; its
  `render_frontmatter` determinism contract is mirrored, not modified.
- `wiki-namespaces` (FEAT-450) — documentation/runbook only: the `issues`
  namespace registration step.
- `JiraToolkit` (ai-parrot-tools) — refactored to delegate its read methods
  to the new interface. Public tool signatures and envelope shape must not
  change (FEAT-138/TASK-948 flipped those deliberately).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/interfaces/jira/` | **new** | Shared read interface + models. Core, lazy `jira` import. |
| `parrot/knowledge/wiki/cli.py` | extends | One new `ingest-jira` command. `build` / `ns` / `link` untouched. |
| `parrot/knowledge/wiki/` (new module) | **new** | Renderer + sweep + watermark. Name must NOT be `sources` — `sources.py` already exists (see anti-hallucination). |
| `parrot_tools/jiratoolkit.py` | modifies | Delegates reads to the interface. Zero public-surface change; existing envelope/permission/OAuth tests are the regression gate. |
| `parrot/knowledge/wiki/vault_scan.py` | depends on | Consumed as-is. Any change here is out of scope. |
| `parrot/knowledge/okf/ontology.py` | possibly extends | No `ConceptType.ISSUE` member exists — see Open Questions. |
| `packages/ai-parrot/pyproject.toml` | possibly modifies | May need a `jira` extra on the host for the wiki path (today it rides `agents`/`mcp`). |
| Operator runbook / docs | extends | The register-once + cron-pair procedure. Same shape as TASK-2382's notes-namespace runbook. |
| `wikitoolkit build` (repo plane) | **none** | Hard non-goal, consistent with FEAT-402/451. |

---

## Code Context

### User-Provided Code

None — the user provided requirements and four architectural decisions in
discovery, not code.

### Verified Codebase References

#### Classes & Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:118
def scan_vault(
    root: Path,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> tuple[RepoScan, VaultScanStats]: ...
# Edge relations produced (open-string `rel`), per module docstring lines 16-21:
#   resolved [[wikilink]] -> "references"
#   resolved ![[embed]]   -> "embeds"
#   note -> tag page      -> "tagged"
#   folder containment    -> "contains"  (via build_dir_pages)
# Unresolved wikilinks are DROPPED (vault_scan.py:183) and counted in
# VaultScanStats.unresolved_links.

# packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:62
def is_obsidian_vault(root: Path) -> bool: ...          # requires .obsidian/
# vault_scan.py:58
VAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {".obsidian", ".trash", ".git", ".hg", ".svn", ".parrot"}
)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:215
class WikiPageRecord(BaseModel):
    concept_id: str        # line 234, min_length=1
    node_id: Optional[str] # 235
    title: str = ""        # 236
    category: str = "concept"   # 237 — OPEN STRING, not ConceptType
    summary: str = ""      # 238
    body: str = ""         # 239
    source_id: Optional[str] = None   # 240
    token_count: int = 0   # 241
    origin: str = "ingest" # 242 — "ingest" | "authored" | "memory"
    asserted_by: Optional[str] = None # 243

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:96-103 — edges schema
# CREATE TABLE edges (src TEXT NOT NULL, dst TEXT NOT NULL,
#                     rel TEXT NOT NULL DEFAULT 'references',
#                     provenance TEXT NOT NULL DEFAULT 'extracted',
#                     PRIMARY KEY (src, dst, rel));
# No FK on src/dst — a dangling dst is physically storable.
    async def add_edges(self, edges: list[tuple]) -> int: ...          # :906
    async def replace_source_slice(self, source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None) -> dict: ... # :928

# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:209
def render_frontmatter(
    metadata: DocumentMetadata,
    provenance: TriageProvenance | None = None,
) -> str: ...
# Determinism contract to MIRROR (docstring :213-219): fixed key order,
# sorted collections, None omitted, returns "" when fully empty.
# documents.py:39-50 — _FRONTMATTER_FIELD_ORDER = (title, author, created_at,
#   modified_at, page_count, word_count, language, content_type,
#   source_url, loader)
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]: ...    # :253

# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:72
class DocumentMetadata(BaseModel):   # document-shaped; ticket fields would
    title/author/created_at/modified_at/page_count/word_count/language/
    content_type/source_url/loader: ... ; extra: dict[str, Any]

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:181
class WikiNamespaceConfig(BaseModel):     # extra="forbid" (line 210)
    path: str | None          # 212 — another wiki project root  (kind: path)
    store: str | None         # 215 — pre-built store dir        (kind: store)
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"  # 218
    database: str | None      # 221 — ArangoDB db               (kind: database)
    credentials_env: str; vault: str | None; description: str; weight: float
    def storage_path(self, root: Path) -> Path: ...   # :381 (on WikiProjectConfig)
    def db_path(self, root: Path) -> Path: ...        # :386 -> <storage>/wiki.db
def resolve_vault_dir(...) -> Path | None: ...        # project.py:436

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
async def open_namespace_store(...) -> ...: ...   # :340
async def resolve_namespaces(...) -> ...: ...     # :433
class FederatedWikiStore(BaseWikiStore): ...      # :579
# :372 — `if kind in ("path", "vault"):`  vault resolves like a project root,
#        defaulting to <vault>/.parrot/wiki (docstring :206-210)

# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py:29
class ConceptType(str, Enum):   # Section, Policy, Control, Safeguard, Evidence,
#   Playbook, Procedure, Standard, Framework, Regulation, Guideline, Symbol,
#   Rationale, Skill, Concept, Document, Wiki Summary, Wiki Entity,
#   Wiki Comparison, Wiki Synthesis, Wiki Overview, Run, Claim, Other
class RelationType(str, Enum):  # :77 — references, maps_to, satisfies,
#   satisfied_by, supersedes, superseded_by, implements, part_of, defines,
#   mentions, explains, contains, extends, summarizes, contradicts,
#   produced, about, supported_by
class RelatesTo(BaseModel): concept: str; rel: RelationType = REFERENCES  # :117

# packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py
class ConceptFrontmatter(BaseModel): ...                      # :35
def project_frontmatter(node: dict, tree_name: str) -> str: ...  # :101
def parse_frontmatter(text: str) -> ConceptFrontmatter: ...       # :154

# packages/ai-parrot/src/parrot/interfaces/obsidian/models.py:38
class ObsidianNote(BaseModel):
    path: Path; title: str; content: str          # content = frontmatter stripped
    frontmatter: dict; links: list[ObsidianLink]
    tags: set[str]; aliases: list[str]; dataview_queries: list[str]

# packages/ai-parrot/src/parrot/auth/jira_oauth.py — ALREADY IN CORE
class JiraTokenSet(BaseModel): ...   # :59
class JiraOAuthManager: ...          # :86

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit): ...                                  # :660
    def __init__(self, server_url=None, auth_type=None, username=None,
        password=None, token=None, oauth_consumer_key=None,
        oauth_key_cert=None, oauth_access_token=None,
        oauth_access_token_secret=None, default_project=None,
        credential_resolver=None, workflow_paths=None,
        verify_credentials=True, **kwargs): ...                          # :731
    def _init_jira_client(self) -> JIRA: ...                             # :955
    def _init_jira_client_from_token(self, token_set: Any) -> JIRA: ...  # :1017
    def _issue_to_dict(self, issue_obj: Any) -> Dict[str, Any]: ...      # :1134
    def _ensure_bounded_jql(self, jql: Optional[str]) -> str: ...        # :1198
    def _extract_field_history(self, changelog_entries, field_name): ... # :1291
    async def _get_full_changelog(self, issue: str, page_size: int = 100) # :1314
    async def jira_get_issue(...) -> ...                                 # :1358
    async def jira_get_projects(self) -> Dict[str, Any]: ...             # :2254
    async def jira_search_issues(self, jql: str, start_at: int = 0,
        max_results: Optional[int] = 100, fields: Optional[str] = None,
        expand: Optional[str] = None, json_result: bool = True,
        store_as_dataframe: bool = False, dataframe_name: Optional[str] = None,
        summary_only: bool = False,
        structured: Optional[StructuredOutputOptions] = None,
    ) -> JiraToolEnvelope: ...                                           # :2638
    async def jira_count_issues(self, jql: str,
        group_by: Optional[List[str]] = None) -> Dict[str, Any]: ...     # :2896

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:68
class SourceCollectionManager:
    def add_source(self, path: Path) -> SourceManifestEntry: ...  # :177 — PATH-shaped
    def mark_ingested(...) -> ...                                 # :293
    def record_document_metadata(...) -> ...                       # :423
    def find_by_uri(self, source_uri: str) -> str | None: ...      # :497
```

#### Verified Imports

```python
# Confirmed to resolve today:
from parrot.knowledge.wiki.vault_scan import is_obsidian_vault, scan_vault   # cli.py:1118-1121
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens      # vault_scan.py:45
from parrot.knowledge.wiki.repo_scan import (
    DEFAULT_BODY_MAX_CHARS, DEFAULT_MAX_FILE_BYTES, FileSlice, RepoScan,
    build_dir_pages, file_concept_id,
)                                                                            # vault_scan.py:37-44
from parrot.interfaces.obsidian.index import VaultIndex                      # vault_scan.py:33
from parrot.interfaces.obsidian.models import ObsidianNote                   # vault_scan.py:34
from parrot.interfaces.obsidian.parser import ObsidianNoteParser             # vault_scan.py:35
from parrot.knowledge.okf import (
    ConceptType, RelationType, RelatesTo, ConceptFrontmatter,
    project_frontmatter, parse_frontmatter, build_uri, parse_uri,
)                                                                            # okf/__init__.py:15-30
from parrot.knowledge.wiki.documents import render_frontmatter, split_frontmatter
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                  # cli.py:2685
```

#### Key Attributes & Constants

- **CLI surface** (`parrot/knowledge/wiki/cli.py`): `build` `:1044` with
  `--vault/--no-vault` → `vault_mode` `:1071-1081`, default `None` =
  auto-detect; vault routing `:1118-1133`; write lock `:1105-1113`.
  `ns` group `:1774`, `ns list` `:1779`, `ns add` `:1826`, `ns remove`
  `:1979`. `link` `:2643`.
- **`ns add` options** (`cli.py:1828-1878`): `--project`, `--store`,
  `--backend {sqlite,memory}`, `--database`, `--credentials-env`,
  `--vault` (*"requires .obsidian/"*, `cli.py:1864`), `--description`, `--weight`,
  `--global` (writes `PARROT_HOME/wikis.json`).
- **Namespace registration is single-writer**: *"This is the only writer of
  namespace entries — neither `build` nor any other command ever
  self-registers a wiki"* (`cli.py:1896`).
- **Jira env/config keys** read via navconfig-then-env `_cfg`
  (`jiratoolkit.py:751-760`): `JIRA_AUTH_TYPE` `:771`, `JIRA_INSTANCE`
  `:780`, `JIRA_USERNAME` `:782`, `JIRA_PASSWORD` / `JIRA_API_TOKEN` `:783`,
  `JIRA_SECRET_TOKEN` `:784`, `JIRA_OAUTH_CONSUMER_KEY` /
  `JIRA_OAUTH_KEY_CERT` / `JIRA_OAUTH_ACCESS_TOKEN` /
  `JIRA_OAUTH_ACCESS_TOKEN_SECRET` `:786-789`, `JIRA_DEFAULT_PROJECT`
  (default `"NAV"`) `:791`, `JIRA_DEFAULT_ISSUE_TYPE` `:792`,
  `JIRA_REQUEST_TIMEOUT` (default 30s) `:800`.
- **No auth-type heuristic**: an unresolved `auth_type` leaves the toolkit
  *unauthenticated* and every call raises `AuthorizationRequired`
  (`jiratoolkit.py:767-775`). The new interface must keep this discipline.
- **`jira` dependency placement**: `packages/ai-parrot-tools/pyproject.toml:51`
  → `jira = ["jira>=3.10"]`; `packages/ai-parrot/pyproject.toml:305, 356, 389`
  → `jira==3.10.5` inside the `agents` / `mcp` / (third) host extras. **Not**
  a core runtime dependency.
- **Lazy optional-satellite import pattern to copy**:
  `parrot/knowledge/graphindex/builder.py:667-704` (`_loader_for`) — try the
  import, log an actionable warning naming the missing distribution, and
  degrade instead of failing the run.
- **Jira keys already in the repo plane**: `**Jira**: NAV-6239`
  (`sdd/specs/botmanager-hot-registration-nav6239.spec.md:13`), `NAV-9267`
  (`eventbus-replacement-evaluation.spec.md:14`), `NAV-9269`
  (`msword-loader-none-name-fix.spec.md:19`), `NAV-9372`/`NAV-9370`
  (`forms-tenant-in-url.spec.md:10`), `NAV-8350`, `NAV-8351`, `NAV-9384`,
  `NAV-7712`. The convention is a `**Jira**:` line, present in a *subset* of
  specs — not frontmatter, and not universal.
- **`sources` table columns** exist for document metadata via additive
  migration (`sources.py:423` `record_document_metadata`, `:848`
  `_migrate_sources_columns`).

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/knowledge/wiki/sources/jira.py`~~ — **cannot exist as written.**
  `parrot/knowledge/wiki/sources.py` is already a **module** (40.3 KB,
  `SourceCollectionManager`); creating a `sources/` package beside it would
  shadow it and break `from .sources import SourceCollectionManager`. The
  shared interface goes to `parrot/interfaces/jira/` instead (matching
  `parrot/interfaces/obsidian/`, `zammad.py`, `odoointerface.py`), and the
  renderer/sweep get a distinct module name.
- ~~Cross-namespace edges~~ — **explicitly unsupported.** `wikitoolkit link`
  states it verbatim: *"Both pages must live in the same plane — there are
  no cross-namespace edges"* (`cli.py:2665-2666`). An `issues::…` → `repo::…`
  edge cannot be created. `edges.dst` is unconstrained TEXT so such a string
  is *physically* storable, but it would be a dangling local id, not a
  traversable federated edge. Ticket↔spec linkage must therefore be
  **text/frontmatter-level** (a qualified page id in the frontmatter, plus
  the `**Jira**:` line the repo plane already indexes), resolved by a
  query/`page` call — not by `related`.
- ~~`ConceptType.ISSUE`~~ / ~~`ConceptType.PERSON`~~ / ~~`ConceptType.PROJECT`~~
  — no such members (`okf/ontology.py:29-74`). Note `WikiPageRecord.category`
  is an **open string** (`store.py:237`) and `scan_vault` hardcodes
  `category="document"` for every note (`vault_scan.py:166`), so the plane
  does not enforce the enum on this path.
- ~~`RelationType.BLOCKS`~~ / ~~`RelationType.DUPLICATES`~~ /
  ~~`RelationType.RELATES_TO`~~ — not in the vocabulary
  (`okf/ontology.py:77-114`). `part_of` and `references` are the closest
  existing members.
- ~~`DocumentAcquirer` handling a non-file source~~ — `resolve_sources`
  (`documents.py:154`) produces `DocumentRef`s from paths and URLs only;
  `_acquire_via_loader` (`:632`) calls a file loader. There is no record/API
  source shape.
- ~~`SourceCollectionManager.add_source(uri: str)`~~ — the parameter is
  `path: Path` (`sources.py:177`). It is filesystem-shaped; a
  `jira://NAV-1234` "source" does not drop in unchanged (`find_by_uri`
  `:497` takes a URI, but `add_source` does not).
- ~~`wikitoolkit ingest-jira`~~, ~~`parrot/interfaces/jira/`~~,
  ~~`JiraInterface`~~, ~~`IssueFrontmatter`~~, ~~`JiraIssue` model~~ — none
  exist; all are new in this feature.
- ~~An existing Jira→markdown renderer anywhere in the repo~~ — none. The
  only Jira-to-text code is `JiraToolkit`'s structured-output projection
  (`_apply_structured_output`, `jiratoolkit.py:1254`), which emits dicts for
  an LLM, not documents.
- ~~`ns add --vault` working on a plain directory~~ — the option's help says
  *"requires .obsidian/"* (`cli.py:1864`) and `is_obsidian_vault`
  (`vault_scan.py:62`) tests for that directory. Only `build` has a
  `--vault` **flag** that forces vault mode without the marker directory.

---

## Parallelism Assessment

- **Internal parallelism**: Genuinely good, along a clean seam. The
  **interface + JiraToolkit refactor** (touches `parrot/interfaces/jira/`
  and `packages/ai-parrot-tools/`) and the **renderer** (a pure function
  over a fixed `JiraIssue` model, plus its tests) share no files once the
  model is agreed. The **sweep + CLI + runbook** must land after both. So:
  one task defines the `JiraIssue` model, then two tasks run in parallel,
  then integration. Worth noting the renderer is the highest-value task to
  isolate — it is pure, fully unit-testable, and needs no Jira credentials.
- **Cross-feature independence**: Moderate risk, one real collision zone.
  `parrot/knowledge/wiki/cli.py` is a 123 KB file touched by nearly every
  wiki feature; adding a command there will conflict textually with any
  in-flight wiki work (FEAT-450/451 descendants, FEAT-452 audio-notes,
  FEAT-402 supervised ingestion). `parrot_tools/jiratoolkit.py` is likewise
  contested — FEAT-138/TASK-948 (envelope), TASK-953 (error hardening) and
  the OAuth 3LO spec all touch it. `vault_scan.py`, `store.py`,
  `documents.py` and `okf/` are consumed read-only, so no conflict there.
- **Recommended isolation**: `per-spec`.
- **Rationale**: The parallel seam is real but narrow (two tasks), while the
  two files most likely to conflict — `cli.py` and `jiratoolkit.py` — are
  both hot repo-wide. Sequential tasks in one worktree keep the
  `jiratoolkit.py` refactor and the `cli.py` command addition from racing
  each other *and* make the single rebase against `dev` cheap. The
  parallelism gain (one pure-function task) does not pay for a second
  worktree on the same two hot files.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus*: `type: feature`,
  `base_branch: dev`.
- [x] Where does the Jira code live, and how do we avoid the Agent
  depending on `JiraToolkit`? — *Owner: Jesus*: a shared read interface in
  **core**, lazily importing `jira`, consumed by both `JiraToolkit` and the
  new sweep. **Path corrected during code research**: not
  `wiki/sources/jira.py` (would shadow the existing `wiki/sources.py`
  module) but `parrot/interfaces/jira/`, matching the
  `parrot/interfaces/obsidian/` precedent — *"one vault-access + parsing
  core reused by the toolkit, the loaders, and wiki vault_scan"* — and the
  fact that `parrot/auth/jira_oauth.py` is already core.
- [x] Deterministic or LLM? — *Owner: Jesus*: zero-LLM default; opt-in
  `--enrich` flag for an LLM summary on thin tickets. The default path must
  stay byte-deterministic and cron-safe.
- [x] How is the `issues` namespace materialized? — *Owner: Jesus*: its own
  plane, built from a folder of one-markdown-per-ticket, registered as a
  namespace — the TASK-2382 notes-wiki shape.
- [x] Where do the markdown files live? — *Owner: Jesus*: outside the git
  repo, configurable, defaulting under `PARROT_HOME` (e.g.
  `~/.parrot/wikis/issues/`), so ticket prose never enters git history.
- [x] Scope and re-run semantics? — *Owner: Jesus*: JQL scope plus an
  `updated >=` watermark; incremental upsert per run.
- [x] Which relations in v1? — *Owner: Jesus*: Jira issue links
  (blocks/relates/duplicates/clones), epic/parent↔subtask hierarchy, person
  pages (assignee/reporter), and project/component/label entity pages.
- [x] How deep does each document go? — *Owner: Jesus*: core fields +
  description + acceptance criteria, status/transition history, and
  attachments/remote links as references only. **Comments are explicitly
  excluded from v1** (largest token contributor, most churn on re-sync).
- [x] Auth modes? — *Owner: Jesus*: full parity with `JiraToolkit`,
  including OAuth 2.0 3LO — so an agent-driven ingest can run under a
  per-user token, not just the service account. (Note: a cron sweep still
  needs a non-interactive mode; 3LO needs a resolvable stored token set.)
- [x] Person representation? — *Owner: Jesus*: display name + accountId
  only. **No email addresses** in the plane or any export.
- [ ] **Ticket↔spec linkage mechanism, given cross-namespace edges do not
  exist.** The chosen answer was "deterministic key scan both directions",
  but `wikitoolkit link` states plainly that *"both pages must live in the
  same plane — there are no cross-namespace edges"* (`cli.py:2665`). The
  buildable v1 is therefore **text-level, not edge-level**: the ticket
  document carries the qualified repo page id in its frontmatter, and the
  repo plane already indexes the `**Jira**: NAV-xxxx` line in the spec body,
  so both directions are *findable by query* and openable by `page` — just
  not traversable by `related`. Decide: accept the text-level join for v1,
  or open a follow-up spec adding cross-namespace edge support to FEAT-450?
  — *Owner: Jesus*
- [ ] **Do we extend `ConceptType` with `Issue` / `Person` / `Project`?**
  Purely additive (existing string values untouched, and `Other` exists as
  the open-vocabulary fallback), and it would make the frontmatter genuinely
  OKF-valid rather than OKF-shaped. Against: `scan_vault` writes
  `category="document"` for every note regardless, so the enum buys
  correctness, not behavior, in v1. — *Owner: Jesus*
- [ ] **Where does the watermark live?** `SourceCollectionManager.add_source`
  is `Path`-shaped (`sources.py:177`), so the sync ledger does not drop into
  the existing `sources` table unchanged. Proposal: a small JSON state file
  in the issues directory (`.parrot/jira_sync.json`) holding the last
  successful `updated` timestamp per JQL scope, plus the extractor version
  so a renderer change can force a full re-render. — *Owner: Jesus*
- [ ] **Adopt the `<!-- jira-sync:end -->` human region in v1?** Recommended
  yes (see Option D): ~10 lines in the writer now, versus a data-loss
  migration later once people have annotated files. — *Owner: Jesus*
- [ ] **ADF → markdown conversion for Jira Cloud descriptions.** Cloud
  returns Atlassian Document Format (JSON), not wiki markup. Is there an
  existing converter to reuse, or do we write a bounded deterministic one
  (headings, lists, code blocks, links, tables → markdown; unknown nodes →
  plain text)? This is the single largest unknown in the renderer's
  effort estimate. — *Owner: Jesus*
- [ ] **Does the ingest need its own host extra?** `jira` currently rides
  the host `agents`/`mcp` extras and `ai-parrot-tools[jira]`. A user who
  installs only the wiki surface has no clean extra to ask for. Add
  `jira = ["jira>=3.10"]` to `packages/ai-parrot/pyproject.toml`? — *Owner: Jesus*
- [ ] **Scheduling mechanism** — out of scope for the code, but the runbook
  must pick one: system cron, a GitHub Action, or `/loop`. The emit+build
  pair must run as one unit; running `ingest-jira` without `build` leaves
  the plane stale with no warning. Should `ingest-jira` just invoke the
  build itself by default (with `--no-build` to opt out)? — *Owner: Jesus*
