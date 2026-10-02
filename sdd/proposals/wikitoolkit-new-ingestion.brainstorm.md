---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [wiki, wikitoolkit, ingestion, inbox, charter, knowledge-graph, archive]
---

# Brainstorm: `wikitoolkit inbox` — autonomous inbox ingestion into the LLM Wiki

**Date**: 2026-10-03
**Author**: Jesus Lara (brainstorm: Claude session 2026-10-03)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The LLM Wiki already has a supervised document-ingestion lane:
`wikitoolkit ingest <SOURCE>` (FEAT-402 charter-driven triage + JSONL manifest
review, FEAT-451 loader-backed PDF/DOCX/PPTX extraction + YAML frontmatter).
It is built for *curating a corpus with a human in the loop*: every run needs a
mode (`--dry-run` / `--review` / `--interactive` / `--auto`), the operator
points it at an arbitrary folder, and the originals stay where they were.

What is missing is the **drop-box workflow** for "corporate digital life"
documents — meeting notes, briefings, memos, decisions, reports — that arrive
one by one:

1. **No fixed intake location.** Nothing watches a conventional folder such
   as `inbox/` in the repository; each ingest is an ad-hoc invocation with a
   path argument.
2. **No classification beyond admit/archive/discard.** Triage decides
   *whether* a document enters the wiki, not *what it is*. `TriageOutput`
   even carries a `category_hint` field that nothing consumes
   (`review.py:88-108`; no reader anywhere in `parrot/knowledge/wiki/`).
   Pages land with PageIndex's generic categories and no tags.
3. **No relations to the existing graph.** An ingested document becomes an
   island: `summarizes` edges to its own source only. A meeting that
   discusses a module, a decision or a previous meeting is never linked to
   those pages, so `wikitoolkit related` cannot travel from one to the other.
4. **No on-disk markdown.** With the default `sqlite` backend the page body
   lives only inside `.parrot/wiki/wiki.db`; OKF markdown exists only as a
   whole-plane export (`export.py`) or in the `memory` backend's bundle
   (`file_store.py`). There is no per-document markdown projection a human
   can open next to the plane.
5. **No lifecycle for the original.** Processed files stay in place, so the
   operator cannot tell "already ingested" from "still pending" by looking at
   the folder, and re-running re-triages everything.

Affected users: the repository maintainers who drop meeting notes and
briefings into the repo and the coding agents (Claude Code, Codex, Gemini via
the `wikitoolkit` MCP server) that later query the wiki for that context.

---

## Constraints & Requirements

Decisions taken during discovery (Rounds 0–2) — binding for the spec:

- **Flow**: `type: feature`, `base_branch: dev`.
- **Shape**: a **new command** (`wikitoolkit inbox`) that **reuses** the
  FEAT-402/451 pipeline (`DocumentAcquirer`, `IngestTriageRouter`,
  `WikiIngestOrchestrator`, `SourceCollectionManager`, `WikiBookkeeper`).
  Not a new `ingest` mode, not an independent subsystem. `build`, `upsert`
  and `ingest` keep byte-identical behavior.
- **Trigger**: manual, hook-safe command run by a human or an agent, also
  exposed as an MCP tool. No daemon, no watcher, no default git hook. It
  needs an LLM, so it must never be wired into the offline post-commit hook
  path by default.
- **Inbox**: a **git-tracked** folder, default `inbox/` at the repo root,
  path configurable in `.parrot/wiki.json`.
- **Archive**: originals move to the **git-ignored** `.parrot/archive/`
  (`.gitignore:385` ignores `.parrot/*`), renamed
  `<stem>.<YYYY-MM-DD>.<ext>`. Archiving a tracked original stages its
  removal (`git rm`-equivalent); the command never commits.
- **Markdown output**: an **OKF markdown file inside the storage dir**
  (`.parrot/wiki/…`), following the `file_store.py` bundle layout and the
  `export.py` frontmatter contract. The SQLite page remains the retrieval
  truth; the file is a write-only projection (same boundary `export.py:1-16`
  states: OKF markdown is never read back on the retrieval path).
- **Taxonomy**: a **charter-defined closed set of document kinds** (meeting,
  briefing, decision, report, memo, …), each mapped to a wiki page category,
  plus **free-form tags normalized to kebab-case**. The LLM chooses *from the
  list*; it never invents a kind.
- **Linking**: **retrieve candidates → LLM selects → verify ids**. Lexical
  search over the plane proposes top-k candidate pages (documents, memories,
  code modules); the LLM picks related ones with a reason; only ids that
  resolve in the store become `references`-family edges and `[[wikilinks]]`.
  Never link to an id the store cannot return.
- **Triage**: charter thresholds apply in `--auto` semantics (a jokes-only
  meeting is discarded). Rejected originals are **also archived**, under a
  `rejected/` marker, with a bookkeeper line — the inbox must be empty after a
  clean run.
- **Idempotent and crash-safe**: a document that fails anywhere stays in the
  inbox; nothing is archived until its page(s) and markdown are persisted.
  Re-running after a failure resumes without duplicating pages
  (`replace_source_slice`).
- **Offline/no-LLM contract untouched**: `repo_scan.py` and the git hook
  remain deterministic and LLM-free.
- **Conventions**: aiohttp only (no new HTTP clients), Pydantic v2 models,
  `self.logger`, `black`/`ruff` clean, tests under
  `packages/ai-parrot/tests/knowledge/wiki/`.

---

## Options Explored

### Option A: `wikitoolkit inbox` — a composed pipeline module with new classify / link / project / archive stages

A new module `parrot/knowledge/wiki/inbox.py` hosts an `InboxProcessor` that
runs, per document in the configured inbox folder:

1. **Acquire** — `resolve_sources(inbox_dir)` + `DocumentAcquirer.acquire()`
   (FEAT-451: PDF/DOCX/… via `parrot_loaders`, frontmatter split for `.md`).
2. **Triage** — `IngestTriageRouter.triage(path, text)` with the charter;
   `--auto` semantics (`decision = proposed_action`, `decision_source="auto"`).
3. **Classify** (new) — one `PageIndexLLMAdapter.ask_structured()` call on
   the lightweight tier returns an `InboxClassification` (kind ∈ charter
   taxonomy, title, one-paragraph summary, tags, named entities, event date).
   Code maps `kind → WikiPageCategory`, normalizes tags, rejects unknown
   kinds (falls back to the charter's `default_kind`).
4. **Propose links** (new) — build a query from title + tags + claims, run
   `WikiCombinedSearch.search(top_k=…)` plus per-tag `store.search_fts()`,
   dedupe into ≤ N candidates `(id, title, category, summary)`; a second
   structured call returns `LinkSelection` restricted to candidate ids with a
   relation from a closed vocabulary (`references`, `relates_to`,
   `mentions`, `follows_up`, `supersedes`) and a one-line reason. Every id is
   re-verified with `store.get_page(id, include_body=False)`; misses are
   dropped and logged.
5. **Ingest** — `WikiIngestOrchestrator.ingest(path, wiki_config,
   triage=entry, charter_version=…, acquired=acquired)`; this is the
   existing FEAT-402/451 path (PageIndex pages, `summarizes` edges, source
   manifest `record_decision`, frontmatter, bookkeeper `ADMIT`/`DISCARD`).
   `discard` short-circuits with no pages.
6. **Decorate** (new) — recover the generated page ids from
   `SourceCollectionManager.get_source(source_id).pages_generated`, pick the
   root page as the *document page*, re-upsert it with the taxonomy
   category, the classification summary and a `## Related` section of
   `[[wikilinks]]`; write `(doc_page, dst, rel, "asserted")` edges and
   `tag:<slug>` pages + `tagged` edges (tags become graph nodes — no schema
   change); `asserted_by = "agent:wikitoolkit-inbox"`.
7. **Project markdown** (new) — render the document page as an OKF file
   under `<storage_dir>/inbox/<category-plural>/<flat-id>.md` using
   `page_frontmatter()` + the machine-field block, exactly as
   `SQLiteFileStore._render_page_file` does, written atomically
   (temp + `os.replace`).
8. **Archive** (new) — move the original to
   `<archive_dir>[/rejected]/<stem>.<YYYY-MM-DD>.<ext>` (suffix `-N` on
   collision); if the file is tracked, stage the deletion through
   `git rm --cached`-equivalent (pattern: `cli.py:3192` already shells
   out to `git -C <root>`); persist `archived_to` into the source's
   `DocumentMetadata.extra` via `record_document_metadata`; bookkeeper
   `ARCHIVE_ORIGINAL` line.

Charter gains an optional `taxonomy:` block (kinds with `id`, `description`,
`category`, optional `tag_hints`; `default_kind`; `max_tags`). A missing block
yields the built-in default taxonomy, so existing charters keep validating.
`WikiProjectConfig` gains an optional `inbox: InboxConfig` (`dir`,
`archive_dir`, `rejected_subdir`, `markdown_dir`, `date_format`, `stage_git`).

CLI: `wikitoolkit inbox [--dry-run] [--limit N] [--charter PATH]
[--lightweight-model] [--model] [--no-archive] [--force] [--json]`.
MCP: a `wiki_inbox` tool wrapping the same processor (dry-run default).

✅ **Pros:**
- Reuses every hardened piece (loaders, triage cascade, manifest provenance,
  staleness/dedupe, frontmatter, bookkeeper) — the new code is four
  well-bounded stages plus a CLI command.
- Deterministic where it matters: code computes category from kind, verifies
  every link id, normalizes tags; the LLM only fills constrained Pydantic
  models.
- Tags as `tag:` pages give relations for free (`wikitoolkit related
  tag:meeting`), no SQLite/Arango migration.
- Markdown projection honours the existing OKF/export boundary and the
  `exclude_dirs: [".parrot/wiki"]` default, so `build` never rescans it.
- Crash-safe ordering (persist → project → archive) and idempotent re-runs.

❌ **Cons:**
- Two extra LLM calls per admitted document (classify, link) on top of
  triage; cost scales with inbox size (mitigation: both on the lightweight
  tier; open question on merging classify into the triage prompt).
- `IngestReport` does not return page ids, so the decorate stage must read
  them back from the source manifest — a small indirection.
- Re-upserting the root page after the orchestrator wrote it is a second
  write; must preserve `content_hash`/`node_id` to keep `upsert`/`sync`
  semantics intact.
- `cli.py` is already 208 KB; the command must stay thin (delegate to
  `inbox.py`) and import the pipeline lazily like `ingest` does.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `click` (already a dep) | `wikitoolkit inbox` command | same option conventions as `ingest` (`cli.py:4794`) |
| `pydantic>=2` (already) | `InboxClassification`, `LinkSelection`, `InboxConfig`, charter `taxonomy` | structured output via `ask_structured` |
| `pyyaml` (already) | OKF frontmatter rendering | via `export.page_frontmatter` |
| `ai-parrot-loaders` (optional extra, already wired) | PDF/DOCX/PPTX/XLSX extraction | lazily imported by `DocumentAcquirer._acquire_via_loader` |
| `git` CLI (system) | stage deletion of tracked originals | `subprocess`, pattern at `cli.py:3192` |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/documents.py` — `resolve_sources`, `DocumentAcquirer`, `AcquiredDocument`, `render_frontmatter`, `split_frontmatter`.
- `parrot/knowledge/wiki/triage.py` — `IngestTriageRouter`, `NoveltyScorer`.
- `parrot/knowledge/wiki/charter.py` — `Charter`, `load_charter` (extend with `taxonomy`).
- `parrot/knowledge/wiki/ingest.py` — `WikiIngestOrchestrator.ingest(..., triage=, acquired=)`.
- `parrot/knowledge/wiki/sources.py` — `record_decision`, `record_document_metadata`, `get_source`, `is_stale`.
- `parrot/knowledge/wiki/search.py` — `WikiCombinedSearch.search`; `store.search_fts`.
- `parrot/knowledge/wiki/export.py` — `page_frontmatter`, `category_dir`; `file_store.py` — `_render_page_file` / `_write_page_file_atomic` as the rendering template; `okf/utils.flatten_concept_id_for_filename`.
- `parrot/knowledge/wiki/cli.py` — `_resolve_project`, `_open_store`, `_open_sources`, `_run`, `_build_triage_adapters`, `_resolve_model_id`, `_authoring_identity`; the `remember` command (`cli.py:3806`) as the precedent for asserted edges and deterministic page ids.
- `parrot/knowledge/wiki/tools.py` — `create_wiki_tools` + `AbstractTool` pattern (`WikiRememberTool`) for the MCP tool.

---

### Option B: Extend `wikitoolkit ingest` with `--inbox` / `--classify` / `--archive-to` flags

Keep one command. `ingest` grows an `--inbox` switch (source defaults to the
configured inbox dir, mode forced to `--auto`), `--classify` (runs the
classification + link stages after `_apply_all`), and `--archive-to DIR`
(moves originals after apply). The taxonomy still lives in the charter.

✅ **Pros:**
- No new command surface; discoverability through one `--help`.
- Shares the adapter/toolkit wiring (`_build_triage_adapters`,
  `PageIndexToolkit`, `_triage_all`/`_apply_all`) in place.

❌ **Cons:**
- `ingest` already has 15 parameters and four mutually exclusive modes
  (`cli.py:4794-4880`); adding three orthogonal switches multiplies the
  invalid combinations (`--inbox --review`, `--archive-to --dry-run`, …).
- The pipeline is implemented as inner closures inside the command body
  (`_triage_all`, `_apply_all` at `cli.py:~4966-5040`), so the new stages
  would either be more closures in a 450-line function or a refactor of the
  FEAT-402 command — risking the byte-identical contract tests rely on.
- Archiving changes the meaning of `ingest`'s SOURCE from "read" to
  "consume"; surprising for existing users and scripts.
- Harder to expose as a focused MCP tool.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `click` | new options on `ingest` | mutual-exclusion validation grows |
| `pydantic>=2` | same models as Option A | — |

🔗 **Existing Code to Reuse:**
- Everything in Option A, but edited in place inside `cli.py:ingest` instead of a new module.

---

### Option C: Agent-driven ingestion (a parrot `Agent` with the `WikiToolkit` tools)

An `Agent` (ReAct loop) receives each inbox document and the wiki tools
(`search`, `read_page`, `find_related`, `create_page`, `remember`,
`update_page` from `parrot/knowledge/wiki/toolkit.py`) and is instructed by a
system prompt to classify, summarise, link and file the document itself. A
thin deterministic wrapper handles acquisition and archiving.

✅ **Pros:**
- Maximum flexibility: the agent can read candidate pages in full before
  deciding links, follow `related` hops, merge into an existing page instead
  of creating a new one.
- Exercises the framework's own primitives (dogfooding `Agent` + toolkit).
- Unconventional path to richer relations (e.g. detect that a meeting
  *supersedes* an earlier one after reading it).

❌ **Cons:**
- Non-deterministic cost and outcome; hard to test (no fixed call count,
  no structured output contract), hard to audit beyond the tool log.
- Bypasses the charter/triage machinery and `record_decision` provenance
  unless re-implemented as tools; `create_page` instead of
  `ingest_source` is exactly the duplicate-page trap FEAT-452 had to guard
  against (`audio-notes-obsidian.spec.md:782`).
- Heavy model per document (reasoning loops) versus two lightweight calls.
- Needs an `Agent` runtime (and its client wiring) inside the `wikitoolkit`
  CLI, which so far only depends on `PageIndexLLMAdapter`.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.bots.Agent` (core) | ReAct loop | requires full client/bot stack in the CLI process |
| `parrot/knowledge/wiki/toolkit.py` (`WikiToolkit`) | agent tools | `ingest_source`, `remember`, `search`, `find_related`, `create_page` |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/toolkit.py` — tool surface.
- `parrot/knowledge/wiki/documents.py` — acquisition.
- Archive stage from Option A.

---

### Option D: Deterministic linker, LLM only for triage + classification

Same as Option A but **no LLM in the link stage**: candidates come from
`WikiCombinedSearch` / FTS, and an edge is created when the lexical score
exceeds a charter threshold or when a candidate's exact title / symbol /
concept id appears verbatim in the document text (same technique
`vault_scan.py` uses to turn `[[wikilinks]]` into `references` edges).

✅ **Pros:**
- One LLM call fewer per document; links can never be hallucinated.
- Fully reproducible; easy to unit-test with a seeded store.
- Works even when the LLM budget is exhausted (links degrade, pages still land).

❌ **Cons:**
- Relations are shallow (`references` only); no reason text, no
  `supersedes`/`follows_up` semantics, poor recall for paraphrased topics.
- Threshold tuning per corpus; FTS scores are not comparable across
  categories (store rows are min-max normalised per group,
  `search.py:241-258`).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | FTS5 already in the SQLite plane |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/search.py` — `WikiCombinedSearch.search`, `_search_store`.
- `parrot/knowledge/wiki/vault_scan.py` — wikilink → `references` edge precedent.

---

## Recommendation

**Option A** is recommended because:

- It honours every discovery decision (new command, reuse of FEAT-402/451,
  charter taxonomy, LLM-selected-but-verified links, triage with archive-all)
  while keeping `ingest`, `build` and the git hook byte-identical. Option B
  would put the same logic inside an already overloaded command body and
  risk the contract its tests pin.
- Its LLM usage is bounded and typed: three structured calls per admitted
  document on the lightweight tier (triage, classify, link), each returning a
  Pydantic model that *code* post-validates. Option C trades that for an
  open-ended agent loop whose cost and output cannot be contracted in a spec.
- It takes Option D's safety property (never emit an edge to an id the store
  cannot return) without giving up relation semantics or reasons: candidate
  retrieval is deterministic, the LLM only *chooses among* retrieved ids, and
  every id is re-verified. Option D remains the documented degradation path
  when the link call fails.
- Tags as `tag:<slug>` pages plus `tagged` edges avoid a `pages` schema
  migration across the SQLite and ArangoDB stores and make tags navigable
  through the existing `related` surface.

What is traded off: two more LLM calls per document than today's `--auto`
ingest, and a second write of the root page in the decorate stage. Both are
acceptable for a human-paced inbox (tens of documents per run, not
thousands) and both have a clear optimisation path (merge classify into the
Stage-1 triage prompt; pass category/summary into `_build_page_records`
instead of re-upserting) recorded under Open Questions.

---

## Feature Description

### User-Facing Behavior

- The operator drops files into `inbox/` (git-tracked; any format
  `DocumentAcquirer` handles: `.md`, `.txt`, `.pdf`, `.docx`, `.pptx`,
  `.xlsx`, `.html`, `.epub`, …) and runs:

  ```bash
  wikitoolkit inbox                 # process everything, archive originals
  wikitoolkit inbox --dry-run       # show kind / tags / links / decision; touch nothing
  wikitoolkit inbox --limit 5       # bounded batch
  wikitoolkit inbox --no-archive    # ingest, leave originals in place
  wikitoolkit inbox --force         # re-ingest even unchanged duplicates
  wikitoolkit inbox --json          # machine-readable report
  ```

- Output per document: source path, triage composite + decision, kind,
  category, tags, selected links with relation and reason, page id, markdown
  path, archive path. A summary line counts admitted / archived-as-category /
  rejected / failed; exit code is non-zero when any document failed.
- After a clean run `inbox/` is empty (except dotfiles), `.parrot/archive/`
  holds `<stem>.<YYYY-MM-DD>.<ext>` originals (`rejected/` for discards), and
  `git status` shows the tracked originals as staged deletions. The command
  never commits.
- `wikitoolkit query`, `page`, `related` immediately see the new document
  page, its `tag:<slug>` neighbours and its outgoing `references`-family
  edges; `.parrot/wiki/inbox/<category-plural>/<id>.md` is a readable OKF
  file with frontmatter (`type`, `title`, `id`, `tags`, `timestamp`,
  `summary`, `relates_to`, plus document and triage provenance).
- Agents get the same capability through the `wiki_inbox` MCP tool
  (dry-run by default; `apply=true` to archive), so a coding assistant can
  file a briefing it just wrote.
- Configuration lives in `.parrot/wiki.json`:

  ```json
  "inbox": {
    "dir": "inbox",
    "archive_dir": ".parrot/archive",
    "rejected_subdir": "rejected",
    "markdown_dir": ".parrot/wiki/inbox",
    "date_format": "%Y-%m-%d",
    "stage_git": true
  }
  ```

  and the charter gains:

  ```yaml
  taxonomy:
    default_kind: note
    max_tags: 8
    kinds:
      - id: meeting     ; category: summary  ; description: "Minutes, call notes, stand-ups"
      - id: briefing    ; category: overview ; description: "Status or context briefing"
      - id: decision    ; category: concept  ; description: "A decision and its rationale"
      - id: report      ; category: synthesis; description: "Analysis or findings"
      - id: memo        ; category: summary  ; description: "Short internal memo"
      - id: note        ; category: concept  ; description: "Anything else worth keeping"
  ```

  (illustrative — the spec fixes the default list and the exact YAML shape.)

### Internal Behavior

1. **Resolve** project root and config (`_resolve_project`), open store and
   sources (`_open_store`, `_open_sources`), load the charter
   (`load_charter`, default `.parrot/charter.yaml`), build the lightweight /
   heavy adapters (`_build_triage_adapters`) and the `PageIndexToolkit` +
   `WikiIngestOrchestrator` exactly as `ingest` does. Fail fast with a
   `ClickException` when the inbox dir is missing or no LLM can be built.
2. **Discover** documents with `resolve_sources(inbox_dir, recursive=True)`;
   dotfiles are skipped; apply `--limit`; stable ordering (mtime then name)
   so partial runs are predictable.
3. **Per document** (sequential; a failure isolates to that document):
   - acquire → `AcquiredDocument`; `DocumentAcquisitionError` ⇒ counted as
     *skipped*, file left in place.
   - triage → `ManifestDocEntry`; set `decision = proposed_action`,
     `decision_source = "auto"` (heuristic rejects keep `"heuristic"`).
   - if `discard`: `orchestrator.ingest(..., triage=entry)` records the
     rejection (`status="rejected"`, bookkeeper `DISCARD`), then archive to
     `rejected/`. No classify / link calls are spent.
   - classify → `InboxClassification`; code validates `kind` against the
     taxonomy, maps to category, normalizes tags (`kebab-case`, deduped,
     capped), derives `title` (classification title → document metadata
     title → file stem).
   - candidates → `WikiCombinedSearch.search(query, top_k=K,
     include_archived=False)` ∪ `store.search_fts(tag)` per tag ∪ exact
     title/`sym:`/`file:` mentions found in the text; dedupe; exclude the
     document's own pages; cap at N (charter/config constant).
   - link selection → `LinkSelection` restricted to candidate ids and the
     closed relation vocabulary; verify each with `store.get_page`; drop
     and log misses (`LINK_DROPPED`).
   - ingest → `orchestrator.ingest(path, wiki_config, triage=entry,
     charter_version=charter.version, acquired=acquired)`; the triage
     `briefing` becomes the PageIndex hint; frontmatter carries document
     metadata + `TriageProvenance`.
   - decorate → read `get_source(report.source_id).pages_generated`; the
     first id is the document page; `upsert_pages` with
     `category=<taxonomy category>` (or `archive` when the decision was
     `archive`), `summary=<classification summary>`, body + `## Related`
     wikilinks, `origin="ingest"`, `asserted_by="agent:wikitoolkit-inbox"`,
     preserving `node_id`, `source_id`, `content_hash`; `add_edges` for the
     selected links and for `tag:<slug>` pages (created on first use with
     `category="tag"`, `origin="authored"`).
   - project → render the document page to
     `<markdown_dir>/<category_dir(category)>/<flatten_concept_id>.md`
     atomically (temp file + `os.replace`); the frontmatter is
     `page_frontmatter(page, relates_to)` plus the machine block, mirroring
     `_render_page_file`.
   - archive → compute destination; `-N` suffix on collision; move
     (`os.replace` same FS, `shutil.move` fallback); when `stage_git` and
     the file is tracked (`git ls-files --error-unmatch`), run
     `git rm --cached --quiet -- <path>` after the move so the deletion is
     staged; persist `archived_to` + `archived_at` into the source's
     `DocumentMetadata.extra` (`record_document_metadata`); bookkeeper
     `ARCHIVE_ORIGINAL`.
4. **Report** aggregated counts and per-document rows (text or `--json`),
   write a run header line to the bookkeeper (`INBOX_RUN`, charter
   fingerprint, counts, models used).
5. **MCP tool** `wiki_inbox` (in `tools.py`, registered by
   `create_wiki_tools` when `root`/`config` are given) wraps steps 1–4 with
   `dry_run=True` default; it reuses the CLI's adapter construction through
   a shared helper moved out of the command body (no new LLM wiring).

### Edge Cases & Error Handling

- **Empty inbox / missing dir** — exit 0 with "nothing to do" / exit 2 with a
  clear message naming the configured path.
- **Undecodable binary / oversized file** — acquisition error or Stage-0
  heuristic reject; counted, reported; heuristic rejects are archived under
  `rejected/`, acquisition failures stay in the inbox (they may need a
  loader extra installed).
- **Duplicate content** (same hash already ingested) — Stage-0 reject with
  `decision_source="heuristic"` → archived under `rejected/duplicate` is
  *not* a separate dir in v1: the reason is recorded in the bookkeeper line
  and report; `--force` bypasses the duplicate check and re-ingests
  (`replace_source_slice` prevents page duplication).
- **Unknown kind from the LLM** — fall back to `default_kind`, flag
  `classification_source="fallback"` in the report; never raise.
- **LLM failure in classify or link** — classification failure aborts that
  document (file stays, counted as failed); link failure degrades to the
  deterministic exact-mention links (Option D behaviour) with a warning, the
  document still lands.
- **Link id not in store** — dropped, logged; never written.
- **Markdown write failure** (permissions, disk) — document counted as
  failed, original *not* archived, pages already persisted remain (idempotent
  re-run re-renders and archives).
- **Archive collision** — `-1`, `-2`, … suffix before the extension; never
  overwrite.
- **Cross-filesystem archive dir** — `shutil.move` fallback; verify the
  destination exists before deleting the source.
- **Git unavailable or file untracked** — skip staging silently (report
  `staged: false`); never fail the run because of git.
- **Interrupted run** — ordering persist → project → archive guarantees the
  inbox never loses a document whose page does not exist; re-running picks
  up where it stopped.
- **Charter without `taxonomy`** — built-in default taxonomy; existing
  `ingest` charters keep validating (additive, optional field).
- **`--dry-run`** — triage + classify + link proposals run (LLM cost is
  spent) but no store write, no file write, no move, no bookkeeper mutation
  except a `DRY_RUN` line.

---

## Capabilities

### New Capabilities
- `wikitoolkit-inbox-ingestion`: autonomous `wikitoolkit inbox` command and
  `wiki_inbox` MCP tool — acquire, triage, classify (charter taxonomy),
  tag, link (retrieve → select → verify), ingest, project OKF markdown,
  archive originals with date-stamped names.

### Modified Capabilities
- `supervised-wiki-ingestion` (FEAT-402): `Charter` gains an optional
  `taxonomy` block; `TriageOutput.category_hint` gets its first consumer.
- `wikitoolkit-ingest-documents` (FEAT-451): `DocumentMetadata.extra`
  carries `archived_to`/`archived_at`; no model change.
- `mcp-local-server-wikitoolkit`: one more tool in `create_wiki_tools`.
- `portable-wikitoolkit-config-paths` / `WikiProjectConfig`: optional
  `inbox` section.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/inbox.py` (new) | adds | `InboxProcessor`, `InboxClassification`, `LinkSelection`, archive + markdown projection helpers |
| `parrot/knowledge/wiki/charter.py` | extends | optional `taxonomy: Taxonomy` with default; fingerprint covers it |
| `parrot/knowledge/wiki/project.py` | extends | optional `inbox: InboxConfig` on `WikiProjectConfig` (+ `WikiEnvOverlay`) |
| `parrot/knowledge/wiki/cli.py` | extends | new `inbox` command; factor adapter/toolkit construction out of `ingest` into a reusable helper **without** changing `ingest` behavior |
| `parrot/knowledge/wiki/tools.py`, `mcp_server.py` | extends | `wiki_inbox` tool (⚠ FEAT-569 in flight on both files) |
| `parrot/knowledge/wiki/ingest.py` | depends on | unchanged; consumed via `ingest(..., triage=, acquired=)` |
| `parrot/knowledge/wiki/sources.py` | depends on | `record_decision`, `record_document_metadata`, `get_source` |
| `parrot/knowledge/wiki/store.py` | depends on | `upsert_pages`, `add_edges`, `get_page`, `search_fts`; no schema change |
| `parrot/knowledge/wiki/export.py`, `file_store.py` | depends on | `page_frontmatter`, `category_dir`; rendering mirrored, not imported from `file_store` (private methods) |
| `.parrot/wiki.json` (repo) | config | add `inbox` block; `exclude_dirs` already covers `.parrot/wiki` |
| `.parrot/charter.yaml` (repo, git-ignored) | config | add `taxonomy` block; ship a documented example under `docs/` |
| `.gitignore` | none | `.parrot/*` already ignores the archive; `inbox/` must **not** be ignored |
| `docs/guides/llm-wiki-guide.md`, `docs/wiki/cheatsheet.md` | docs | new section "Inbox ingestion" |
| `packages/ai-parrot/tests/knowledge/wiki/` | tests | `test_inbox.py` (processor stages with stub adapters), `test_cli_inbox.py` (CliRunner, monkeypatched `_build_triage_adapters` like FEAT-402 tests) |

No new runtime dependency. No breaking change.

---

## Code Context

### User-Provided Code

None — the user provided the behavioural description only (inbox folder,
auto-classify / categorize / tag / link, register in the graph, markdown
file in the wiki plane, archive original with the date in the filename into
`.parrot/archive`).

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/documents.py
class DocumentRef(BaseModel):                       # L69
    uri: str; is_url: bool = False; suffix: str = ""
class DocumentMetadata(BaseModel):                  # L83
    title: str | None; author: str | None; created_at: str | None; modified_at: str | None
    page_count: int | None; word_count: int | None; language: str | None
    content_type: str | None; source_url: str | None; loader: str | None
    extra: dict[str, Any] = Field(default_factory=dict)
class AcquiredDocument(BaseModel):                  # L119
    ref: DocumentRef; text: str; metadata: DocumentMetadata
    ebook_sections: list[dict[str, Any]] = []
class TriageProvenance(BaseModel):                  # L136
    composite_score: float | None; decision: str | None
    decision_source: str | None; charter_version: str | None
class DocumentAcquisitionError(Exception): ...      # L158
def resolve_sources(source: str, *, recursive: bool = True) -> list[DocumentRef]   # L166
def render_frontmatter(metadata: DocumentMetadata, provenance: TriageProvenance | None = None) -> str  # L221
def split_frontmatter(...)                          # L265
class DocumentAcquirer:                             # L466
    def __init__(self, *, fetch_timeout: float = 30.0, max_bytes: int = 100 * 1024 * 1024,
                 cache_dir: Path | None = None) -> None            # L481
    async def acquire(self, ref: DocumentRef) -> AcquiredDocument  # L500

# From packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
class NoveltyScorer:                                # L67
    def __init__(self, grounding_evaluator: GroundingEvaluator | None = None,
                 search: WikiCombinedSearch | None = None,
                 max_claims: int = DEFAULT_MAX_CLAIMS_FOR_NOVELTY) -> None   # L88
class IngestTriageRouter:                           # L252
    def __init__(self, charter: Charter, adapter: PageIndexLLMAdapter,
                 sources: SourceCollectionManager, novelty_scorer: NoveltyScorer, *,
                 heavy_adapter: PageIndexLLMAdapter | None = None,
                 max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
                 allowed_suffixes: frozenset[str] | None = None) -> None     # L271
    async def triage(self, path: Path, content: str) -> ManifestDocEntry   # L304

# From packages/ai-parrot/src/parrot/knowledge/wiki/charter.py
class Thresholds(BaseModel):                        # L75  admit: float; reject: float
    def route(self, composite: float) -> Literal['admit', 'gray', 'reject']  # L107
class TriageExample(BaseModel):                     # L177 summary; why; destination
class Charter(BaseModel):                           # L208
    version: str; scope: CharterScope; weights: dict[str, float]; thresholds: Thresholds
    destinations: list[str]; calibration: CalibrationPolicy
    examples: list[TriageExample]; examples_file: Path | None
    amendments: list[Amendment]; fingerprint: str
def load_charter(...) -> Charter                    # L303
def append_example(charter: Charter, example: TriageExample, path: Path | None = None)  # L333

# From packages/ai-parrot/src/parrot/knowledge/wiki/review.py
class DimensionScores(BaseModel): density: float; novelty: float; durability: float   # L58
class Claim(BaseModel): text: str; grounded: bool | None = None                       # L74
class TriageOutput(BaseModel):                      # L88
    briefing: str; scores: DimensionScores; claims: list[Claim] = []
    sensitive: bool = False; category_hint: str | None = None   # <- no consumer anywhere
class ManifestRunHeader(BaseModel):                 # L111
    charter_version: str; mode: Literal["dry-run","review","interactive","auto"]
    novelty_backend: Literal["grounding","search-proxy"]; counts: dict[str,int]; created_at: str
class ManifestDocEntry(BaseModel):                  # L135
    source_uri: str; file_hash: str; briefing: str; scores: DimensionScores
    composite: float; proposed_action: Literal["admit","archive","discard"]
    claims: list[Claim]; decision: Literal["admit","archive","discard"] | None
    decision_source: Literal["heuristic","model","human","auto"] | None
    audit_sample: bool = False; audit_stratum: str | None = None

# From packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py
class IngestReport(BaseModel):                      # L120
    source_id: str; source_uri: str; pages_created: int; pages_updated: int
    graph_nodes_created: int; duration_ms: float; status: str = "ok"; error: str | None
    # NOTE: no page ids — recover them via SourceCollectionManager.get_source(source_id).pages_generated
class WikiIngestOrchestrator:                       # L144
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any,
                 source_manager: SourceCollectionManager, bookkeeper: WikiBookkeeper,
                 store: Optional[BaseWikiStore] = None, sync_graph: bool = False) -> None  # L164
    async def ingest(self, source_path: str, wiki_config: WikiConfig, *,
                     triage: Optional[ManifestDocEntry] = None,
                     charter_version: Optional[str] = None,
                     acquired: AcquiredDocument | None = None) -> IngestReport          # L198
    async def _build_page_records(self, tree_name: str, node_ids: list[str], source_id: str,
                                  fallback_title: str = "", fallback_summary: str = "",
                                  category_override: Optional[str] = None,
                                  frontmatter: str = "") -> list[WikiPageRecord]      # L822
    # frontmatter is rendered at L397-400 only when `triage` is given (FEAT-451)

# From packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                      # L108
    def get_source(self, source_id: str) -> SourceManifestEntry | None            # L514
    def is_stale(...)                                                              # L532
    def record_decision(self, path: Path, *, destination: str, decision_source: str | None = None,
                        charter_version: str | None = None, composite_score: float | None = None,
                        pages_generated: list[str] | None = None, status: str | None = None,
                        external_id: str | None = None) -> SourceManifestEntry     # L631
    def record_document_metadata(...)                                              # L730
    def _migrate_sources_columns(self) -> None   # additive ALTER TABLE pattern    # L1427

# From packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiPageCategory(str, Enum):                  # L25
    SUMMARY="summary"; ENTITY="entity"; CONCEPT="concept"; COMPARISON="comparison"
    OVERVIEW="overview"; SYNTHESIS="synthesis"; ANSWER="answer"; ARCHIVE="archive"
class SourceManifestEntry(BaseModel):               # L155
    pages_generated: list[str]                      # L205

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel):                    # L409
    concept_id: str; node_id: Optional[str]; title: str = ""; category: str = "concept"
    summary: str = ""; body: str = ""; source_id: Optional[str]; token_count: int = 0
    origin: str = "ingest"; asserted_by: Optional[str]; updated_at: Optional[str]
    content_hash: Optional[str]                     # <- NO `tags` field
class BaseWikiStore(ABC):                           # L525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int             # L544
    async def add_edges(self, edges: list[tuple]) -> int   # (src, dst, rel[, provenance]) ; default provenance 'extracted'  # L547 / impl L1643
    async def replace_source_slice(...)                                           # L550
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]  # L565
    async def list_pages(self, category: Optional[str] = None, limit: int = 100,
                         origin: Optional[list[str]] = None) -> list[dict[str, Any]]  # L568  (no source_id filter)
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]  # L576

# From packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                           # L32
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any,
                 default_weights: Optional[dict[str, float]] = None,
                 store: Optional[BaseWikiStore] = None,
                 embedder: Optional[Callable[[str], Awaitable[list[float]]]] = None,
                 normalize_store_rows: bool = True) -> None                        # L47
    async def search(self, query: str, mode: str = "combined", top_k: int = 10,
                     tree_name: Optional[str] = None, weights: Optional[dict[str, float]] = None,
                     include_archived: bool = False) -> list[WikiSearchResult]    # L91
    async def find_related(...)                                                   # L281

# From packages/ai-parrot/src/parrot/knowledge/wiki/export.py
def okf_type(category: str) -> str                  # L71
def category_dir(category: str) -> str              # L76  (naive plural, lowercase)
def page_frontmatter(page: dict[str, Any], relates_to: list[dict[str, str]]) -> str   # L86
    # keys: type, title, id, tags=[category], timestamp, summary?, relates_to?
async def export_okf_bundle(store: BaseWikiStore, output_dir: Path, wiki_name: str = "") -> WikiExportReport  # L125

# From packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py  (private — mirror, do not import)
def _page_path(self, page) -> Path       # <bundle>/<category_dir>/<flatten_concept_id_for_filename(id)>.md  # L209
def _render_page_file(self, page) -> str # page_frontmatter + machine block (category,node_id,source_id,token_count,created_at,content_hash) + body  # L215
def _write_page_file_atomic(self, page) -> None  # temp sibling + os.replace     # L241

# From packages/ai-parrot/src/parrot/knowledge/okf/utils.py
def flatten_concept_id_for_filename(concept_id: str) -> str   # L18  ('/' -> '--')

# From packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py
class WikiBookkeeper:                               # L31
    def log_operation(self, wiki_dir: Path, operation: str, details: str, timestamp: Optional[str] = None) -> None  # L175

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
PARROT_DIR = ".parrot"                              # L43
class WikiProjectConfig(BaseModel):                 # L382
    wiki_name: str = "codebase"; storage_dir: str = ".parrot/wiki"; backend: Literal["sqlite","memory","arangodb"]
    include_suffixes: list[str]; exclude_dirs: list[str]; sync_graph: bool; vault_dir: str | None
    namespaces: dict[str, WikiNamespaceConfig]; obsidian_sync: ObsidianSyncConfig | None
    decisions: DecisionConfig; schema_plane: SchemaPlaneConfig; ...   # no `inbox` field today
    def storage_path(self, root: Path) -> Path      # L555
    def db_path(self, root: Path) -> Path           # L560
class WikiEnvOverlay(BaseModel): ...                # L816  (per-env overrides; mirror new field here)

# From packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                          # L42
    async def ask_structured(self, prompt: str, output_type: type, temperature: float = 0.0,
                             system_prompt: Optional[str] = None) -> Any          # L99

# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]         # L367
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore           # L464
def _open_sources(root, config, store=...)                                        # L521
def _run(coro: Any) -> Any                                                        # L560
def _env_setting(name: str) -> str | None                                         # L565
def _authoring_identity(by: str | None) -> str   # --by > CLAUDE_AGENT_ID/PARROT_AGENT_ID (agent:) > human:<user>  # L3513
def remember(...)                                 # L3806  page_id = "mem-" + sha1(f"{title}::{category}")[:12]; edges (page_id, dst, rel, "asserted")
def _resolve_model_id(cli_value: str | None, env_name: str) -> str                # L4455
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]  # L4477  (test seam — monkeypatched in FEAT-402 tests)
def ingest(source, path_, charter_opt, dry_run, review_opt, interactive_flag, auto_flag, extract_flag,
           lightweight_model_opt, model_opt, audit_rate, manifest_opt, recursive, fetch_timeout, refresh_flag)  # L4794
    # default charter: root / PARROT_DIR / "charter.yaml"  (L4449)
    # router = IngestTriageRouter(charter, light_adapter, sources, novelty_scorer, heavy_adapter=heavy_adapter)
    # refs = resolve_sources(source, recursive=recursive); orch.ingest(..., triage=entry, acquired=acquired)
def ingest_jira(...)                              # L5249

# From packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class WikiRememberTool(AbstractTool): name = "wiki_remember"   # L336  (pattern for a write tool with storage_dir)
def create_wiki_tools(store: BaseWikiStore, root: Path | None = None,
                      config: WikiProjectConfig | None = None,
                      ledger_service: Union["LedgerService", None] = None) -> list[AbstractTool]  # L807

# From packages/ai-parrot/src/parrot/knowledge/wiki/entry.py
def main() -> None   # console script `wikitoolkit` (pyproject.toml:204) → cli.main unless argv == ["claude-hook"]
```

#### Verified Imports
```python
from parrot.knowledge.wiki.documents import (
    AcquiredDocument, DocumentAcquirer, DocumentAcquisitionError, DocumentRef,
    DocumentMetadata, TriageProvenance, render_frontmatter, resolve_sources, split_frontmatter,
)                                                                   # documents.py L69-294
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer   # triage.py L67, L252
from parrot.knowledge.wiki.charter import Charter, TriageExample, load_charter, append_example  # charter.py
from parrot.knowledge.wiki.review import (
    Claim, DimensionScores, ManifestDocEntry, ManifestRunHeader, TriageOutput,
)                                                                   # review.py L58-169
from parrot.knowledge.wiki.ingest import IngestReport, WikiIngestOrchestrator  # ingest.py L120, L144
from parrot.knowledge.wiki.sources import SourceCollectionManager   # sources.py L108
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens  # store.py
from parrot.knowledge.wiki.search import WikiCombinedSearch        # search.py L32
from parrot.knowledge.wiki.export import category_dir, okf_type, page_frontmatter  # export.py
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename  # okf/utils.py L18
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper        # bookkeeper.py L31
from parrot.knowledge.wiki.models import WikiConfig, WikiPageCategory, SourceManifestEntry  # models.py
from parrot.knowledge.wiki.project import PARROT_DIR, WikiProjectConfig, WikiEnvOverlay  # project.py
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter  # llm_adapter.py L42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit    # imported lazily in cli.ingest
from parrot.knowledge.wiki.tools import create_wiki_tools          # tools.py L807
from parrot.tools import AbstractTool, ToolResult                  # used by tools.py
```

#### Key Attributes & Constants
- `WikiProjectConfig.storage_dir` default `".parrot/wiki"`; repo `.parrot/wiki.json` sets `exclude_dirs: [".parrot/wiki"]` so a markdown projection under the storage dir is never rescanned by `build`.
- `.gitignore:385` `.parrot/*` with negation `!.parrot/wiki.local.json` (L389) — `.parrot/archive/` is git-ignored by default; `inbox/` is not ignored by any rule.
- `BaseWikiStore.add_edges` tuple shape `(src, dst, rel[, provenance])`, provenance default `'extracted'`; `remember` uses `'asserted'` (cli.py:3877).
- `WikiPageRecord.origin ∈ {"ingest","authored","memory"}`; `asserted_by` convention `agent:<id>` / `human:<user>` (`_authoring_identity`).
- `WikiSearchResult` is the type returned by `WikiCombinedSearch.search` (models.py L258).
- Default charter path: `<root>/.parrot/charter.yaml` (cli.py:4449); env fallbacks `WIKI_LIGHTWEIGHT_MODEL`, `WIKI_MODEL`, kill switch `PARROT_NO_AUTO_LLM` (cli.py ingest body).
- `vault_scan.py:18,186` — `[[wikilink]]` → `references` edge precedent (Obsidian plane).
- Tests precedent: `packages/ai-parrot/tests/knowledge/wiki/test_cli.py` uses `click.testing.CliRunner` over `parrot.knowledge.wiki.cli.wiki`; FEAT-402 tests monkeypatch `_build_triage_adapters`.
- Prior features (all `done`): FEAT-402 supervised-wiki-ingestion, FEAT-451 wikitoolkit-ingest-documents, FEAT-450 wiki-namespaces, FEAT-452 audio-notes-obsidian. In flight: FEAT-481 fireflies-wiki-knowledgebase-agent (touches `toolkit.py`, `models.py`), FEAT-569 wikitoolkit-http-mcp (touches `tools.py`, `mcp_server.py`, `cli.py`, `project.py`).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/knowledge/wiki/inbox.py`~~, ~~`archive.py`~~, ~~`classify.py`~~ — none exist; `inbox.py` is the module this feature creates.
- ~~`wikitoolkit inbox`~~ command, ~~`wiki_inbox`~~ MCP tool — do not exist.
- ~~`WikiProjectConfig.inbox`~~, ~~`.inbox_dir`~~, ~~`.archive_dir`~~ — no such fields (project.py L382-520).
- ~~`Charter.taxonomy`~~, ~~`Charter.kinds`~~ — not in `Charter` (charter.py L208-300).
- ~~`WikiPageRecord.tags`~~ — there is no tags column; `page_frontmatter` emits `tags=[category]` only (export.py L95).
- ~~`IngestReport.pages_generated`~~ / ~~`.page_ids`~~ — the report carries counts only; ids live in `SourceManifestEntry.pages_generated`.
- ~~`BaseWikiStore.list_pages(source_id=...)`~~ — `list_pages` filters by `category`/`origin`/`limit` only.
- ~~`TriageOutput.category_hint` consumer~~ — the field exists but nothing reads it.
- ~~`inbox/`~~ and ~~`.parrot/archive/`~~ directories — absent in the repo today.
- ~~`SQLiteFileStore` public render API~~ — `_page_path`, `_render_page_file`, `_write_page_file_atomic` are private to the memory backend; the inbox must mirror them, not import them.
- ~~`WikiIngestOrchestrator.ingest(category=...)`~~ / ~~`(tags=...)`~~ — no such parameters; category is forced only for `archive` decisions.
- ~~a `--watch` / daemon / inotify mode~~ — not part of this feature by decision.
- ~~a git post-commit hook running `inbox`~~ — explicitly excluded (LLM required).

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Independent units after the models
  land: (a) charter `taxonomy` extension + default taxonomy; (b)
  `InboxConfig` on `WikiProjectConfig`/`WikiEnvOverlay`; (c) classification
  stage; (d) link-proposal stage; (e) markdown projection + archive helpers;
  (f) `InboxProcessor` orchestration; (g) CLI command (+ factoring the
  adapter construction out of `ingest`); (h) MCP tool; (i) docs. (c), (d),
  (e) can be built and unit-tested in parallel once (a)/(b) and the Pydantic
  models exist; (f)–(h) are sequential on them.
- **Cross-feature independence**: **conflicts with FEAT-569
  wikitoolkit-http-mcp** (in progress, 17 tasks) on `cli.py`, `tools.py`,
  `mcp_server.py`, `project.py`; mild overlap with **FEAT-481
  fireflies-wiki-knowledgebase-agent** (in progress) on the *domain*
  (meeting pages) and on `toolkit.py`/`models.py` — the inbox should accept
  Fireflies exports without creating a second page for a meeting FEAT-481
  already filed (`external_id` on the source manifest is the hook). No
  overlap with `ingest.py`, `triage.py`, `documents.py`, `charter.py`,
  `sources.py` (all read-only or additive here).
- **Recommended isolation**: `per-spec` — one worktree, tasks sequential,
  with the `cli.py` / `tools.py` / `mcp_server.py` tasks ordered **last** and
  rebased on `dev` after FEAT-569 merges (or the MCP tool deferred to a
  follow-up if FEAT-569 is still open at `/sdd-done` time).
- **Rationale**: the hot files (`cli.py` at 208 KB, `tools.py`,
  `mcp_server.py`) are single points of contention with an in-flight feature;
  everything new is confined to one new module plus two additive model
  fields, which does not justify multiple worktrees.

---

## Open Questions

- [ ] **Merge classification into the triage Stage-1 prompt** (one call
  returning `TriageOutput` + kind/tags, using the dormant `category_hint`)
  versus a separate `InboxClassification` call? Separate is cleaner and keeps
  FEAT-402 prompts untouched; merged saves one LLM call per document. —
  *Owner: Jesus*
- [ ] **Tags representation**: `tag:<slug>` pages + `tagged` edges (no
  migration, navigable) versus an additive `tags` column on `pages` in SQLite
  and ArangoDB stores? Brainstorm recommends tag pages for v1. — *Owner:
  Jesus*
- [ ] **Document page identity**: decorate the PageIndex root page (keeps
  FEAT-402 behaviour, one tree per document) or create a dedicated
  `doc:<slug>` page like `remember` does and leave the PageIndex pages as
  children? — *Owner: spec author*
- [ ] **Git staging policy**: stage the deletion (`git rm --cached` after the
  move) as decided, or additionally offer `--commit` with a conventional
  message (`wiki: ingest inbox (<n> docs)`)? Default remains never-commit. —
  *Owner: Jesus*
- [ ] **Duplicate policy**: an unchanged file re-dropped in the inbox is a
  Stage-0 heuristic reject → archived under `rejected/`. Acceptable, or
  should exact duplicates be archived under the normal path with a
  `duplicate` marker and no `rejected` stigma? — *Owner: Jesus*
- [ ] **Markdown projection location**: `<storage_dir>/inbox/<category>/`
  (recommended, avoids colliding with the memory backend's `pages/` bundle
  name) versus `<storage_dir>/pages/` to be a valid OKF bundle root. —
  *Owner: spec author*
- [ ] **Default taxonomy** list and the kind → `WikiPageCategory` mapping to
  ship (meeting→summary, briefing→overview, decision→concept,
  report→synthesis, memo→summary, note→concept?). Should `decision` kinds
  additionally feed the ADR plane (`wikitoolkit adr`, FEAT-578) as
  candidates? — *Owner: Jesus*
- [ ] **Link relation vocabulary**: `references`, `relates_to`, `mentions`,
  `follows_up`, `supersedes` — final set, and whether `supersedes` should
  demote the older page's ranking. — *Owner: spec author*
- [ ] **Candidate cap and search mix**: top-k from `WikiCombinedSearch` plus
  per-tag FTS; include `sym:`/`file:` code pages by default or only when the
  document mentions a symbol verbatim? — *Owner: spec author*
- [ ] **MCP tool timing**: implement `wiki_inbox` in this feature (conflicts
  with FEAT-569 on `tools.py`/`mcp_server.py`) or defer to a follow-up after
  FEAT-569 merges? — *Owner: Jesus*
- [ ] **Fireflies overlap** (FEAT-481): should the inbox detect a Fireflies
  export (`fireflies:<id>` external id) and update that page instead of
  creating a new one? — *Owner: Jesus*
