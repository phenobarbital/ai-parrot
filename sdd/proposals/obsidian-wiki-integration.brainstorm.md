---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Obsidian → Wiki — Byte-Faithful Raw Copy of the Vault

**Date**: 2026-08-28
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The Obsidian → LLM Wiki ingest (`wikitoolkit build` in vault mode and the
`vault_ingest` MCP tool, both routed through `scan_vault()` in
`packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py`) is a
**retrieval-oriented distillation**, not an archive. What lands in the
plane is lossy on several independent axes:

| Loss | Where it happens |
|---|---|
| YAML frontmatter is stripped | `ObsidianNoteParser.parse()` → `ObsidianNote.content` is "frontmatter stripped" (`interfaces/obsidian/models.py:43`) |
| A synthetic header (`# title` / `Tags:` / `Aliases:`) is prepended | `_note_body()` (`vault_scan.py:103-115`) |
| Body is cut at `body_max_chars` (default **16 000**) | `_note_body()` return `body[:body_max_chars]`; `WikiProjectConfig.body_max_chars` (`project.py:322`) |
| Notes larger than `max_file_kb` (default **512 KiB**) are skipped entirely | `scan_vault()` (`vault_scan.py:151-153`) |
| Line endings / BOM normalised, non-UTF-8 notes skipped | `path.read_text(encoding="utf-8")` (`vault_scan.py:155`) |
| Only `*.md` is scanned — `.canvas`, `.base`, images, PDFs are invisible | `root.rglob("*.md")` (`vault_scan.py:146`) — and `![[embed]]` edges to attachments end up as *unresolved links* |

The `summary` column is **not** an LLM summary either: `_note_summary()`
(`vault_scan.py:90-100`) takes `frontmatter.summary` / `description` or the
first non-empty line (≤ 300 chars). That heuristic summary and the capped
body are exactly right for RAG/FTS and must stay; but nothing in the plane
lets a user (or an agent) get the **original file back, byte for byte**.

The `sources` manifest (`sources.py` / `models.SourceManifestEntry`) already
tracks every ingested file by absolute URI, SHA-1 (`file_hash`) and mtime,
so the plane *knows* what the file looked like — it just does not keep it.

**Who is affected**: vault owners using the wiki as a durable knowledge
store (the vault may live on a laptop that dies; the server-hosted Arango
plane should be a faithful mirror), agents that need the exact original
(frontmatter fields, dataview blocks, canvas JSON) rather than the RAG
rendering, and anyone wanting a verifiable backup/restore path.

**Goal**: store the *entire* content of every note **byte-for-byte**, as
optimally as possible (dedupe, compression), **in addition to** — never
instead of — the existing summary + capped body used for retrieval.

## Constraints & Requirements

Decisions taken during discovery (Rounds 0–2):

- **Flow**: `type: feature`, `base_branch: dev`.
- **Fidelity**: raw bytes of the file as on disk — frontmatter, BOM, CRLF,
  original encoding — with **zero parsing** in the archival path.
- **Set to preserve**: every `.md` and `.canvas` in the vault (outside
  `VAULT_EXCLUDE_DIRS`) **with no size limit**; other attachments
  (images, PDFs, `.base`, audio…) only up to a configurable threshold —
  larger ones are registered (URI + hash + size) but their bytes are not
  stored.
- **Storage model**: the raw copy belongs to the **source entry**
  (extend `sources` / `SourceManifestEntry`), **latest version only** —
  no historical versioning (explicitly dropped in Round 2).
- **Backends**: must work on all three planes — SQLite (`wiki.db`),
  ArangoDB (server), memory/OKF (directory + `.manifest.json`).
- **RAG path unchanged**: `pages.body` keeps the synthetic header and the
  `body_max_chars` cap; `summary` heuristic unchanged; FTS5 / embeddings
  untouched.
- **Consumption**: (1) `wikitoolkit page --raw` and `wiki_page(raw=True)`
  return the original; (2) `wikitoolkit vault restore <dest>` rebuilds the
  vault on disk and verifies every file by hash.
- **Incremental**: unchanged files (same hash + mtime) must not be re-read
  or re-written — same staleness rule as today (`entry_is_stale`).
- **No new hard dependencies**; compression via stdlib.
- Async-first: no blocking I/O on the event loop (`asyncio.to_thread` as
  `_ingest_files` already does for manifest work).
- Backwards compatible: pre-existing `wiki.db` files open cleanly (additive,
  nullable columns via the existing `_migrate_sources_columns` mechanism).

---

## Options Explored

### Option A: `raw_content` column, literal, in every backend

Add `raw_content` (bytes), `raw_size`, `raw_encoding` to
`SourceManifestEntry` and persist them exactly as one more column /
attribute in each backend: `BLOB` in the sqlite `sources` table, a base64
string in the Arango `wiki_sources` document, a base64 string in
`.manifest.json`. `scan_vault()` also walks `.canvas` and attachments.
Read path: `page --raw` looks up `pages.source_id → sources.raw_content`.

✅ **Pros:**
- Smallest conceptual change — one model, one upsert statement, one row
  per file; the 14-column `_SOURCES_UPSERT_SQL` grows to 17.
- Restore is trivial: iterate `list_sources()`, write bytes, compare hash.

❌ **Cons:**
- `.manifest.json` (memory/OKF backend) is loaded fully into RAM on open
  (`_load_manifest`) and rewritten atomically on every save
  (`_save_manifest`, `sources.py:1195`) — inlining megabytes of base64
  makes every ingest O(vault size) and the file un-diffable.
- Arango `wiki_sources` documents become huge; every `find_entries_by_uris`
  round trip (used for staleness of *every* file on each build) would
  drag the raw payload across the wire unless every query is rewritten
  to project columns.
- The same problem in sqlite: `SELECT *` in `_row_to_entry` would pull
  blobs on staleness checks unless queries are narrowed.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlite3` (stdlib) | BLOB column | already in use |
| `base64` (stdlib) | JSON/Arango encoding | +33 % size |

🔗 **Existing Code to Reuse:**
- `sources.py` `_SOURCES_UPSERT_SQL`, `_entry_params`, `_row_to_entry`,
  `_entry_to_doc`, `_doc_to_entry`, `_migrate_sources_columns`.
- `vault_scan.py` `scan_vault()` file walk.

---

### Option B: Raw copy owned by the source entry, backend-specific physical layout, compressed *(recommended)*

Same **logical** model as A — the raw copy is a property of the source
entry, latest-only, addressed by `source_id` — but the **bytes are stored
out-of-row** so the hot manifest path never touches them:

- **sqlite**: new table `source_raw(source_id PK → sources, content BLOB,
  size INTEGER, stored_size INTEGER, codec TEXT, sha1 TEXT)` in
  `WIKI_SCHEMA_SQL` (+ `_SCHEMA_TABLES`), FK-less like the rest of the
  schema; deleted alongside `remove_source`.
- **arangodb**: new collection `wiki_raw` keyed by `source_id`
  (base64 payload) registered next to `SOURCES_COLLECTION`.
- **memory/OKF (json manifest)**: sidecar directory
  `{sources_dir}/raw/<source_id>.<codec>`; the manifest entry carries only
  `raw_ref`, `raw_size`, `raw_codec` — the OKF bundle stays browsable.

`SourceManifestEntry` gains metadata only (`raw_size`, `raw_codec`,
`raw_stored: bool`, `raw_ref`), never the bytes. `SourceCollectionManager`
gets `put_raw(source_id, data)`, `get_raw(source_id) -> bytes | None`,
`iter_raw()`, implemented per backend like the existing `_upsert` /
`_async_upsert` split.

Content is compressed with stdlib **`zlib`** (level 6; `codec="zlib"`) —
markdown compresses 3–5×; already-compressed attachments (png/jpg/pdf) are
stored with `codec="raw"` when compression gains < 10 %. Integrity is
verified on read against the entry's existing SHA-1 `file_hash` (the
staleness hash and the archive hash are one and the same, computed from
the same bytes in one pass).

`scan_vault()` is extended with a second walk that yields
`RawAsset(rel_path, size, kind ∈ {note, canvas, attachment})` for every
file outside `VAULT_EXCLUDE_DIRS`; notes and canvases are always captured,
attachments only when `size <= raw_attachment_max_kb`. Non-note assets
also get a lightweight page (`category="canvas"` / `"attachment"`, body =
a few metadata lines) so `![[embed]]` edges now **resolve** instead of
being counted as unresolved, and `page --raw` has a `concept_id` to hang
off.

✅ **Pros:**
- Manifest reads (`find_entries_by_uris` on every build) stay as cheap as
  today on all three backends — no query rewrites for column projection.
- Compression makes the archive markedly smaller than the vault itself
  for text; dedupe by content is unnecessary given latest-only.
- Attachment/canvas pages fix a real existing gap (embed edges).
- Restore = `iter_raw()` + write + hash check; no parsing anywhere in the
  archive path, so fidelity is exact by construction.
- Memory/OKF backend's bundle remains a human-readable directory.

❌ **Cons:**
- One more table/collection/directory per backend and three storage
  implementations to test (sqlite, arango, json).
- Raw bytes read twice today (`scan_vault` reads text, `_compute_hash`
  reads bytes) — should be unified into one read to avoid tripling I/O.
- Latest-only: a re-ingest after an edit silently overwrites the previous
  raw copy (accepted in Round 2).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `zlib` (stdlib) | compression codec | no new dependency; `zstandard` (≥0.22) could be an optional faster codec later, codec column makes it swappable |
| `hashlib` (stdlib) | SHA-1 integrity, single pass | already used by `_compute_hash` |
| `sqlite3` (stdlib) | `source_raw` table, BLOB | WAL mode already enabled |
| `python-arango` via `asyncdb` | `wiki_raw` collection | already the Arango driver in `arango_store.py` |

🔗 **Existing Code to Reuse:**
- `sources.py` `SourceCollectionManager` (backend dispatch pattern,
  `_connect`, `_run_async`, `_arango_execute`), `remove_source`.
- `store.py` `WIKI_SCHEMA_SQL`, `_SCHEMA_TABLES`, `_MIGRATION_COLUMNS`.
- `arango_store.py` collection registration (`SOURCES_COLLECTION`,
  line 292 collection list).
- `vault_scan.py` `scan_vault()`, `VAULT_EXCLUDE_DIRS`, `file_concept_id`.
- `cli.py` `_ingest_files` / `_prune_removed` / `build` vault branch
  (lines 1199-1215), `page` command (line 1591), `export` (line 2270).
- `tools.py` `WikiPageTool` / `WikiPageInput`, `VaultIngestTool`.
- `interfaces/obsidian/parser.py` `parse_canvas()` (canvas JSON already
  parseable for the lightweight page body).

---

### Option C: Mirror the vault into a bare git repository under `.parrot/` *(unconventional)*

Keep the plane exactly as it is and instead maintain a bare git repo
(`{storage_dir}/vault.git`) that `vault_ingest` commits into after each
run (via `git` subprocess or `dulwich`). Git gives content-addressed
dedupe, zlib packing, full history and `git checkout` as the restore path
for free; the wiki only stores the commit SHA per ingest.

✅ **Pros:**
- Versioning, dedupe, compression and restore are solved, battle-tested
  primitives; almost no storage code to write.
- Diffs between ingests come for free (`git diff`).

❌ **Cons:**
- Does not live in the plane: the server-hosted Arango backend gains
  nothing (the mirror is local to whoever ran the ingest), violating the
  "all three backends" constraint.
- Adds a runtime dependency on the `git` binary (or `dulwich`), and a
  second store to keep consistent with `sources`.
- User explicitly dropped versioning; the main benefit is unused.

📊 **Effort:** Low (local) / High (to make it work through Arango)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `dulwich` ≥ 0.22 | pure-Python git | new dependency, or shell out to `git` |

🔗 **Existing Code to Reuse:**
- `bookkeeper.py` `WikiBookkeeper.log_operation` to record the commit SHA.
- `project.py` `wiki_write_lock` to serialise mirror writes.

---

### Option D: Reuse `pages.body` — store the raw note as a second page (`category="raw"`)

Emit, per note, a second `WikiPageRecord` with `concept_id="raw:<rel>"`,
body = the original text uncapped, excluded from FTS/embeddings by
category. No schema change at all.

✅ **Pros:**
- Zero schema work; `get_page("raw:…")` already returns it; `sync`,
  namespaces and export see it for free.

❌ **Cons:**
- `pages.body` is `TEXT` — cannot hold bytes (BOM/encoding/CRLF are lost
  through `str`), and `.canvas`/attachments do not fit at all → fails the
  "byte-for-byte" requirement.
- `pages_fts` is an external-content-free FTS5 table populated on every
  upsert; keeping raw pages out of it needs trigger-level changes.
- Doubles page count and pollutes `wikitoolkit query` ranking/telemetry.

📊 **Effort:** Low

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `WikiPageRecord`, `upsert_pages`.

---

## Recommendation

**Option B** is recommended because:

- It is the only option that satisfies every constraint at once:
  byte-exact (no `str` round-trip, unlike D), works on sqlite + Arango +
  memory/OKF (unlike C), and keeps the manifest hot path cheap on every
  backend (unlike A, whose inline blobs would be dragged through
  `find_entries_by_uris` on every build and rewritten wholesale by
  `_save_manifest`).
- It stays faithful to the user's "extend `sources`" decision at the model
  level — the raw copy is a property of the source entry, keyed by
  `source_id`, latest-only — while letting each backend choose the
  physical layout it is good at (BLOB table, collection, sidecar file).
- Stdlib `zlib` delivers the "optimal" storage the user asked for without
  a new dependency, and the `codec` column keeps the door open for
  `zstandard` later.
- Adding canvas/attachment pages is a small, adjacent win that turns
  today's *unresolved* `![[embed]]` links into real edges.

What we trade off: three backend implementations to write and test, and
latest-only semantics (a re-ingest overwrites). Both were explicitly
accepted in discovery.

---

## Feature Description

### User-Facing Behavior

- `wikitoolkit build` (vault mode) and the `vault_ingest` MCP tool now
  also archive every scanned file. The summary line gains
  `raw: N stored (X MiB → Y MiB), M attachments skipped (>limit)`;
  `VaultIngestTool` returns `raw_stored`, `raw_bytes`, `raw_stored_bytes`,
  `raw_skipped`.
- New config keys in `.parrot/wiki.json` (`WikiProjectConfig`):
  `raw_copy: bool = True` (vault mode only), `raw_attachment_max_kb: int =
  10240`, `raw_codec: "zlib" | "raw" = "zlib"`. Env overrides follow the
  existing `WikiEnvOverrides` pattern.
- `wikitoolkit page <id> --raw` prints the original bytes (stdout, binary
  safe; `--raw -o FILE` writes to a file). For notes that is the exact
  `.md` including frontmatter. `wiki_page(page_id, raw=True)` returns
  `{"raw": "<utf-8 text>"}` for text sources or `{"raw_base64": …,
  "content_type": …}` for binary, plus `size`, `sha1`, `source_uri`.
- `wikitoolkit vault restore <dest> [--ns] [--verify-only]` rebuilds the
  vault tree from the plane, writes each file at its original relative
  path, and reports `restored / verified / mismatched / missing (raw not
  stored)`. Exit code non-zero on any mismatch.
- `wikitoolkit status` reports raw archive size and count.
- `.canvas` files and attachments now appear as pages
  (`category="canvas"` / `"attachment"`) and are targets of `embeds`
  edges, so `wikitoolkit related` on a note lists its images/PDFs.

### Internal Behavior

1. **Scan** — `scan_vault()` performs one walk over the vault (not
   `rglob("*.md")` only). For each file outside `VAULT_EXCLUDE_DIRS` it
   reads bytes **once**, computes SHA-1, and:
   - `.md` → decodes for the note page as today (decode failure → page
     skipped, raw still archived) and yields `RawAsset(kind="note")`.
   - `.canvas` → page from `parse_canvas()` card titles, `RawAsset(kind="canvas")`.
   - anything else → `attachment` page (title, size, mime), `RawAsset`
     with `store_bytes = size <= raw_attachment_max_kb`.
   `max_file_kb` continues to bound only the **page body** path; the raw
   path for notes/canvases is unbounded.
2. **Register** — `SourceCollectionManager.add_sources()` accepts the
   precomputed hash (no second read). Staleness is unchanged.
3. **Archive** — for every *pending* (new/stale) asset, `put_raw()` stores
   `(source_id, compressed bytes, size, stored_size, codec, sha1)`; backend
   dispatch mirrors `_upsert` / `_async_upsert`. Writes happen inside the
   existing `wiki_write_lock`, off-loop via `asyncio.to_thread`, in
   batches like `_upsert_many`.
4. **Prune** — `_prune_removed()` → `remove_source()` also deletes the raw
   row/doc/sidecar.
5. **Read** — `get_raw(source_id)` decompresses, verifies SHA-1, returns
   bytes. `page --raw` resolves `pages.source_id` → `get_raw`.
6. **Restore** — iterate `iter_raw()` joined with `sources.source_uri`,
   derive the relative path from the recorded vault root (stored in `meta`
   at ingest as `vault_root`), write atomically (tmp + rename), compare
   hash.

### Edge Cases & Error Handling

- **Non-UTF-8 note**: raw archived; page skipped and counted (today it is
  simply skipped). Restore returns the exact bytes.
- **Note > `max_file_kb`**: raw archived; page gets summary + body capped
  at `body_max_chars` (no longer skipped) — *see Open Question 1*.
- **Attachment > `raw_attachment_max_kb`**: source entry + attachment page
  created, `raw_stored=False`; `page --raw` errors with
  "raw copy not stored (size > limit)"; restore lists it under `missing`.
- **Compression not worth it** (gain < 10 %): stored with `codec="raw"`.
- **Hash mismatch on read** (corruption): `get_raw` raises
  `RawIntegrityError`; CLI exits non-zero; restore counts `mismatched`.
- **Legacy `wiki.db` / Arango DB**: `source_raw` table / `wiki_raw`
  collection created on first open by the existing schema-probe path;
  entries ingested before this feature have `raw_stored=False` until the
  next `build --force`.
- **Concurrent writer**: unchanged — `wiki_write_lock` guards ingest.
- **Symlinks / files vanishing mid-scan**: `OSError` → logged, counted in
  `scan.skipped`, never aborts the build.
- **Namespaces (FEAT-450)**: `page --raw --ns X` reads from that
  namespace's store; restore takes `--ns`.
- **`sync_push/pull`**: raw copies are **not** replicated (sync covers
  memory pages only) — documented, *Open Question 3*.

---

## Capabilities

### New Capabilities
- `vault-raw-archive`: byte-faithful, compressed, latest-only raw copy of
  every vault file owned by its `sources` entry, on all three backends.
- `vault-restore`: `wikitoolkit vault restore` with per-file hash
  verification.
- `vault-assets-as-pages`: canvas and attachment pages so `embeds` edges
  resolve.

### Modified Capabilities
- `llmwiki-obsidian-plugin` (FEAT-392) — `scan_vault()` walk and stats.
- `wikitoolkit-mcp-tools` (FEAT-403) — `wiki_page` gains `raw`,
  `vault_ingest` gains raw telemetry.
- `wiki-source-manifest` (FEAT-260 / FEAT-451 columns) — additive metadata
  fields on `SourceManifestEntry`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/wiki/models.py` `SourceManifestEntry` | extends | `raw_stored`, `raw_size`, `raw_stored_size`, `raw_codec`, `raw_ref` (nullable) |
| `knowledge/wiki/sources.py` `SourceCollectionManager` | extends | `put_raw` / `get_raw` / `iter_raw` / `delete_raw` on sqlite, arangodb, json; `add_sources` accepts precomputed hash |
| `knowledge/wiki/store.py` `WIKI_SCHEMA_SQL`, `_SCHEMA_TABLES` | modifies | new `source_raw` table |
| `knowledge/wiki/arango_store.py` | modifies | new `wiki_raw` collection in the created-collections list (line 292) |
| `knowledge/wiki/vault_scan.py` | modifies | single-walk scan, `RawAsset`, canvas/attachment pages, stats |
| `knowledge/wiki/cli.py` | extends | `page --raw`, `vault restore`, `build` vault branch + summary, `_ingest_files` archive step, `_prune_removed` |
| `knowledge/wiki/tools.py` | extends | `WikiPageInput.raw`, `VaultIngestTool` result |
| `knowledge/wiki/project.py` `WikiProjectConfig` / env overrides | extends | `raw_copy`, `raw_attachment_max_kb`, `raw_codec` |
| `knowledge/wiki/bookkeeper.py` | depends on | `VAULT_INGEST` log line carries raw counts |
| `tests/knowledge/wiki/test_vault_scan.py`, `test_vault_ingest_tool.py`, `test_mcp_server_vault.py`, `test_cli.py`, `test_extra_backends.py` | extends | plus new `test_source_raw.py` |
| `docs/` wiki runbooks | extends | restore procedure |

No breaking changes; all schema work is additive and idempotent.

---

## Code Context

### User-Provided Code

_None — the user described the problem in prose only._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py
VAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {".obsidian", ".trash", ".git", ".hg", ".svn", ".parrot"})           # line 53
def is_obsidian_vault(root: Path) -> bool: ...                            # line 58
def tag_concept_id(tag: str) -> str: ...                                  # line 69
@dataclass
class VaultScanStats:                                                     # line 75
    notes: int = 0; tags: int = 0; wikilink_edges: int = 0
    embed_edges: int = 0; unresolved_links: list[tuple[str, str]]
def _note_summary(note: ObsidianNote) -> str: ...                         # line 90
def _note_body(note: ObsidianNote, body_max_chars: int) -> str: ...       # line 103  (returns body[:body_max_chars])
def scan_vault(root: Path, body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
               max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
               ) -> tuple[RepoScan, VaultScanStats]: ...                  # line 118
#   walk: for path in sorted(root.rglob("*.md")) — line 146
#   size skip: path.stat().st_size > max_file_bytes → scan.skipped — line 151
#   raw = path.read_text(encoding="utf-8") — line 155

# From packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
DEFAULT_BODY_MAX_CHARS, DEFAULT_MAX_FILE_BYTES, FileSlice, RepoScan,
build_dir_pages, file_concept_id                                          # imported by vault_scan.py:37-44

# From packages/ai-parrot/src/parrot/interfaces/obsidian/models.py
class ObsidianNote(BaseModel):                                            # line 38
    path: Path; title: str
    content: str   # "Raw markdown body (frontmatter stripped)"           # line 43
    frontmatter: dict; links: list[ObsidianLink]; tags: set[str]
    aliases: list[str]; dataview_queries: list[str]
class ObsidianCanvasCard(BaseModel): ...                                  # line 51
class ObsidianCanvas(BaseModel): ...                                      # line 61

# From packages/ai-parrot/src/parrot/interfaces/obsidian/parser.py
class ObsidianNoteParser:                                                 # line 81
    def parse(self, raw: str, rel_path: str | Path) -> ObsidianNote: ...  # line 91
def parse_canvas(raw_json: str, rel_path: str | Path) -> ObsidianCanvas   # line 212

# From packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel):                                     # line 155
    source_id: str; source_uri: str
    file_hash: str        # SHA-1 hex digest at ingest time              # line 197
    mtime: float; ingested_at: str; pages_generated: list[str]
    status: str = "ingested"
    destination / decision_source / charter_version / composite_score     # FEAT-402, nullable
    doc_metadata / content_type / loader                                  # FEAT-451, nullable

# From packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
_SOURCES_UPSERT_SQL  # 14-column INSERT ... ON CONFLICT(source_id) DO UPDATE   # line 50
_SOURCES_DECISION_COLUMNS: dict[str, str]                                 # line 78
_SOURCES_DOCUMENT_COLUMNS: dict[str, str]                                 # line 89  (ALTER-migrated, nullable)
class SourceCollectionManager:                                            # line 96
    # backend: "sqlite" | "json" | "arangodb"
    def __init__(...)                                                     # line 121
    def add_source(self, path: Path) -> SourceManifestEntry               # line 205
    def find_entries_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]  # line 260
    def find_entries_by_ids(self, source_ids: list[str]) -> dict[...]     # line 301
    def add_sources(self, paths, known) -> list[SourceManifestEntry]      # line 339
    def mark_ingested_many(...)                                           # line 400
    def list_sources(self) -> list[SourceManifestEntry]                   # line 442
    def get_source(self, source_id: str) -> SourceManifestEntry | None    # line 457
    def is_stale(self, source_id: str) -> bool                            # line 475
    def entry_is_stale(self, entry: SourceManifestEntry) -> bool          # line 496
    def remove_source(self, source_id: str) -> bool                       # line 708
    def find_by_uri(self, source_uri: str) -> str | None                  # line 737
    def _connect(self) -> sqlite3.Connection                              # line 752
    def _upsert(self, entry) / _upsert_many(self, entries)                # lines 764 / 776
    def _entry_params(entry) -> tuple ; _row_to_entry(row)                # lines 800 / 841
    def _compute_hash(self, path: Path) -> str   # SHA-1, 8 KiB chunks    # line 870
    def _generate_source_id(self, source_uri: str) -> str  # "src-<uuid5 hex[:12]>"  # line 887
    def _run_async(self, coro) ; _arango_query / _arango_execute          # lines 922 / 1001 / 1017
    def _doc_to_entry(doc) / _entry_to_doc(entry)                         # lines 1026 / 1042
    async def _async_upsert / _async_upsert_many / _async_remove_source   # lines 1062 / 1073 / 1100
    def _migrate_sources_columns(self) -> None                            # line 1116
    def _load_manifest(self) / _save_manifest(self)  # json backend, whole-file rewrite  # lines 1170 / 1195

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
WIKI_SCHEMA_SQL  # tables: meta, sources, pages, edges, pages_fts (fts5), embeddings   # lines 53-116
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]]                       # line 120
_SCHEMA_TABLES = frozenset({"meta","sources","pages","edges","pages_fts","embeddings"})  # line 130
class WikiPageRecord(BaseModel):                                          # line 213
    concept_id, node_id, title, category, summary, body: str, source_id,
    token_count, origin, asserted_by, updated_at
class BaseWikiStore(ABC):                                                 # line 321
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int      # line 340
    async def replace_source_slice(...)                                   # line 346
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]  # line 361
class SQLiteWikiStore(BaseWikiStore): ...                                 # line 477

# From packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py
class InMemoryWikiStore(BaseWikiStore): ...                               # line 71  (OKF bundle: {storage_dir}/pages/…)

# From packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
SOURCES_COLLECTION = "wiki_sources"                                       # line 49
# collections created in a (name, is_edge) list — line 292

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):                                       # line 287
    body_max_chars: int = Field(default=16_000, ge=1_000)                 # line 322
    max_file_kb: int = Field(default=512, ge=1)                           # line 323
    vault_dir: str | None                                                 # line 338
    def storage_path(self, root: Path) -> Path                            # line 366
def resolve_vault_dir(root, config, override=None) -> Path | None         # line 485
# env-override model with vault_dir / body_max_chars / max_file_kb        # lines 627-647

# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _open_sources(root, config, store=...) -> SourceCollectionManager     # line 423
async def _ingest_files(store, sources, root, scan, force=False) -> dict[str, int]  # line 622
async def _prune_removed(store, sources, root, scan, scope=...) -> int    # line 702
# `build` command: vault_mode = is_obsidian_vault(root); scan_vault(...)  # lines 1144, 1199-1215
@wiki.command() def page(page_id, path_, max_tokens, store_opt, backend_opt, ns_opt, as_json)  # line 1591
def export(path_, output)                                                 # line 2270

# From packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class WikiPageInput(BaseModel): page_id: str; namespace: str | None       # line 102
class WikiPageTool(AbstractTool): name = "wiki_page"                      # line 190
    async def _execute(self, page_id: str, namespace: str | None = None) -> ToolResult  # line 208
class VaultIngestInput(BaseModel)                                         # line 137
class VaultIngestTool(AbstractTool): name = "vault_ingest"                # line 425
    async def _execute(self, vault_path: str | None = None, force: bool = False, **kw) -> ToolResult  # line 448
    # uses: resolve_vault_dir, wiki_write_lock, scan_vault, _open_sources, _ingest_files, _prune_removed, WikiBookkeeper().log_operation(storage, "VAULT_INGEST", ...)

# From packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
# VaultIngestTool(store, root=root, config=config) appended to vault_tools  # lines 170-175
```

#### Verified Imports
```python
from parrot.knowledge.wiki.vault_scan import scan_vault, is_obsidian_vault, VaultScanStats, VAULT_EXCLUDE_DIRS
from parrot.knowledge.wiki.repo_scan import DEFAULT_BODY_MAX_CHARS, DEFAULT_MAX_FILE_BYTES, FileSlice, RepoScan, build_dir_pages, file_concept_id
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens, BaseWikiStore, SQLiteWikiStore
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.project import WikiProjectConfig, resolve_vault_dir, wiki_write_lock
from parrot.knowledge.wiki.tools import WikiPageTool, VaultIngestTool
from parrot.interfaces.obsidian.parser import ObsidianNoteParser, parse_canvas
from parrot.interfaces.obsidian.models import ObsidianNote, ObsidianCanvas
from parrot.interfaces.obsidian.index import VaultIndex
```

#### Key Attributes & Constants
- `WikiProjectConfig.body_max_chars` → `int` default 16 000 (`project.py:322`)
- `WikiProjectConfig.max_file_kb` → `int` default 512 (`project.py:323`)
- `SourceManifestEntry.file_hash` → SHA-1 hex (`models.py:197`); `_compute_hash` is the only producer (`sources.py:870`)
- `SourceCollectionManager.backend` ∈ `{"sqlite","json","arangodb"}` (`sources.py:101-103`)
- `SOURCES_COLLECTION = "wiki_sources"` (`arango_store.py:49`), duplicated literal in `sources.py:44`
- `_SCHEMA_TABLES` drives the per-connection schema probe (`store.py:130`) — a new table must be added there or it will never be created on existing DBs
- `VaultIngestTool` audit op name: `"VAULT_INGEST"` (`tools.py`)

### Does NOT Exist (Anti-Hallucination)
- ~~`pages.raw_content` / `WikiPageRecord.raw`~~ — pages hold only the RAG body (`TEXT`).
- ~~`sources.raw_content` / `SourceManifestEntry.raw_*`~~ — no raw-content fields exist today.
- ~~`source_raw` table, `wiki_raw` collection, `{sources_dir}/raw/`~~ — to be created by this feature.
- ~~`SourceCollectionManager.put_raw / get_raw / iter_raw`~~ — do not exist.
- ~~`wikitoolkit page --raw`, `wikitoolkit vault restore`, `WikiPageInput.raw`~~ — do not exist.
- ~~`WikiProjectConfig.raw_copy / raw_attachment_max_kb / raw_codec`~~ — do not exist.
- ~~LLM-generated note summaries in `scan_vault`~~ — the summary is heuristic (`_note_summary`); zero LLM calls in vault mode.
- ~~`scan_vault` handling of `.canvas` or attachments~~ — only `*.md` today; `parse_canvas()` exists in the parser but is unused by the wiki scanner (used by `loaders/obsidian/loader.py`).
- ~~A `parrot/vectorstores/` package or a root-level `parrot/` dir~~ — source root is `packages/ai-parrot/src/parrot/`.
- ~~`sync_push/sync_pull` replicating sources~~ — sync covers `origin="memory"` pages only (`sync.py:3`).

---

## Parallelism Assessment

- **Internal parallelism**: limited. A natural cut is (1) storage layer —
  `models.py` + `sources.py` raw API on the three backends + schema in
  `store.py`/`arango_store.py`; (2) scanner — `vault_scan.py` single walk,
  `RawAsset`, canvas/attachment pages; (3) wiring — `_ingest_files`,
  `_prune_removed`, `build`/`vault_ingest` telemetry, config keys;
  (4) read/restore surface — `page --raw`, `wiki_page(raw=)`,
  `vault restore`, `status`. (1) and (2) are independent of each other;
  (3) depends on both; (4) depends on (1).
- **Cross-feature independence**: touches `cli.py`, `tools.py`,
  `project.py`, `sources.py` which are hot files for the wiki family
  (FEAT-450 namespaces, FEAT-451 ingest, FEAT-461 sync, FEAT-471
  rustworkx proposal). No in-flight spec currently edits `vault_scan.py`
  or the `sources` schema; `FEAT-470 a2ui-v1-dialect` (in progress) is
  unrelated.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the storage API shape (1) is the contract everything
  else consumes; running (1) and (2) in separate worktrees saves little
  and risks merge friction in `cli.py`. Sequential tasks in one worktree,
  ordered (1) → (2) → (3) → (4), is simplest.

---

## Open Questions

- [ ] Notes larger than `max_file_kb`: with the raw copy always archived,
  should the *page* now be created with a capped body (proposed) instead
  of being skipped as today? — *Owner: Jesus*
- [ ] Attachment size threshold default: 10 MiB proposed
  (`raw_attachment_max_kb = 10240`). OK, or lower for Arango deployments? — *Owner: Jesus*
- [ ] Should `sync_push/sync_pull` (FEAT-461) replicate raw copies between
  planes, or is raw strictly per-plane (proposed: per-plane, out of scope)? — *Owner: Jesus*
- [ ] `page --raw` for binary attachments over MCP: base64 inline (proposed,
  with a size cap) vs. writing to a temp path and returning the path? — *Owner: Jesus*
- [ ] Keep SHA-1 as the single integrity hash (reuses `file_hash`) or add a
  SHA-256 column for the archive (proposed: keep SHA-1, no second hash)? — *Owner: Jesus*
- [ ] Should `raw_copy` also apply to non-vault `wikitoolkit build` (code
  repos) and `wikitoolkit ingest` documents (FEAT-451)? Proposed: vault-only
  in v1, but design the `sources` raw API so it is source-kind agnostic. — *Owner: Jesus*
