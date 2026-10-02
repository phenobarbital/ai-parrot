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

# Feature Specification: `wikitoolkit inbox` — autonomous inbox ingestion into the LLM Wiki

**Feature ID**: FEAT-626
**Date**: 2026-10-03
**Author**: Jesus Lara (spec: Claude session 2026-10-03)
**Status**: approved
**Target version**: next minor
**Brainstorm**: `sdd/proposals/wikitoolkit-new-ingestion.brainstorm.md` (accepted 2026-10-03, Option A)
**Builds on**: FEAT-402 `supervised-wiki-ingestion`, FEAT-451 `wikitoolkit-ingest-documents`, FEAT-578 `sdd-spec-wiki-adr`

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The LLM Wiki already has a supervised document-ingestion lane:
`wikitoolkit ingest <SOURCE>` (FEAT-402 charter-driven triage + JSONL
manifest review, FEAT-451 loader-backed PDF/DOCX/PPTX extraction + YAML
frontmatter). It is built for *curating a corpus with a human in the loop*:
every run needs a mode (`--dry-run` / `--review` / `--interactive` /
`--auto`), the operator points it at an arbitrary folder, and the originals
stay where they were.

What is missing is the **drop-box workflow** for "corporate digital life"
documents — meeting notes, briefings, memos, decisions, reports — that arrive
one by one:

1. **No fixed intake location.** Nothing watches a conventional folder such
   as `inbox/`; each ingest is an ad-hoc invocation with a path argument.
2. **No classification beyond admit/archive/discard.** Triage decides
   *whether* a document enters the wiki, not *what it is*. Pages land with
   PageIndex's generic categories and no tags.
3. **No relations to the existing graph.** An ingested document becomes an
   island: `summarizes` edges to its own source only. A meeting that
   discusses a module, a decision or a previous meeting is never linked to
   those pages, so `wikitoolkit related` cannot travel from one to the other.
4. **No on-disk markdown.** With the default `sqlite` backend the page body
   lives only inside `.parrot/wiki/wiki.db`; OKF markdown exists only as a
   whole-plane export or in the `memory` backend's bundle.
5. **No lifecycle for the original.** Processed files stay in place, so the
   operator cannot tell "already ingested" from "still pending" by looking at
   the folder, and re-running re-triages everything.

Affected users: repository maintainers who drop meeting notes and briefings
into the repo, and the coding agents that later query the wiki for that
context.

### Goals

- **G1 — One command, fixed intake.** `wikitoolkit inbox` processes every
  document in the configured, git-tracked `inbox/` folder (default) with no
  mode flag, no path argument and no human checkpoint.
- **G2 — Reuse, do not fork, the FEAT-402/451 pipeline.** Acquisition
  (`DocumentAcquirer`), triage (`IngestTriageRouter`), page creation and
  provenance (`WikiIngestOrchestrator`, `SourceCollectionManager`,
  `WikiBookkeeper`) are consumed as they are. `build`, `upsert`, `ingest`
  and the git post-commit hook stay byte-identical.
- **G3 — Charter-defined taxonomy.** The LLM picks one *document kind* from
  a closed list declared in the charter (`taxonomy:` block, with a built-in
  default of six kinds); code maps the kind to a wiki category and
  normalizes free-form tags to kebab-case.
- **G4 — Verified relations.** Candidate pages are retrieved lexically
  (≤ 20), the LLM selects related ones with a relation from a closed
  vocabulary and a reason, and only ids the store can return become edges
  and `[[wikilinks]]`.
- **G5 — One stable document page.** Each admitted document gets a
  `doc:<slug>` page that carries category, summary, tags, links and
  frontmatter; the orchestrator's PageIndex pages become its children via
  `part_of` edges and are never rewritten.
- **G6 — Tags as graph nodes.** Tags are `tag:<slug>` pages joined by
  `tagged` edges — no `pages` schema migration in any backend.
- **G7 — Decisions feed the ADR plane.** A document classified as
  `decision` also emits an `origin="inferred"`, `review_status="unreviewed"`
  candidate into the FEAT-578 decisions plane for `wikitoolkit adr review`.
- **G8 — On-disk markdown projection.** The doc page is rendered as an OKF
  markdown file under `<storage_dir>/inbox/<category-plural>/<flat-id>.md`;
  the SQLite page remains the retrieval truth and the file is write-only.
- **G9 — Archive lifecycle.** After the page and the markdown are persisted
  the original moves to `.parrot/archive/[rejected/]<stem>.<YYYY-MM-DD>.<ext>`;
  a tracked original has its deletion staged (`git rm --cached`); the
  command never commits. A clean run leaves the inbox empty.
- **G10 — Idempotent and crash-safe.** Any failure leaves the document in
  the inbox; nothing is archived before its page and markdown exist;
  re-running resumes without duplicating pages (`replace_source_slice`).
- **G11 — Fireflies-aware.** A document that carries a Fireflies id updates
  the source FEAT-481 already filed (`find_by_external_id`) instead of
  creating a second doc page.

### Non-Goals (explicitly out of scope)

- A `wiki_inbox` **MCP tool** — deferred to a follow-up feature because
  FEAT-569 (`wikitoolkit-http-mcp`) is in flight on `tools.py` and
  `mcp_server.py`. `InboxProcessor` is shaped so the tool is a thin wrapper;
  a ledger item is opened by the docs task (M9).
- A watcher / daemon / `--watch` mode, a default git post-commit hook, or a
  scheduler integration — the command needs an LLM and is run manually (by
  a human or an agent).
- Changing FEAT-402 triage prompts or `TriageOutput` — the classification
  is a separate structured call (resolved in brainstorm); `category_hint`
  stays dormant.
- A `tags` column on `pages`, ranking demotion for `supersedes`, or any
  change to the search read path.
- Extending `ingest` with `--inbox`/`--archive-to` flags and an agent-driven
  (ReAct) ingestion loop were rejected in the brainstorm (Options B and C).
- A `--commit` flag; committing is the human's job.

---

## 2. Architectural Design

### Overview

A new sub-package `parrot/knowledge/wiki/inbox/` hosts an `InboxProcessor`
that composes the existing FEAT-402/451 pipeline with five new, bounded
stages. For every document in the inbox folder it runs:

1. **Acquire** — `resolve_sources(inbox_dir)` + `DocumentAcquirer.acquire()`
   (binary formats through the optional `ai-parrot-loaders`, `.md`
   frontmatter split off the body). A `DocumentAcquisitionError` counts as
   *skipped*; the file stays.
2. **Fireflies pre-check** — if the document carries a Fireflies id, look up
   `fireflies:<id>` with `SourceCollectionManager.find_by_external_id`; on a
   hit, `update_source_uri(existing.source_id, inbox_path)` repoints that
   source to the inbox file **before** ingest, so the orchestrator's
   URI lookup finds the same `source_id` (it would otherwise `add_source` a
   second, path-derived source — design research S5) and the run updates
   the existing doc page.
3. **Triage** — `IngestTriageRouter.triage(path, text)`; `--auto` semantics
   (`decision = proposed_action`, `decision_source="auto"`, heuristic
   rejects keep `"heuristic"`). Stage-0 rejects (duplicate, size, suffix)
   and `discard` decisions spend no further LLM call: the orchestrator
   records the rejection and the original is archived under `rejected/`.
4. **Classify** (new) — one `ask_structured()` call on the lightweight tier
   returns an `InboxClassification`; code validates `kind` against the
   charter taxonomy (fallback `default_kind`, flagged), maps it to a
   `WikiPageCategory`, normalizes and caps tags, derives the title.
5. **Propose links** (new) — candidates = combined search top-k over
   title + tags + claims ∪ per-tag FTS ∪ verbatim `sym:`/`file:` mentions,
   deduped, own pages excluded, capped at `max_candidates` (20). A second
   structured call returns a `LinkSelection` restricted to candidate ids and
   the closed relation vocabulary; every id is re-verified with
   `store.get_page`; misses are dropped and logged. On LLM failure the
   stage degrades to the deterministic verbatim-mention links.
6. **Ingest** — `WikiIngestOrchestrator.ingest(path, wiki_config,
   triage=entry, charter_version=charter.version, acquired=acquired)`: the
   unchanged FEAT-402/451 path (PageIndex pages, `summarizes` edges, source
   manifest `record_decision`, frontmatter, bookkeeper `ADMIT`/`ARCHIVE`).
7. **Document page** (new) — upsert `doc:<slug>` with category, title,
   summary, frontmatter + body, **`source_id=None`, `origin="authored"`**
   (the same shape `remember` pages use), `asserted_by="agent:wikitoolkit-inbox"`.
   The doc page must **not** share the orchestrator's `source_id`:
   `replace_source_slice` deletes every page with that id and every edge
   touching them on re-ingest (`store.py:1664-1750`, design research S1),
   which would erase the doc page and its inbound links. The source
   identity (`source_id`, `source_uri`, `file_hash`) travels in the doc
   page's frontmatter instead. Join the orchestrator's pages
   (`get_source(source_id).pages_generated`) with `part_of` edges (rewritten
   after every ingest, since child ids may change); write asserted link
   edges; ensure `tag:<slug>` pages and `tagged` edges; for
   `kind == decision` save an inferred `DecisionRecord` through
   `DecisionRepository` — `get(decision_id)` first, reuse an existing record
   (`save(record, None)` is insert-only and raises `ADR_REVISION_CONFLICT`
   otherwise, S6); lazy import; failure logged, never fatal.
8. **Project markdown** (new) — render the doc page as an OKF file
   (`page_frontmatter(page, relates_to, tags=[category, *tags])` + machine
   block + body, mirroring the memory backend's `_render_page_file`)
   atomically under `<markdown_dir>/<category_dir>/<flat-id>.md`; regenerate
   `<markdown_dir>/index.md`. The `tags` parameter is a new, optional,
   additive argument on `export.page_frontmatter` (S4).
8b. **Verify** (new) — before anything is moved, re-read what the previous
   stages claim to have persisted: the source entry exists with the
   expected decision, every id in `pages_generated` resolves via
   `store.get_page`, the doc page resolves, and the markdown file exists.
   The orchestrator downgrades store-sync, manifest and bookkeeping
   failures to warnings and still returns `status="ok"`
   (`ingest.py:436-529`, S2), so `IngestReport.status` alone must never
   gate archiving. A failed verification marks the document `failed` and
   leaves it in the inbox.
9. **Archive** (new) — move the original to
   `<archive_dir>[/rejected]/<stem>.<YYYY-MM-DD>.<ext>` (`-N` on collision,
   `shutil.move` across filesystems); when `stage_git` is on and the file is
   tracked, `git rm --cached --quiet -- <path>`; **repoint the source to the
   archived file** with `update_source_uri(source_id, destination)` so the
   manifest keeps resolving (and `is_stale` keeps working) after the move
   (S5); persist `archived_to` / `archived_at` in the source's
   `doc_metadata.extra` (`record_document_metadata`); bookkeeper
   `ARCHIVE_ORIGINAL`.

Ordering **persist → project → verify → archive** is the crash-safety
invariant: a document is removed from the inbox only once its page and its
markdown are confirmed to exist. The guarantee is **transactional on the
`sqlite` backend** (one `_write` transaction per slice, `store.py:1696`)
and best-effort on `memory` / `arangodb`, which write in steps (S3); the
ordering still holds there, but a crash mid-slice may need a re-run to
converge. The **whole run holds `wiki_write_lock(storage_path)`** (the
same advisory flock `build`/`upsert` use, `project.py:74`, S9) so two
inbox processes — or an inbox and a `build` — never triage the same file
twice or race on archive names and git staging; lock timeout → exit 3
with a clear message. `--dry-run` runs stages 1–5 and prints the plan
without any write, move or bookkeeper mutation beyond a `DRY_RUN` line.

Configuration: `WikiProjectConfig.inbox: InboxConfig` (defaults: `dir:
"inbox"`, `archive_dir: ".parrot/archive"`, `rejected_subdir: "rejected"`,
`markdown_dir: None` → `<storage_dir>/inbox`, `date_format: "%Y-%m-%d"`,
`stage_git: true`, `max_candidates: 20`, `lock_timeout: 30.0`), mirrored on
`WikiEnvOverlay`. Path safety (S10): the resolved inbox, archive and
markdown dirs must lie inside the repository root and must not nest in one
another (archive inside inbox would re-ingest its own output); symlinked
entries and anything resolving outside the inbox dir are skipped with a
report row, never moved or staged. The
charter gains an optional `taxonomy:` block (`kinds[]`, `default_kind`,
`max_tags`) whose absence yields the built-in default taxonomy, so existing
charters keep validating; the charter fingerprint covers the block.

The `.gitignore` rule `.parrot/*` already ignores the archive and the
storage dir; `inbox/` is not ignored by any rule. The repo's
`.parrot/wiki.json` sets `exclude_dirs: [".parrot/wiki"]`, so `build` never
rescans the markdown projection.

### Component Diagram
```
inbox/<file>  ──▶ resolve_sources ──▶ DocumentAcquirer.acquire ──▶ AcquiredDocument
                                                                       │
                      find_by_external_id("fireflies:<id>")  ◀─────────┤ (pre-check)
                                                                       ▼
                                             IngestTriageRouter.triage ──▶ ManifestDocEntry (auto)
                                                       │ discard / heuristic             │ admit / archive
                                                       ▼                                 ▼
                              WikiIngestOrchestrator.ingest(triage=…)        InboxClassifier.classify  ──▶ ResolvedClassification
                              (records rejection, no pages)                            │
                                                       │                                ▼
                                                       │              LinkProposer.candidates → .select → VerifiedLink[]
                                                       │                                │
                                                       │                                ▼
                                                       │        WikiIngestOrchestrator.ingest(triage=, acquired=)  ──▶ IngestReport
                                                       │                                │
                                                       │                                ▼
                                                       │        DocPageWriter: doc:<slug> page · part_of · links · tag:<slug>/tagged
                                                       │                                │ (kind == decision) ──▶ DecisionRepository.save
                                                       │                                ▼
                                                       │        write_doc_markdown  → <storage_dir>/inbox/<cat>/<id>.md (+ index.md)
                                                       │                                │
                                                       ▼                                ▼
                                   archive_original → .parrot/archive/rejected/…   archive_original → .parrot/archive/<stem>.<date>.<ext>
                                                       └──────────────┬─────────────────┘
                                                                      ▼
                                                     git rm --cached (tracked) · record_document_metadata(extra.archived_to) · bookkeeper
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/documents.py` — `resolve_sources`, `DocumentAcquirer`, `split_frontmatter`, `render_frontmatter` | uses | acquisition and `.md` frontmatter; unchanged |
| `parrot/knowledge/wiki/triage.py` — `IngestTriageRouter`, `NoveltyScorer` | extends (additive) | `--auto` semantics; new `skip_duplicate_check` kwarg on `triage()` for `--force` (S7); default path unchanged |
| `parrot/knowledge/wiki/project.py` — `wiki_write_lock` | uses | whole-run advisory lock, as `build`/`upsert` (S9) |
| `parrot/knowledge/wiki/sources.py` — `update_source_uri` | uses | Fireflies repoint before ingest; archive repoint after the move (S5) |
| `parrot/knowledge/wiki/charter.py` — `Charter`, `load_charter` | extends (additive) | optional `taxonomy` block + default |
| `parrot/knowledge/wiki/ingest.py` — `WikiIngestOrchestrator.ingest(triage=, acquired=)` | uses | unchanged; the only page-creation path |
| `parrot/knowledge/wiki/sources.py` — `get_source`, `record_document_metadata`, `find_by_external_id`, `record_decision` | uses | page ids, archive provenance, Fireflies pre-check |
| `parrot/knowledge/wiki/store.py` — `upsert_pages`, `add_edges`, `get_page`, `search_fts` | uses | doc/tag pages and edges; no schema change |
| `parrot/knowledge/wiki/search.py` — `WikiCombinedSearch.search` | uses | link candidates (store-only mode: `WikiCombinedSearch(None, None, store=store)`) |
| `parrot/knowledge/wiki/export.py` — `page_frontmatter`, `category_dir`, `okf_type` | extends (additive) | markdown projection; `page_frontmatter` gains an optional `tags` parameter (default emits `[category]` as today, S4) |
| `parrot/knowledge/okf/utils.py` — `flatten_concept_id_for_filename` | uses | file stem |
| `parrot/knowledge/wiki/decisions/` — `DecisionRecord`, `EvidenceRef`, `DecisionRepository`, `codec.candidate_decision_id` | uses (lazy import) | ADR candidate for `decision` kinds; plane not modified |
| `parrot/knowledge/wiki/project.py` — `WikiProjectConfig`, `WikiEnvOverlay` | extends (additive) | `inbox: InboxConfig`; overlay merge is generic over `model_fields` (`project.py:977-981`) |
| `parrot/knowledge/wiki/cli.py` — `_resolve_project`, `_open_store`, `_open_sources`, `_run`, `_resolve_charter_path`, `_build_triage_adapters`, `_build_novelty_scorer`, `_authoring_identity`, `ingest` | extends | new `inbox` command; adapter/toolkit/orchestrator construction factored out of `ingest` into `_build_ingest_runtime` with no behaviour change |
| `parrot/knowledge/wiki/bookkeeper.py` — `WikiBookkeeper.log_operation` | uses | `TRIAGE`, `CLASSIFY`, `LINK_DROPPED`, `DOC_PAGE`, `ADR_CANDIDATE`, `ADR_CANDIDATE_SKIPPED`, `ARCHIVE_ORIGINAL`, `INBOX_RUN`, `DRY_RUN` lines |
| `parrot/knowledge/pageindex/llm_adapter.py` — `PageIndexLLMAdapter.ask_structured` | uses | classification + link selection (lightweight tier) |
| `docs/guides/llm-wiki-guide.md`, `docs/wiki/cheatsheet.md` | docs | new "Inbox ingestion" section / one-liner |
| `tools.py`, `mcp_server.py` | **none** | MCP tool deferred (FEAT-569 conflict) |

### Data Models
```python
# parrot/knowledge/wiki/charter.py  (additive)
class TaxonomyKind(BaseModel):
    id: str                       # kebab-case, unique within the taxonomy
    description: str
    category: str                 # a WikiPageCategory value (validated)
    tag_hints: list[str] = []

class Taxonomy(BaseModel):
    default_kind: str = "note"
    max_tags: int = 8             # ge=1, le=32
    kinds: list[TaxonomyKind]     # validator: ids unique, default_kind ∈ kinds

DEFAULT_TAXONOMY: Taxonomy  # meeting→summary, briefing→overview, decision→concept,
                            # report→synthesis, memo→summary, note→concept

# parrot/knowledge/wiki/project.py  (additive)
class InboxConfig(BaseModel):
    dir: str = "inbox"
    archive_dir: str = ".parrot/archive"
    rejected_subdir: str = "rejected"
    markdown_dir: str | None = None          # None → <storage_dir>/inbox
    date_format: str = "%Y-%m-%d"
    stage_git: bool = True
    max_candidates: int = 20                 # ge=1, le=100
    lock_timeout: float = 30.0               # seconds to wait for wiki_write_lock

# parrot/knowledge/wiki/inbox/models.py  (new)
RELATIONS = ("references", "relates_to", "mentions", "follows_up", "supersedes")

class InboxClassification(BaseModel):        # LLM structured output
    kind: str
    title: str
    summary: str
    tags: list[str] = []
    entities: list[str] = []
    event_date: str | None = None            # ISO date when the document states one

class ResolvedClassification(BaseModel):     # code-validated projection of the above
    kind: str
    category: str
    title: str
    summary: str
    tags: list[str]                          # kebab-case, deduped, ≤ max_tags
    entities: list[str]
    event_date: str | None
    classification_source: Literal["model", "fallback"]

class LinkCandidate(BaseModel):
    page_id: str; title: str; category: str; summary: str; origin: Literal["search", "tag_fts", "verbatim"]

class LinkChoice(BaseModel):                 # LLM structured output item
    page_id: str; rel: Literal[RELATIONS]; why: str

class LinkSelection(BaseModel):
    links: list[LinkChoice] = []

class VerifiedLink(BaseModel):
    page_id: str; rel: str; why: str; title: str

class ArchiveResult(BaseModel):
    source: Path; destination: Path; rejected: bool; staged_git: bool

class InboxDocResult(BaseModel):
    source_uri: str
    status: Literal["admitted", "archived_category", "rejected", "skipped", "failed", "dry_run"]
    decision: str | None; composite: float | None; decision_source: str | None
    kind: str | None; category: str | None; tags: list[str] = []
    links: list[VerifiedLink] = []
    doc_page_id: str | None; markdown_path: str | None; archived_to: str | None
    adr_candidate_id: str | None; adr_candidate_reused: bool = False; fireflies_match: str | None
    verified: bool = False                   # verify_persisted passed (always False for rejected/dry_run)
    error: str | None

class InboxRunReport(BaseModel):
    inbox_dir: str; charter_version: str; charter_fingerprint: str
    models: dict[str, str]                   # {"lightweight": ..., "heavy": ...}
    dry_run: bool
    counts: dict[str, int]                   # per InboxDocResult.status
    documents: list[InboxDocResult]
    @property
    def failed(self) -> bool: ...
```

### New Public Interfaces
```python
# parrot/knowledge/wiki/inbox/__init__.py
from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxRuntime
from parrot.knowledge.wiki.inbox.models import InboxRunReport, InboxDocResult

# wikitoolkit CLI
wikitoolkit inbox [--path ROOT] [--dry-run] [--limit N] [--charter PATH]
                  [--lightweight-model SPEC] [--model SPEC]
                  [--no-archive] [--force] [--json]
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Charter taxonomy | yes | Pydantic models + validators above; `DEFAULT_TAXONOMY` fixed; field `Charter.taxonomy` with `default_factory`; fingerprint unchanged for charters without the block | — |
| M2: Inbox config | yes | `InboxConfig` fields fixed; `WikiProjectConfig.inbox` + `WikiEnvOverlay.inbox`; three path helpers | — |
| M3: Inbox models + classifier | yes | models fixed above; prompt builder is pure; `normalize_tag`, `slugify_doc_id` contracts fixed; fallback semantics fixed | — |
| M4: Link proposer | yes | candidate sources, cap, relation vocabulary, verification and degradation fixed | — |
| M5: Doc page / tags / ADR candidate | yes | ids `doc:<slug>` / `tag:<slug>`, edge rels `part_of`/`tagged`/RELATIONS with provenance `asserted`, `DecisionRecord` field values fixed | — |
| M6: Markdown projection + archive | yes | file layout, rendering, atomic write, name collision rule, git staging command fixed | — |
| M7: InboxProcessor | yes | stage order, crash-safety ordering, per-document isolation, dry-run semantics, report shape fixed | — |
| M8: CLI command + runtime factoring | yes | option names fixed; `_build_ingest_runtime` extraction must keep `ingest` byte-identical (existing tests are the oracle) | — |
| M9: Docs + follow-up ledger item | yes | section anchors fixed; ledger command fixed | — |
| M10: Triage force seam + frontmatter tags | yes | one additive kwarg on `IngestTriageRouter.triage` threaded to `_heuristic_reject`; one additive `tags` kwarg on `export.page_frontmatter`; defaults byte-identical | — |

### Module 1: Charter taxonomy
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py`
- **Responsibility**: declare the closed set of document kinds, their wiki
  category mapping and the tag cap; ship the built-in default; keep every
  existing charter valid.
- **Depends on**: existing `Charter` (`charter.py:208`), `WikiPageCategory`
  (`models.py:25`).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/charter.py  (insert before `class Charter(BaseModel):` verified: charter.py:208)
  class TaxonomyKind(BaseModel):
      """One allowed document kind and the wiki category it maps to."""
      id: str                                # kebab-case; unique within a Taxonomy
      description: str
      category: str                          # must be a WikiPageCategory value (validator)
      tag_hints: list[str] = Field(default_factory=list)

  class Taxonomy(BaseModel):
      """Closed set of document kinds for `wikitoolkit inbox` classification."""
      default_kind: str = "note"
      max_tags: int = Field(default=8, ge=1, le=32)
      kinds: list[TaxonomyKind]

      @model_validator(mode="after")
      def _validate_kinds(self) -> "Taxonomy":
          """Ids unique and kebab-case; `default_kind` must name one of `kinds`; raises ValueError otherwise."""

      def kind(self, kind_id: str) -> TaxonomyKind | None:
          """Return the kind with this id, or None."""

  def default_taxonomy() -> Taxonomy:
      """Return a fresh copy of DEFAULT_TAXONOMY (meeting, briefing, decision, report, memo, note)."""

  class Charter(BaseModel):                  # verified: charter.py:208
      ...
      amendments: list[Amendment] = Field(default_factory=list)   # verified: charter.py:241
      taxonomy: Taxonomy = Field(default_factory=default_taxonomy)  # NEW — optional in YAML
  ```

### Module 2: Inbox config
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
- **Responsibility**: `InboxConfig` on `WikiProjectConfig` and
  `WikiEnvOverlay`, plus root-relative path helpers.
- **Depends on**: existing `WikiProjectConfig` (`project.py:382`),
  `WikiEnvOverlay` (`project.py:816`), `storage_path` (`project.py:555`).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/project.py  (insert before `class ObsidianSyncConfig(BaseModel):` verified: project.py:283)
  class InboxConfig(BaseModel):
      """`wikitoolkit inbox` folder, archive and projection settings (all repo-root-relative unless absolute)."""
      dir: str = Field(default="inbox")
      archive_dir: str = Field(default=f"{PARROT_DIR}/archive")
      rejected_subdir: str = Field(default="rejected")
      markdown_dir: str | None = Field(default=None, description="None → <storage_dir>/inbox")
      date_format: str = Field(default="%Y-%m-%d")
      stage_git: bool = Field(default=True)
      max_candidates: int = Field(default=20, ge=1, le=100)
      lock_timeout: float = Field(default=30.0, ge=0.0)

      @model_validator(mode="after")
      def _validate_layout(self) -> "InboxConfig":
          """Reject `rejected_subdir` containing path separators or '..', and an empty `dir`/`archive_dir`."""

  def validate_inbox_paths(root: Path, inbox: Path, archive: Path, markdown: Path) -> None:
      """Raise WikiConfigError unless all three resolve inside `root` and none is nested inside another (S10)."""

  class WikiProjectConfig(BaseModel):        # verified: project.py:382
      ...
      sqlite_performance_pragmas: bool = Field(...)   # verified: project.py:509 (multi-line Field; insert AFTER its closing paren)
      inbox: InboxConfig = Field(default_factory=InboxConfig)   # NEW

      def inbox_path(self, root: Path) -> Path:
          """Resolve `inbox.dir` against the repo root."""
      def archive_path(self, root: Path) -> Path:
          """Resolve `inbox.archive_dir` against the repo root."""
      def inbox_markdown_path(self, root: Path) -> Path:
          """`inbox.markdown_dir` resolved against root, else `storage_path(root) / "inbox"`."""

  class WikiEnvOverlay(BaseModel):           # verified: project.py:816
      ...
      claude: ClaudeIntegrationConfig | None = None   # verified: project.py:864
      inbox: InboxConfig | None = None                # NEW — merged generically by load_effective_config (project.py:977-981)
  ```

### Module 3: Inbox models + classifier
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py`,
  `inbox/models.py`, `inbox/classify.py`
- **Responsibility**: the Pydantic models in §2 Data Models; the
  classification prompt; kind validation, tag normalization, title
  derivation and doc-id slugging.
- **Depends on**: M1 (`Taxonomy`), `PageIndexLLMAdapter.ask_structured`
  (`llm_adapter.py:99`), `AcquiredDocument` (`documents.py:119`),
  `ManifestDocEntry` (`review.py:135`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py  (new)
  def normalize_tag(raw: str) -> str | None:
      """Lowercase, ASCII-fold, collapse non-alphanumerics to '-', strip; None when nothing survives or len > 64."""

  def normalize_tags(raw: Iterable[str], *, max_tags: int) -> list[str]:
      """Normalize, dedupe preserving order, cap at max_tags."""

  def slugify_doc_id(title: str, file_hash: str) -> str:
      """`doc:<kebab-title-max-48>-<file_hash[:8]>` — stable for the same content, unique across equal titles."""

  def build_classification_prompt(text: str, taxonomy: Taxonomy, briefing: str, metadata: DocumentMetadata) -> str:
      """Pure prompt builder: lists the allowed kind ids + descriptions, forbids inventing kinds, asks for ≤ max_tags tags."""

  class InboxClassifier:
      """Runs the structured classification call and resolves it against the taxonomy."""
      def __init__(self, adapter: PageIndexLLMAdapter, taxonomy: Taxonomy, *, max_chars: int = 24_000) -> None: ...
      async def classify(self, acquired: AcquiredDocument, triage: ManifestDocEntry) -> ResolvedClassification:
          """ask_structured(prompt, InboxClassification) → ResolvedClassification. Fail closed (S8): anything that is
          not an `InboxClassification` instance (dict, list, None, raw text) raises InboxClassificationError, as does an
          adapter failure. Only an explicit, well-formed but unknown `kind` falls back to taxonomy.default_kind with
          classification_source="fallback"."""
  ```

### Module 4: Link proposer
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py`
- **Responsibility**: candidate retrieval (combined search, per-tag FTS,
  verbatim `sym:`/`file:` mentions), LLM selection constrained to candidate
  ids and `RELATIONS`, id verification, deterministic degradation.
- **Depends on**: `WikiCombinedSearch.search` (`search.py:91`),
  `BaseWikiStore.search_fts` / `get_page` (`store.py:576`, `store.py:565`),
  `WikiSearchResult.node_id` (`models.py:258`), M3 models.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py  (new)
  _VERBATIM_RE: re.Pattern[str]   # matches `sym:...`, `file:...` ids and backticked `path/to/file.py` mentions

  class LinkProposer:
      """Retrieve → select → verify. Never emits an edge to an id the store cannot return."""
      def __init__(self, store: BaseWikiStore, search: WikiCombinedSearch, adapter: PageIndexLLMAdapter | None,
                   *, max_candidates: int = 20, top_k: int = 15) -> None: ...
      async def candidates(self, text: str, classification: ResolvedClassification, claims: list[Claim],
                           exclude_ids: set[str]) -> list[LinkCandidate]:
          """search(title+tags+claims, top_k, include_archived=False) ∪ search_fts(tag) per tag ∪ verbatim mentions;
          code pages (`sym:`/`file:`) only via the verbatim branch; dedupe; drop exclude_ids; cap at max_candidates."""
      async def select(self, text: str, classification: ResolvedClassification,
                       candidates: list[LinkCandidate]) -> list[VerifiedLink]:
          """ask_structured(prompt, LinkSelection); a result that is not a `LinkSelection` instance counts as adapter
          failure (S8). Keep choices whose page_id ∈ candidates and rel ∈ RELATIONS; drop duplicates (first wins) and
          self-links (page_id == the doc id); re-verify each with store.get_page(id, include_body=False); log
          LINK_DROPPED for misses. adapter None or adapter failure → deterministic_links(candidates)."""
      @staticmethod
      def deterministic_links(candidates: list[LinkCandidate]) -> list[VerifiedLink]:
          """Verbatim-mention candidates only, rel="references", why="verbatim mention"."""
  ```

### Module 5: Document page, tags and ADR candidate
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py`
- **Responsibility**: upsert the `doc:<slug>` page, `part_of` edges to the
  orchestrator's pages, asserted link edges, `tag:<slug>` pages + `tagged`
  edges, and the ADR candidate for `decision` kinds.
- **Depends on**: `WikiPageRecord`, `upsert_pages`, `add_edges`,
  `get_page` (`store.py:409`, `:544`, `:547`, `:565`), `estimate_tokens`
  (`store.py:318`), `SourceCollectionManager.get_source` (`sources.py:514`),
  `render_frontmatter` (`documents.py:221`), decisions plane
  (`decisions/models.py:78,143`, `decisions/repository.py:26,96`,
  `decisions/codec.py:109`) — imported lazily inside `emit_adr_candidate`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py  (new)
  INBOX_ASSERTED_BY = "agent:wikitoolkit-inbox"
  REL_PART_OF = "part_of"; REL_TAGGED = "tagged"; TAG_CATEGORY = "tag"

  def tag_page_id(tag: str) -> str:
      """`tag:<kebab-slug>`."""

  def render_doc_body(classification: ResolvedClassification, acquired: AcquiredDocument, provenance: TriageProvenance,
                      links: list[VerifiedLink], child_ids: list[str]) -> str:
      """render_frontmatter(metadata, provenance) + '# <title>' + summary + '## Related' ([[id]] — rel — why) + '## Sections' (child ids)."""

  class DocPageWriter:
      """Writes the document page and its graph neighbourhood; the orchestrator's pages are read, never rewritten."""
      def __init__(self, store: BaseWikiStore, sources: SourceCollectionManager, bookkeeper: WikiBookkeeper, wiki_dir: Path) -> None: ...
      async def write_doc_page(self, doc_id: str, source_id: str, classification: ResolvedClassification, acquired: AcquiredDocument,
                               triage: ManifestDocEntry, charter_version: str, links: list[VerifiedLink],
                               archive_decision: bool) -> str:
          """upsert_pages([WikiPageRecord(concept_id=doc_id, category=classification.category or "archive",
          origin="authored", asserted_by=INBOX_ASSERTED_BY, source_id=None, content_hash=triage.file_hash, …)]) — source_id
          MUST be None so replace_source_slice never deletes the doc page on re-ingest (S1); the source identity
          (source_id, source_uri, file_hash) is rendered into the frontmatter. Then add_edges: (child, doc_id, "part_of",
          "asserted") for every id in get_source(source_id).pages_generated, and (doc_id, link.page_id, link.rel, "asserted").
          Returns doc_id."""
      async def ensure_tags(self, doc_id: str, tags: list[str]) -> list[str]:
          """Create missing tag:<slug> pages (category "tag", origin "authored") and (doc_id, tag_id, "tagged", "asserted") edges."""
      async def emit_adr_candidate(self, doc_id: str, classification: ResolvedClassification, acquired: AcquiredDocument,
                                   doc_rel_path: str, config: WikiProjectConfig) -> tuple[str | None, bool]:
          """kind != "decision" or decisions disabled → (None, False). Else lazily import decisions.models/repository/codec,
          decision_id = candidate_decision_id(doc_id, file_hash, PROMPT_VERSION, summary) (deterministic per content);
          repo = DecisionRepository(store, max_records=config.decisions.max_records); if await repo.get(decision_id) is not
          None → (decision_id, True) and bookkeeper ADR_CANDIDATE_REUSED — an existing (possibly reviewed) record is never
          overwritten (S6: save(record, None) is insert-only and raises ADR_REVISION_CONFLICT). Else build
          DecisionRecord(decision_id, title, context=summary, decision=<decision sentence>, origin="inferred",
          source_status="unknown", review_status="unreviewed", external_id=f"inbox:{doc_id}", source_path=doc_rel_path,
          evidence=[EvidenceRef(kind="document", page_id=doc_id, rel_path=doc_rel_path, start_line=1,
          end_line=max(1, line_count), excerpt=<first 200 chars>)]) and await repo.save(record, None) → (decision_id, False).
          Any exception → bookkeeper ADR_CANDIDATE_SKIPPED, (None, False); never raises. `doc_rel_path` is the inbox-relative
          path of the original at ingest time (the evidence excerpt is captured before the move)."""
  ```

### Module 6: Markdown projection and archive
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py`,
  `inbox/archive.py`
- **Responsibility**: write-only OKF markdown projection of the doc page;
  date-stamped archiving with collision handling and git staging.
- **Depends on**: `page_frontmatter`, `category_dir` (`export.py:86`, `:76`),
  `flatten_concept_id_for_filename` (`okf/utils.py:18`),
  `generate_index` (`export.py:109`), `subprocess` pattern (`cli.py:3192`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py  (new)
  def doc_markdown_path(markdown_dir: Path, page: dict[str, Any]) -> Path:
      """markdown_dir / category_dir(category) / f"{flatten_concept_id_for_filename(concept_id)}.md"."""
  def render_doc_markdown(page: dict[str, Any], relates_to: list[dict[str, str]], tags: list[str]) -> str:
      """page_frontmatter(page, relates_to, tags=[category, *tags]) (new optional kwarg, M10 — no string surgery, S4)
      + machine block (category,node_id,source_id,token_count,created_at,content_hash) + '\\n' + body. Deterministic."""
  def write_doc_markdown(markdown_dir: Path, page: dict[str, Any], relates_to: list[dict[str, str]], tags: list[str]) -> Path:
      """Atomic: sibling temp file + os.replace. Sync by design — call via asyncio.to_thread."""
  def write_inbox_index(markdown_dir: Path, store_pages: list[dict[str, Any]]) -> Path:
      """Regenerate markdown_dir/index.md with generate_index()."""

  # packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py  (new)
  def archive_destination(archive_dir: Path, source: Path, *, rejected: bool, rejected_subdir: str,
                          date_format: str, today: date) -> Path:
      """archive_dir[/rejected_subdir]/<stem>.<date>.<ext>; append -1, -2, … before <ext> until free. Never overwrites."""
  def is_git_tracked(root: Path, path: Path) -> bool:
      """`git -C root ls-files --error-unmatch -- <rel>` returncode == 0; False on any OSError."""
  def stage_git_removal(root: Path, path: Path) -> bool:
      """`git -C root rm --cached --quiet -- <rel>` after the move; returns success; never raises."""
  def archive_original(root: Path, source: Path, destination: Path, *, stage_git: bool) -> ArchiveResult:
      """mkdir -p; os.replace else shutil.move; assert destination.exists() before any git call; stage when requested & tracked."""
  def repoint_source(sources: SourceCollectionManager, source_id: str, destination: Path) -> None:
      """sources.update_source_uri(source_id, destination) so the manifest resolves the archived file (S5); logs and
      swallows FileNotFoundError/ValueError (never un-archives)."""
  ```

### Module 7: InboxProcessor
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py`
- **Responsibility**: discovery, ordering, the per-document stage pipeline,
  Fireflies pre-check, failure isolation, dry-run, the run report and the
  bookkeeper run header.
- **Depends on**: M1–M6, `resolve_sources` (`documents.py:166`),
  `DocumentAcquirer` (`documents.py:466`), `IngestTriageRouter`
  (`triage.py:252`), `WikiIngestOrchestrator` (`ingest.py:144`),
  `SourceCollectionManager.find_by_external_id` / `record_document_metadata`
  (`sources.py:822`, `:730`), `WikiBookkeeper.log_operation`
  (`bookkeeper.py:175`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py  (new)
  _FIREFLIES_RE: re.Pattern[str]   # `fireflies[_-]?id:\s*<id>` in frontmatter/body, or `fireflies:<id>` marker

  @dataclass
  class InboxRuntime:
      """Everything the processor needs, built once per run (see cli._build_ingest_runtime)."""
      root: Path; config: WikiProjectConfig; wiki_config: WikiConfig; charter: Charter
      store: BaseWikiStore; sources: SourceCollectionManager; bookkeeper: WikiBookkeeper
      acquirer: DocumentAcquirer; router: IngestTriageRouter; orchestrator: WikiIngestOrchestrator
      light_adapter: PageIndexLLMAdapter; heavy_adapter: PageIndexLLMAdapter; search: WikiCombinedSearch
      models: dict[str, str]

  def detect_fireflies_id(acquired: AcquiredDocument) -> str | None:
      """Return `fireflies:<id>` when the frontmatter mapping or the text carries a Fireflies id; else None."""

  class InboxLockBusy(RuntimeError):
      """Raised by run() when wiki_write_lock cannot be acquired within inbox.lock_timeout (CLI maps it to exit 3)."""

  class InboxProcessor:
      """Autonomous inbox run: acquire → (fireflies) → triage → classify → links → ingest → doc page → markdown → verify → archive."""
      def __init__(self, runtime: InboxRuntime, *, today: date | None = None) -> None:
          """validate_inbox_paths(root, inbox_path, archive_path, markdown_path) runs here (S10) and raises WikiConfigError."""
      def discover(self, *, limit: int | None) -> list[DocumentRef]:
          """resolve_sources(inbox_dir, recursive=True), dotfiles skipped; entries that are symlinks or whose resolved path
          is outside inbox_path.resolve() are dropped and reported as status="skipped" (S10); ordered by (mtime, name);
          truncated to limit."""
      async def run(self, *, dry_run: bool = False, limit: int | None = None, force: bool = False,
                    archive: bool = True) -> InboxRunReport:
          """Hold wiki_write_lock(storage_path, timeout=inbox.lock_timeout) for the whole run (S9) — not acquired →
          InboxLockBusy. Process every discovered document in order; one failure never stops the run; writes INBOX_RUN
          (or DRY_RUN) bookkeeper line; returns the report (report.failed when any status == "failed")."""
      async def process_one(self, ref: DocumentRef, *, dry_run: bool, force: bool, archive: bool) -> InboxDocResult:
          """The per-document pipeline. Invariant: archive_original is called only after verify_persisted() passed
          (admitted/archived_category) or after the orchestrator recorded the rejection (rejected). `force` is forwarded as
          router.triage(path, text, skip_duplicate_check=True) (M10, S7) — size/suffix/sensitive rules still apply."""
      async def verify_persisted(self, source_id: str, doc_id: str, markdown_path: Path, expected_decision: str) -> list[str]:
          """Re-read the store and manifest (S2): get_source(source_id) exists with decision == expected_decision; every id in
          pages_generated resolves via store.get_page(id, include_body=False); get_page(doc_id) resolves; markdown_path.exists().
          Returns the list of problems (empty == verified). Never trusts IngestReport.status alone."""
  ```

### Module 8: CLI command and runtime factoring
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: `wikitoolkit inbox`; extract the adapter / PageIndex
  toolkit / orchestrator construction that `ingest` performs inline
  (`cli.py:4944-4965`) into `_build_ingest_runtime` and make `ingest` call it
  with identical behaviour (existing `ingest` tests are the oracle).
- **Depends on**: M7, existing helpers `_resolve_project` (`cli.py:367`),
  `_open_store` (`:464`), `_open_sources` (`:521`), `_run` (`:560`),
  `_resolve_charter_path` (`:4430`), `_resolve_model_id` (`:4455`),
  `_build_triage_adapters` (`:4477`), `_build_novelty_scorer` (`:4511`).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (insert after `_build_novelty_scorer` verified: cli.py:4511)
  def _build_ingest_runtime(root: Path, config: WikiProjectConfig, store: BaseWikiStore, sources: SourceCollectionManager,
                            charter: Charter, charter_path: Path, *, lightweight_model_opt: str | None, model_opt: str | None,
                            fetch_timeout: float = 30.0) -> "InboxRuntime":
      """Factored from `ingest`: resolve model ids (env fallbacks, PARROT_NO_AUTO_LLM), _build_triage_adapters,
      PageIndexToolkit(heavy_adapter, wiki_dir, lightweight_model=light_model_id if same_provider else None, ...),
      WikiIngestOrchestrator(pi_toolkit, None, sources, WikiBookkeeper(), store=store, sync_graph=config.sync_graph),
      IngestTriageRouter(charter, light_adapter, sources, _build_novelty_scorer(root, config, store), heavy_adapter=heavy_adapter),
      WikiCombinedSearch(None, None, store=store), DocumentAcquirer(fetch_timeout=fetch_timeout), WikiConfig(... charter_path=...).
      Raises click.ClickException when no LLM client can be built."""

  # insert before `@wiki.command(name="ingest-jira")` verified: cli.py:5168
  @wiki.command()
  @click.option("--path", "path_", ...)                 # same shape as `ingest`
  @click.option("--dry-run", is_flag=True)
  @click.option("--limit", type=int, default=None)
  @click.option("--charter", "charter_opt", default=None)
  @click.option("--lightweight-model", "lightweight_model_opt", default=None)
  @click.option("--model", "model_opt", default=None)
  @click.option("--archive/--no-archive", default=True)
  @click.option("--force", is_flag=True)
  @click.option("--json", "as_json", is_flag=True)
  def inbox(path_, dry_run, limit, charter_opt, lightweight_model_opt, model_opt, archive, force, as_json) -> None:
      """Autonomously ingest every document in the configured inbox folder (default `inbox/`): charter triage,
      classification, verified links, doc page, OKF markdown projection, verification, archive of the original.
      Exit 1 when any document failed; exit 2 when the inbox dir does not exist or the path layout is invalid
      (WikiConfigError); exit 3 when the wiki write lock is busy (InboxLockBusy)."""
  ```

### Module 9: Documentation and follow-up ledger item
- **Path**: `docs/guides/llm-wiki-guide.md`, `docs/wiki/cheatsheet.md`
- **Responsibility**: "Inbox ingestion" subsection (command, config keys,
  charter `taxonomy` example, archive layout, dry-run) under "Document
  Ingestion" before the Jira subsection; TOC entry; a one-line cheatsheet
  entry; open the ledger follow-up for the MCP tool.
- **Depends on**: M8 (final option names).
- **Interface Skeleton**: n/a (docs). Ledger command fixed:
  ```bash
  wikitoolkit ledger open --kind tech_debt --severity low \
    --discovered-from spec:FEAT-626 --about file:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py \
    --title "wiki_inbox MCP tool wrapping InboxProcessor (deferred from FEAT-626 — FEAT-569 conflict)" \
    --body "Thin AbstractTool over parrot.knowledge.wiki.inbox.InboxProcessor; dry_run default; register in create_wiki_tools after FEAT-569 merges."
  ```

### Module 10: Triage force seam and frontmatter tags (additive seams in FEAT-402/260 code)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/export.py`
- **Responsibility**: two keyword-only, defaulted parameters whose default
  path is byte-identical to today, so `ingest`, `build` and the memory
  backend are untouched: `--force` can bypass *only* the Stage-0 duplicate
  check (design research S7), and the projection can emit real tags without
  string surgery (S4).
- **Depends on**: existing `IngestTriageRouter.triage` / `_heuristic_reject`
  (`triage.py:304`, `:367`), `page_frontmatter` (`export.py:86`).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
  class IngestTriageRouter:                                   # verified: triage.py:252
      async def triage(self, path: Path, content: str, *, skip_duplicate_check: bool = False) -> ManifestDocEntry:  # verified: triage.py:304
          """Unchanged cascade. skip_duplicate_check=True skips ONLY the two duplicate branches of Stage 0
          (unchanged-since-last-ingest, duplicate-elsewhere); size cap, suffix allowlist, sensitivity and the LLM stages run as before."""
      def _heuristic_reject(self, path: Path, content: str, file_hash: str, *, skip_duplicate_check: bool = False) -> ManifestDocEntry | None:  # verified: triage.py:367

  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/export.py
  def page_frontmatter(page: dict[str, Any], relates_to: list[dict[str, str]], tags: Sequence[str] | None = None) -> str:  # verified: export.py:86
      """tags=None → today's `[category]` (byte-identical); otherwise the given list, deduped, order preserved."""
  ```

---

## 4. Test Specification

All new tests live under `packages/ai-parrot/tests/knowledge/wiki/inbox/`
(the FEAT-402/451 CLI tests live in
`packages/ai-parrot/tests/knowledge/wiki/test_cli.py`; the root `tests/`
tree is legacy). LLM calls are stubbed by monkeypatching
`parrot.knowledge.wiki.cli._build_triage_adapters` (pattern:
`test_cli.py:299-307`) or by passing a fake adapter whose `ask_structured`
returns canned Pydantic instances. No test touches a real provider.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_default_taxonomy_six_kinds` | M1 | `default_taxonomy()` has exactly the six kinds with the decided category mapping and `default_kind == "note"` |
| `test_charter_without_taxonomy_block_still_loads` | M1 | FEAT-402 fixture charter (no `taxonomy:`) → `Charter.taxonomy == default_taxonomy()`; fingerprint identical to pre-change |
| `test_taxonomy_validators` | M1 | duplicate ids, unknown `default_kind`, invalid category → `ValueError` |
| `test_inbox_config_defaults_and_paths` | M2 | defaults; `inbox_path`, `archive_path`, `inbox_markdown_path` (None → `<storage>/inbox`; absolute honoured) |
| `test_env_overlay_merges_inbox` | M2 | overlay with `inbox.dir` only → merged config keeps other defaults (generic merge) |
| `test_normalize_tags` | M3 | case, accents, punctuation, dedupe, cap at `max_tags`, empty dropped |
| `test_slugify_doc_id_stable_and_unique` | M3 | same title+hash → same id; same title, different hash → different id; ≤ 64 chars |
| `test_classify_unknown_kind_falls_back` | M3 | fake adapter returns `kind="poem"` → `default_kind`, `classification_source="fallback"` |
| `test_classify_adapter_failure_raises` | M3 | adapter raises → `InboxClassificationError` |
| `test_candidates_cap_and_exclusion` | M4 | 30 search hits + tags → ≤ 20, own ids excluded, deduped |
| `test_code_pages_only_on_verbatim_mention` | M4 | `sym:`/`file:` hits from search are dropped unless the text names them verbatim |
| `test_select_verifies_ids_and_relations` | M4 | LLM returns one unknown id, one bad rel, two good → only the two good survive; `LINK_DROPPED` logged |
| `test_select_degrades_without_adapter` | M4 | adapter None / raising → `deterministic_links` (verbatim mentions, `references`) |
| `test_write_doc_page_edges` | M5 | doc page upserted with `origin="ingest"`, `asserted_by`, `part_of` edges to `pages_generated`, link edges with provenance `asserted` |
| `test_ensure_tags_idempotent` | M5 | second call creates no duplicate `tag:` pages or edges |
| `test_emit_adr_candidate_only_for_decisions` | M5 | `kind="meeting"` → None; `kind="decision"` → record saved with `origin="inferred"`, `source_status="unknown"`, `external_id="inbox:<doc_id>"` |
| `test_emit_adr_candidate_never_raises` | M5 | repository raising → None + `ADR_CANDIDATE_SKIPPED` |
| `test_render_doc_markdown_deterministic` | M6 | same page → byte-identical output; frontmatter `tags` = `[category, *tags]` |
| `test_write_doc_markdown_atomic_path` | M6 | file at `<md>/<category_dir>/<flat-id>.md`; no `.tmp` left behind |
| `test_archive_destination_collision` | M6 | `a.2026-10-03.md` exists → `a.2026-10-03-1.md`, then `-2` |
| `test_archive_original_git_staging` | M6 | tracked file in a tmp git repo → moved + staged deletion; untracked → `staged_git=False`; git missing → no error |
| `test_processor_order_persist_project_archive` | M7 | markdown write failure → status `failed`, original still in inbox, page exists |
| `test_processor_discard_archives_rejected` | M7 | triage `discard` → no classify/link call, original under `rejected/` |
| `test_processor_duplicate_rejected` | M7 | second drop of identical content → heuristic reject, archived under `rejected/`, no LLM call; `--force` re-ingests |
| `test_processor_fireflies_updates_existing` | M7 | source with `external_id="fireflies:x"` exists → same doc page updated, no second `doc:` page |
| `test_processor_dry_run_writes_nothing` | M7 | store, filesystem, inbox untouched; report populated |
| `test_cli_inbox_options_and_exit_codes` | M8 | missing inbox dir → exit 2; failed doc → exit 1; lock busy → exit 3; `--json` emits `InboxRunReport` |
| `test_ingest_unchanged_after_runtime_factoring` | M8 | existing `ingest` tests in `test_cli.py` pass unchanged (regression oracle) |
| `test_doc_page_survives_reingest` | M5/M7 | re-ingesting the same source (`replace_source_slice`) keeps the `doc:` page and its inbound edges; `part_of` edges are rewritten (S1) |
| `test_verify_persisted_gates_archive` | M7 | orchestrator stub returns `status="ok"` but writes no pages → `verify_persisted` reports problems, status `failed`, original stays (S2) |
| `test_run_holds_write_lock` | M7 | a held `wiki_write_lock` → `InboxLockBusy` after `lock_timeout`; lock released after a normal run (S9) |
| `test_discover_skips_symlinks_and_escapes` | M7 | symlink in inbox and a file resolving outside the inbox → `skipped` rows, never moved or staged (S10) |
| `test_validate_inbox_paths` | M2 | archive inside inbox, inbox outside root, markdown outside root → `WikiConfigError` |
| `test_classify_rejects_malformed_output` | M3 | adapter returns dict / list / None → `InboxClassificationError`, no fallback (S8) |
| `test_select_drops_duplicates_and_self_links` | M4 | duplicate choice and `page_id == doc_id` are removed (S8) |
| `test_emit_adr_candidate_reuses_existing` | M5 | second run with same content → same `decision_id`, `adr_candidate_reused=True`, record untouched (S6) |
| `test_force_skips_only_duplicate_check` | M10 | `skip_duplicate_check=True` passes a duplicate but still rejects oversized/forbidden-suffix input; default path byte-identical to the FEAT-402 fixtures (S7) |
| `test_page_frontmatter_tags_param` | M10 | `tags=None` → identical to current output; `tags=[…]` → given list (S4) |
| `test_archive_repoints_source_uri` | M6/M7 | after archiving, `get_source(id).source_uri` is the archive path and `is_stale` is False; Fireflies hit repoints to the inbox path before ingest (S5) |

### Integration Tests
| Test | Description |
|---|---|
| `test_inbox_end_to_end_sqlite` | tmp repo with `inbox/` (one `.md` meeting, one `.md` decision, one jokes-only note), tmp sqlite store, stub adapters → two doc pages with tags/links/markdown files, one ADR candidate, one `rejected/` archive, inbox empty, `related doc:<id>` reaches `tag:` and `part_of` neighbours |
| `test_inbox_rerun_is_idempotent` | second run on an empty inbox is a no-op; re-dropping an archived original is rejected as duplicate |

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/knowledge/wiki/inbox/conftest.py
@pytest.fixture
def tmp_repo(tmp_path) -> Path:          # git init + inbox/ + .parrot/wiki.json (sqlite) + .parrot/charter.yaml (FEAT-402 fixture + taxonomy)
@pytest.fixture
def fake_adapters(monkeypatch):          # patches cli._build_triage_adapters (pattern test_cli.py:299) with adapters whose
                                         # ask_structured returns TriageOutput / InboxClassification / LinkSelection by output_type
@pytest.fixture
def seeded_store(tmp_repo):              # sqlite store with a few file:/sym:/mem- pages to link against
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1** `wikitoolkit inbox` with no flags processes every document under the configured inbox dir (default `inbox/`), recursive, dotfiles skipped, and exits 0 on a clean run; exit 2 when the dir is missing; exit 1 when any document `failed`.
- [ ] **AC2** `wikitoolkit build`, `upsert`, `ingest` and the git hook are byte-identical: all pre-existing wiki tests pass unchanged, and `ingest`'s refactor to `_build_ingest_runtime` changes no option, output or persisted field.
- [ ] **AC3** A charter without a `taxonomy:` block loads with the six-kind default and an unchanged fingerprint; a charter with the block validates ids, categories and `default_kind`.
- [ ] **AC4** Classification is a separate `ask_structured` call returning `InboxClassification`; an unknown kind resolves to `default_kind` with `classification_source="fallback"`; tags are kebab-case, deduped, ≤ `max_tags`.
- [ ] **AC5** Link candidates ≤ `inbox.max_candidates` (20 default); `sym:`/`file:` pages are candidates only on verbatim mention; every emitted edge targets an id `store.get_page` returns; relation ∈ {`references`, `relates_to`, `mentions`, `follows_up`, `supersedes`}; LLM failure degrades to verbatim-mention `references` links.
- [ ] **AC6** Each admitted document yields exactly one `doc:<slug>` page (`origin="authored"`, `source_id=None`, `asserted_by="agent:wikitoolkit-inbox"`, source identity in frontmatter), `part_of` edges from every page in `pages_generated`, asserted link edges, and `tag:<slug>` pages with `tagged` edges; the orchestrator's pages are not modified; re-ingesting the same source keeps the doc page and its inbound edges.
- [ ] **AC7** A `decision`-kind document saves one `DecisionRecord` with a deterministic `decision_id`, `origin="inferred"`, `source_status="unknown"`, `review_status="unreviewed"`, `external_id="inbox:<doc_id>"` and one `kind="document"` evidence ref; an existing record with that id is reused, never overwritten; a repository failure logs `ADR_CANDIDATE_SKIPPED` and does not fail the document.
- [ ] **AC8** The doc page is projected to `<markdown_dir>/<category-plural>/<flat-id>.md` (default `<storage_dir>/inbox/`), deterministic, written atomically, with frontmatter `tags = [category, *tags]` via the new `page_frontmatter(tags=)` parameter and `index.md` regenerated; `build` does not rescan it; `page_frontmatter` without `tags` is byte-identical to today.
- [ ] **AC9** Originals are archived as `<archive_dir>[/rejected]/<stem>.<YYYY-MM-DD>.<ext>` with `-N` collision suffixes, never overwritten; discards and Stage-0 duplicates go under `rejected/`; a tracked original has its deletion staged via `git rm --cached` when `stage_git` is true; the command never commits.
- [ ] **AC10** Crash-safety: a failure in classify, ingest, doc page, markdown or verification leaves the original in the inbox and archives nothing for it; re-running does not duplicate pages; on the `sqlite` backend the slice replacement is transactional, on `memory`/`arangodb` it is documented as best-effort; `--dry-run` performs no write, move or bookkeeper mutation other than `DRY_RUN`.
- [ ] **AC11** A document carrying a Fireflies id whose `fireflies:<id>` source exists updates that source and its doc page instead of creating a second doc page.
- [ ] **AC12** `archived_to`/`archived_at` are persisted in the source's `doc_metadata.extra`; bookkeeper lines `TRIAGE`, `CLASSIFY`, `DOC_PAGE`, `ARCHIVE_ORIGINAL`, `INBOX_RUN` (or `DRY_RUN`) are written.
- [ ] **AC13** No `tools.py` / `mcp_server.py` change; the MCP follow-up is recorded in the work ledger.
- [ ] **AC14** Docs: `docs/guides/llm-wiki-guide.md` gains an "Inbox ingestion" subsection + TOC entry; `docs/wiki/cheatsheet.md` gains one line.
- [ ] **AC15** `ruff check` clean on every touched file; new tests pass under `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/wiki/inbox -q`.
- [ ] **AC16** Archiving is gated by `verify_persisted`: the source entry, every `pages_generated` id, the doc page and the markdown file are re-read from the store/filesystem; an `IngestReport` with `status="ok"` but missing pages yields `failed` and no move.
- [ ] **AC17** The whole run holds `wiki_write_lock(storage_path, timeout=inbox.lock_timeout)`; a busy lock exits 3 with a clear message; the lock is released on every exit path.
- [ ] **AC18** Inbox, archive and markdown dirs must resolve inside the repository root and must not nest in one another (`WikiConfigError`, exit 2); symlinked entries and files resolving outside the inbox are reported as `skipped` and never moved or staged.
- [ ] **AC19** `--force` is implemented as `IngestTriageRouter.triage(..., skip_duplicate_check=True)`: it bypasses only the duplicate check; size, suffix, sensitivity and the LLM stages still apply; the default path is byte-identical to FEAT-402.
- [ ] **AC20** Malformed structured output (not an `InboxClassification` / `LinkSelection` instance) fails closed: classification marks the document `failed`; link selection degrades to deterministic links; `default_kind` fallback applies only to an explicit unknown kind.
- [ ] **AC21** After archiving, `update_source_uri(source_id, destination)` repoints the manifest to the archived file (`is_stale` False); a Fireflies hit repoints the existing source to the inbox path before ingest so no second source or doc page is created.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against commit `7b4473649` (dev, 2026-10-03). Line numbers below were
> re-checked at spec time; `/sdd-task` must re-run `grep -c` on every anchor.

### Verified Imports
```python
from parrot.knowledge.wiki.documents import (                     # documents.py L69-294
    AcquiredDocument, DocumentAcquirer, DocumentAcquisitionError, DocumentMetadata, DocumentRef,
    TriageProvenance, render_frontmatter, resolve_sources, split_frontmatter,
)
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer   # triage.py L252, L67
from parrot.knowledge.wiki.charter import Charter, load_charter             # charter.py L208, L303
from parrot.knowledge.wiki.review import Claim, ManifestDocEntry, TriageOutput  # review.py L74, L135, L88
from parrot.knowledge.wiki.ingest import IngestReport, WikiIngestOrchestrator   # ingest.py L120, L144
from parrot.knowledge.wiki.sources import SourceCollectionManager           # sources.py L108
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens, create_wiki_store  # store.py L525, L409, L318, L2376
from parrot.knowledge.wiki.search import WikiCombinedSearch                 # search.py L32
from parrot.knowledge.wiki.export import category_dir, generate_index, okf_type, page_frontmatter  # export.py L76, L109, L71, L86
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename      # okf/utils.py L18
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                 # bookkeeper.py L31
from parrot.knowledge.wiki.models import SourceManifestEntry, WikiConfig, WikiPageCategory, WikiSearchResult  # models.py L155, L52, L25, L258
from parrot.knowledge.wiki.project import PARROT_DIR, WikiConfigError, WikiEnvOverlay, WikiProjectConfig, wiki_write_lock  # project.py L43, L768, L816, L382, L74
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter      # llm_adapter.py L42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit             # toolkit.py L92 (__init__) — import lazily, as cli.ingest does
# lazy, inside emit_adr_candidate only:
from parrot.knowledge.wiki.decisions.models import DecisionRecord, EvidenceRef   # decisions/models.py L143, L78
from parrot.knowledge.wiki.decisions.repository import DecisionRepository        # decisions/repository.py L26
from parrot.knowledge.wiki.decisions.codec import candidate_decision_id          # decisions/codec.py L109
from parrot.knowledge.wiki.decisions.generation import PROMPT_VERSION            # decisions/generation.py L50
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py
class DocumentRef(BaseModel): uri: str; is_url: bool = False; suffix: str = ""                      # L69
class DocumentMetadata(BaseModel):                                                                   # L83
    title, author, created_at, modified_at: str | None; page_count, word_count: int | None
    language, content_type, source_url, loader: str | None; extra: dict[str, Any] = {}             # L116
class AcquiredDocument(BaseModel): ref: DocumentRef; text: str; metadata: DocumentMetadata; ebook_sections: list[dict] = []  # L119
class TriageProvenance(BaseModel): composite_score: float | None; decision: str | None; decision_source: str | None; charter_version: str | None  # L136
def resolve_sources(source: str, *, recursive: bool = True) -> list[DocumentRef]                    # L166
def render_frontmatter(metadata: DocumentMetadata, provenance: TriageProvenance | None = None) -> str  # L221
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]                                      # L265
class DocumentAcquirer:                                                                              # L466
    def __init__(self, *, fetch_timeout: float = 30.0, max_bytes: int = 100 * 1024 * 1024, cache_dir: Path | None = None)  # L481
    async def acquire(self, ref: DocumentRef) -> AcquiredDocument                                   # L500

# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
class NoveltyScorer: def __init__(self, grounding_evaluator=None, search: WikiCombinedSearch | None = None, max_claims: int = ...)  # L88
class IngestTriageRouter:                                                                            # L252
    def __init__(self, charter: Charter, adapter: PageIndexLLMAdapter, sources: SourceCollectionManager,
                 novelty_scorer: NoveltyScorer, *, heavy_adapter: PageIndexLLMAdapter | None = None,
                 max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES, allowed_suffixes: frozenset[str] | None = None)  # L271
    async def triage(self, path: Path, content: str) -> ManifestDocEntry                            # L304 (no force/skip kwarg today)
        # L313 file_hash = self._hash_content(content); L318 heuristic_entry = self._heuristic_reject(path, content, file_hash)
    def _heuristic_reject(self, path: Path, content: str, file_hash: str) -> ManifestDocEntry | None  # L367 — size cap, suffix allowlist,
        # then duplicate (find_by_uri + hash, and duplicate-elsewhere by hash); unconditional today
    # Stage-0 duplicate: briefing "Rejected by heuristic: duplicate: unchanged since last ingest",
    # proposed_action="discard", decision_source="heuristic"                                         # L406-422

# packages/ai-parrot/src/parrot/knowledge/wiki/charter.py
class Charter(BaseModel):                                                                            # L208
    version: str; scope: CharterScope; weights: dict[str, float]; thresholds: Thresholds; destinations: list[str]
    calibration: CalibrationPolicy; examples: list[TriageExample]; examples_file: Path | None
    amendments: list[Amendment] = Field(default_factory=list)                                       # L241
    fingerprint: str = Field(...)                                                                    # L242
def load_charter(path: Path) -> Charter                                                              # L303

# packages/ai-parrot/src/parrot/knowledge/wiki/review.py
class Claim(BaseModel): text: str; grounded: bool | None = None                                     # L74
class TriageOutput(BaseModel): briefing: str; scores: DimensionScores; claims: list[Claim]; sensitive: bool; category_hint: str | None  # L88 (category_hint has no consumer)
class ManifestDocEntry(BaseModel):                                                                   # L135
    source_uri: str; file_hash: str; briefing: str; scores: DimensionScores; composite: float
    proposed_action: Literal["admit","archive","discard"]; claims: list[Claim]
    decision: Literal["admit","archive","discard"] | None; decision_source: Literal["heuristic","model","human","auto"] | None
    audit_sample: bool = False; audit_stratum: str | None = None

# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py
class IngestReport(BaseModel): source_id: str; source_uri: str; pages_created: int; pages_updated: int; graph_nodes_created: int; duration_ms: float; status: str = "ok"; error: str | None  # L120 — NO page ids
class WikiIngestOrchestrator:                                                                        # L144
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any, source_manager: SourceCollectionManager,
                 bookkeeper: WikiBookkeeper, store: Optional[BaseWikiStore] = None, sync_graph: bool = False)  # L164
    async def ingest(self, source_path: str, wiki_config: WikiConfig, *, triage: Optional[ManifestDocEntry] = None,
                     charter_version: Optional[str] = None, acquired: AcquiredDocument | None = None) -> IngestReport  # L198
    # frontmatter rendered only when triage is given (L397-400); "archive" forces category ARCHIVE; "discard" → _record_discard (L703)
    # resolves the source by URI (find_by_uri L316) and add_source()s a NEW entry for an unknown path (L335) — repoint first for Fireflies
    # store-sync (L436-454), manifest (L490-501) and bookkeeping (L527-529) failures are logged as warnings; status stays "ok" (L546)

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                                                                       # L108
    def get_source(self, source_id: str) -> SourceManifestEntry | None                              # L514
    def record_decision(self, path: Path, *, destination: str, decision_source=None, charter_version=None,
                        composite_score=None, pages_generated=None, status=None, external_id=None) -> SourceManifestEntry  # L631
    def record_document_metadata(self, source_id: str, *, doc_metadata: dict[str, Any] | None, content_type: str | None, loader: str | None) -> None  # L730
    def find_by_uri(self, source_uri: str) -> str | None                                             # L807
    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None                   # L822
    def set_external_id(self, source_id: str, external_id: str | None) -> SourceManifestEntry | None  # L927
    def update_source_uri(self, source_id: str, new_uri: Path | str) -> SourceManifestEntry | None  # L948 — keeps source_id/external_id,
        # updates source_uri/file_hash/mtime; raises FileNotFoundError when new_uri does not exist, ValueError on URI ownership conflict
    # external_id convention "<source>:<id>" (L122), e.g. "fireflies:abc123"

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiPageCategory(str, Enum): SUMMARY ENTITY CONCEPT COMPARISON OVERVIEW SYNTHESIS ANSWER ARCHIVE   # L25
class WikiConfig(BaseModel): wiki_name: str; storage_dir: Path; source_dir; page_categories; search_weights;
    lightweight_model: str | None; model: str | None; sync_graph: bool; storage_backend: Literal[...]; charter_path: Path | None  # L52-132
class SourceManifestEntry(BaseModel): ... pages_generated: list[str]                                 # L155, L205
class WikiSearchResult(BaseModel): node_id: str; title: str; score: float; source: str; token_count: int | None; snippet: str; category: WikiPageCategory | None  # L258

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def estimate_tokens(text: str) -> int                                                                # L318
class WikiPageRecord(BaseModel): concept_id: str; node_id: Optional[str]; title: str = ""; category: str = "concept"; summary: str = ""; body: str = "";
    source_id: Optional[str]; token_count: int = 0; origin: str = "ingest"; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str]  # L409 — NO tags
class BaseWikiStore(ABC):                                                                            # L525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                                # L544
    async def add_edges(self, edges: list[tuple]) -> int   # (src, dst, rel[, provenance]); default provenance "extracted"  # L547 / L1643
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges=None) -> dict  # L550 / impl L1664:
        # deletes `pages WHERE source_id = ?` and every edge whose src OR dst is one of them; re-inserts incoming edges only for
        # concept_ids present in the replacement set; ONE `_write` transaction on sqlite (L1696) — the doc page must NOT share source_id
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]  # L565
    async def list_pages(self, category: Optional[str] = None, limit: int = 100, origin: Optional[list[str]] = None) -> list[dict]  # L568
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]  # L576
def create_wiki_store(...)                                                                           # L2376

# packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                                                                            # L32
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any, default_weights=None, store: Optional[BaseWikiStore] = None, embedder=None, normalize_store_rows: bool = True)  # L47
    async def search(self, query: str, mode: str = "combined", top_k: int = 10, tree_name=None, weights=None, include_archived: bool = False) -> list[WikiSearchResult]  # L91
    # store-only construction used by the CLI: WikiCombinedSearch(None, None, store=store)          # cli.py ~L4535
    # _store_row_to_wiki coerces an unknown category string to None (try WikiPageCategory(raw) except ValueError) — "tag"/"doc" pages are safe  # L265-269

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py (lock)
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]   # L74 — advisory flock context manager; yields whether acquired;
    # used by build (cli.py L1538) and upsert (cli.py L1813, timeout=UPSERT_LOCK_WAIT_SECONDS)
class WikiConfigError(ValueError)                                                                    # L768

# packages/ai-parrot/src/parrot/knowledge/wiki/export.py
def okf_type(category: str) -> str   # CATEGORY_TO_OKF_TYPE.get(category, category.title() or "Other")  # L71
def category_dir(category: str) -> str   # naive plural                                              # L76
def page_frontmatter(page: dict[str, Any], relates_to: list[dict[str, str]]) -> str   # tags=[category] hard-coded at L95; no tags kwarg today  # L86
def generate_index(wiki_name: str, entries: list[tuple[str, str, str]]) -> str                        # L109
# file_store.py (memory backend, PRIVATE — mirror, do not import): _page_path L209, _render_page_file L215, _write_page_file_atomic L241

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
PARROT_DIR = ".parrot"                                                                               # L43
class ObsidianSyncConfig(BaseModel)                                                                  # L283
class WikiProjectConfig(BaseModel):  ... sqlite_performance_pragmas: bool = Field(...)               # L382, L509
    def storage_path(self, root: Path) -> Path                                                       # L555
    def db_path(self, root: Path) -> Path                                                            # L560
class WikiEnvOverlay(BaseModel): ... claude: ClaudeIntegrationConfig | None = None                  # L816, L864
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig   # merges every non-None overlay field generically  # L933, L977-981

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:
    async def ask_structured(self, prompt: str, output_type: type, temperature: float = 0.0, system_prompt: Optional[str] = None) -> Any  # L99
    # may return: an output_type instance; output_type.model_validate(dict); a raw list; or the raw parsed value (L125-150) → callers must isinstance-check

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit: def __init__(self, adapter: PageIndexLLMAdapter, storage_dir: str | Path, reranker=None, lightweight_model: Optional[str] = None, model: Optional[str] = None, ...)  # L92

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]                             # L367
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore                              # L464
def _open_sources(root, config, store=...)                                                           # L521
def _run(coro: Any) -> Any                                                                           # L560
def _env_setting(name: str) -> str | None                                                            # L565
def _authoring_identity(by: str | None) -> str                                                       # L3513
def _resolve_charter_path(root: Path, charter_opt: str | None) -> Path                               # L4430 (default <root>/.parrot/charter.yaml L4449)
def _resolve_model_id(cli_value: str | None, env_name: str) -> str                                   # L4455
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]         # L4477 (test seam)
def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any        # L4511
@wiki.command() def ingest(...)                                                                      # L4701 / L4794
    pi_toolkit = PageIndexToolkit(                                                                   # L4944
    orch = WikiIngestOrchestrator(                                                                   # L4957
@wiki.command(name="ingest-jira") def ingest_jira(...)                                               # L5168 / L5249
# git shell-out pattern: subprocess.run(["git", "-C", str(root), ...])                              # L3192 (import subprocess L34)

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/
class EvidenceRef(_Strict): page_id: str; rel_path: str; start_line: int (ge=1); end_line: int (ge=1); excerpt: str = ""; kind: Literal["adr","code","comment","document"]  # models.py L78
class DecisionRecord(_Strict): decision_id: str; revision: int = 1; title: str; context: str; decision: str (min_length=1); consequences: str;
    source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"] = "unknown"; origin: Literal["documented","inferred"];
    review_status: Literal["unreviewed","accepted","rejected"] = "unreviewed"; source_path: str | None; external_id: str | None;
    evidence: list[EvidenceRef]; links: list[DecisionLink]; observations: list[str]; hypotheses: list[str]; ...   # models.py L143
    # validator L170: origin="inferred" REQUIRES source_status="unknown"
class DecisionRepository: def __init__(self, store: BaseWikiStore, max_records: int = 10_000)        # repository.py L26
    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None               # L45
    async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord  # L96 — None = INSERT that must not exist;
        # raises DecisionError(ADR_REVISION_CONFLICT) when the page already exists (compare_and_swap_page) → call get() first and reuse
def candidate_decision_id(scope_id: str, evidence_fingerprint: str, prompt_version: int, decision_text: str) -> str  # codec.py L109
PROMPT_VERSION = 1                                                                                   # generation.py L50
# DecisionConfig.enabled / max_records on WikiProjectConfig.decisions (cli.py L896 checks `config.decisions.enabled`)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InboxProcessor.process_one` | `DocumentAcquirer.acquire()` | await | `documents.py:500` |
| `InboxProcessor.process_one` | `IngestTriageRouter.triage(path, text)` | await | `triage.py:304` |
| `InboxProcessor.process_one` | `WikiIngestOrchestrator.ingest(path, wiki_config, triage=, charter_version=, acquired=)` | await | `ingest.py:198` |
| `InboxProcessor.process_one` | `SourceCollectionManager.find_by_external_id("fireflies:<id>")` | sync call | `sources.py:822` |
| `InboxProcessor.process_one` | `SourceCollectionManager.record_document_metadata(source_id, doc_metadata=…extra.archived_to…)` | sync call | `sources.py:730` |
| `InboxClassifier.classify` / `LinkProposer.select` | `PageIndexLLMAdapter.ask_structured(prompt, Model)` | await | `llm_adapter.py:99` |
| `LinkProposer.candidates` | `WikiCombinedSearch.search(query, top_k=, include_archived=False)` · `BaseWikiStore.search_fts(tag)` | await | `search.py:91` · `store.py:576` |
| `LinkProposer.select` | `BaseWikiStore.get_page(id, include_body=False)` | await | `store.py:565` |
| `DocPageWriter.write_doc_page` | `BaseWikiStore.upsert_pages([WikiPageRecord])` · `add_edges([(src,dst,rel,"asserted")])` · `SourceCollectionManager.get_source(source_id).pages_generated` | await / sync | `store.py:544`, `:547` · `sources.py:514`, `models.py:205` |
| `DocPageWriter.emit_adr_candidate` | `DecisionRepository(store, max_records=config.decisions.max_records).save(record, None)` | await (lazy import) | `repository.py:29`, `:96` |
| `render_doc_markdown` | `page_frontmatter(page, relates_to)` · `category_dir` · `flatten_concept_id_for_filename` | call | `export.py:86`, `:76` · `okf/utils.py:18` |
| `archive_original` | `subprocess.run(["git","-C",root,"rm","--cached","--quiet","--",rel])` | subprocess | pattern `cli.py:3192` |
| `cli.inbox` | `_resolve_project`, `_open_store`, `_open_sources`, `_resolve_charter_path`, `load_charter`, `_build_ingest_runtime`, `_run` | calls | `cli.py:367`, `:464`, `:521`, `:4430`, `charter.py:303` |
| `cli._build_ingest_runtime` | `_resolve_model_id`, `_build_triage_adapters`, `_build_novelty_scorer`, `PageIndexToolkit(...)`, `WikiIngestOrchestrator(...)` | calls (moved from `ingest` body) | `cli.py:4455`, `:4477`, `:4511`, `:4944`, `:4957` |
| `InboxProcessor.run` | `wiki_write_lock(storage_path, timeout=inbox.lock_timeout)` | context manager | `project.py:74` (pattern `cli.py:1813`) |
| `InboxProcessor.process_one` (force) | `IngestTriageRouter.triage(path, text, skip_duplicate_check=True)` | await (new kwarg, M10) | `triage.py:304`, `:318`, `:367` |
| `InboxProcessor.verify_persisted` | `SourceCollectionManager.get_source` · `BaseWikiStore.get_page` · `Path.exists` | re-read after ingest | `sources.py:514` · `store.py:565` |
| `repoint_source` / Fireflies pre-check | `SourceCollectionManager.update_source_uri(source_id, path)` | sync call | `sources.py:948` |
| `DocPageWriter.emit_adr_candidate` | `DecisionRepository.get(decision_id)` before `save(record, None)` | await (lazy import) | `repository.py:45`, `:96` |
| `render_doc_markdown` | `page_frontmatter(page, relates_to, tags=[...])` | call (new kwarg, M10) | `export.py:86` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/knowledge/wiki/inbox/`~~ (package), ~~`inbox.py`~~, ~~`archive.py`~~, ~~`classify.py`~~ at the `wiki/` level — none exist; this feature creates the `inbox/` package.
- ~~`wikitoolkit inbox`~~ command — does not exist yet. ~~`wiki_inbox`~~ MCP tool — does not exist and is **not** in scope.
- ~~`WikiProjectConfig.inbox`~~, ~~`.inbox_path()`~~, ~~`.archive_path()`~~, ~~`.inbox_markdown_path()`~~ — created by M2.
- ~~`Charter.taxonomy`~~, ~~`Taxonomy`~~, ~~`TaxonomyKind`~~, ~~`default_taxonomy`~~ — created by M1.
- ~~`WikiPageRecord.tags`~~ — no tags column anywhere; `page_frontmatter` emits `tags=[category]`.
- ~~`IngestReport.pages_generated`~~ / ~~`.page_ids`~~ — counts only; ids come from `SourceManifestEntry.pages_generated`.
- ~~`BaseWikiStore.list_pages(source_id=...)`~~ — `list_pages` filters by `category`/`origin`/`limit` only.
- ~~`WikiIngestOrchestrator.ingest(category=..., tags=...)`~~ — no such parameters.
- ~~`candidate_decision_id` in `decisions/generation.py` or `decisions/models.py`~~ — it lives in `decisions/codec.py:109` (the brainstorm's location was wrong).
- ~~`decisions.__init__` exporting `DecisionRepository` / `candidate_decision_id`~~ — `__all__` (`decisions/__init__.py:51-67`) exports neither; import from the submodules.
- ~~`SQLiteFileStore` public render API~~ — `_page_path` / `_render_page_file` / `_write_page_file_atomic` are private; mirror them.
- ~~`doc:` / `tag:` concept-id prefixes, `part_of` / `tagged` relations~~ — none exist today; introduced here.
- ~~`WikiSearchResult.concept_id` / `.page_id`~~ — the id field is `node_id` (`models.py:258`).
- ~~`IngestTriageRouter.triage(..., force=…)` / `skip_duplicate_check`~~ — no such kwarg today (`triage.py:304`); M10 adds `skip_duplicate_check`.
- ~~`page_frontmatter(..., tags=…)`~~ — no such parameter today (`export.py:86`); M10 adds it.
- ~~`DecisionRepository.upsert()` / `save_or_reuse()`~~ — only `get` and insert-only/CAS `save` exist (`repository.py:45`, `:96`).
- ~~`InboxProcessor` trusting `IngestReport.status`~~ — the orchestrator returns `"ok"` after swallowed store/manifest failures (`ingest.py:436-546`); verification must re-read the store.
- ~~`SourceCollectionManager.move_source()` / `rename_source()`~~ — the repoint API is `update_source_uri` (`sources.py:948`).
- ~~`wiki_write_lock` as a decorator or an async context manager~~ — it is a sync `@contextmanager` yielding a bool (`project.py:74`); use `with` and `asyncio.to_thread`-free code around it (hold it in the CLI thread for the whole `_run(...)`).
- ~~a tracked `.parrot/wiki.json`~~ — only `.parrot/wiki.local.json` is tracked; config defaults carry the feature, no repo config edit is required.
- ~~`inbox/`~~ and ~~`.parrot/archive/`~~ directories — absent today.
- ~~`--watch`, daemon, default git hook, `--commit`~~ — excluded by decision.

### Edit Sites (Blueprint Anchors)

Verified against: `7b4473649`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py` | MODIFY (insert `TaxonomyKind`, `Taxonomy`, `default_taxonomy` before) | `class Charter(BaseModel):` | `charter.py:208` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py` | MODIFY (add `taxonomy` field after) | `    amendments: list[Amendment] = Field(default_factory=list)` | `charter.py:241` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY (insert `InboxConfig` before) | `class ObsidianSyncConfig(BaseModel):` | `project.py:283` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY (add `inbox` field AFTER the closing paren of this multi-line `Field(`) | `    sqlite_performance_pragmas: bool = Field(` | `project.py:509` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY (add `inbox_path`/`archive_path`/`inbox_markdown_path` after) | `    def db_path(self, root: Path) -> Path:` | `project.py:560` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY (add overlay `inbox` field after) | `    claude: ClaudeIntegrationConfig | None = None` | `project.py:864` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (insert `_build_ingest_runtime` after this function) | `def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:` | `cli.py:4511` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (replace inline construction with the helper call) | `    pi_toolkit = PageIndexToolkit(` | `cli.py:4944` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (same block) | `    orch = WikiIngestOrchestrator(` | `cli.py:4957` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (insert the `inbox` command before) | `@wiki.command(name="ingest-jira")` | `cli.py:5168` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | MODIFY (add `*, skip_duplicate_check: bool = False`) | `    async def triage(self, path: Path, content: str) -> ManifestDocEntry:` | `triage.py:304` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | MODIFY (forward the kwarg) | `        heuristic_entry = self._heuristic_reject(path, content, file_hash)` | `triage.py:318` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | MODIFY (accept the kwarg; guard the two duplicate branches only) | `    def _heuristic_reject(` | `triage.py:367` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/export.py` | MODIFY (add `tags: Sequence[str] | None = None`; `"tags": list(tags) if tags is not None else [category]`) | `def page_frontmatter(` | `export.py:86` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/` (`conftest.py`, `test_taxonomy.py`, `test_inbox_config.py`, `test_classify.py`, `test_links.py`, `test_pages.py`, `test_projection.py`, `test_archive.py`, `test_processor.py`, `test_cli_inbox.py`, `test_end_to_end.py`) | CREATE | — | — | — |
| `docs/guides/llm-wiki-guide.md` | MODIFY (TOC entry before) | `  - [Jira Ticket Extraction (wikitoolkit ingest-jira)](#jira-ticket-extraction-wikitoolkit-ingest-jira)` | `llm-wiki-guide.md:50` | 1 |
| `docs/guides/llm-wiki-guide.md` | MODIFY (insert subsection before) | `### Jira Ticket Extraction (wikitoolkit ingest-jira)` | `llm-wiki-guide.md:1015` | 1 |
| `docs/wiki/cheatsheet.md` | MODIFY (add one line after) | `wikitoolkit upsert path/a/archivo.py path/b/otro.py   # re-ingesta puntual` | `cheatsheet.md:48` | 1 |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks.

### Patterns to Follow
- **Package, not a single file.** The brainstorm sketched `inbox.py`; the
  spec splits it into `inbox/{models,classify,links,pages,projection,archive,processor}.py`
  so M3–M7 can be implemented concurrently (precedent: `wiki/decisions/`,
  `wiki/claude_code/`). `inbox/__init__.py` re-exports `InboxProcessor`,
  `InboxRuntime`, `InboxRunReport`, `InboxDocResult`.
- **Lazy heavy imports** inside the CLI command body and inside
  `emit_adr_candidate` (`decisions/`), the way `ingest` imports its pipeline
  (`cli.py:4847-4862`) and `LazyAdrGroup` defers `decisions.cli`. The
  `claude-hook` fast path must not get slower.
- **Code decides, the model fills forms.** Every LLM output is a Pydantic
  model; category comes from the taxonomy mapping, never from the model;
  link ids are filtered to the candidate set and re-verified; tags are
  normalized in code.
- **Provenance.** All inbox-written edges carry provenance `"asserted"`
  (as `remember` does, `cli.py:3877`); pages carry
  `asserted_by="agent:wikitoolkit-inbox"`; the ADR record carries
  `external_id="inbox:<doc_id>"`.
- **Deterministic rendering.** `render_doc_markdown` mirrors
  `_render_page_file` (frontmatter → machine block → body) and must be
  byte-stable for the same page; the `tags` list is `[category, *tags]`.
- **Sync filesystem work off the loop** via `asyncio.to_thread` (archive
  move, markdown write, git calls), matching `_write_page_file_atomic`'s
  "sync by design" contract.
- **Bookkeeper vocabulary** (new operation names): `CLASSIFY`,
  `LINK_DROPPED`, `DOC_PAGE`, `TAGGED`, `ADR_CANDIDATE`,
  `ADR_CANDIDATE_SKIPPED`, `ARCHIVE_ORIGINAL`, `INBOX_RUN`, `DRY_RUN`;
  existing `TRIAGE`/`ADMIT`/`ARCHIVE`/`DISCARD` lines keep coming from the
  router/orchestrator.
- **`force` semantics (M10, design research S7).** The Stage-0 duplicate
  check (`find_by_uri` + `file_hash`, `triage.py:367-404`) is unconditional
  today, so `--force` cannot be implemented above the router without either
  failing to bypass it or bypassing the whole policy. The router gains a
  keyword-only `skip_duplicate_check=False` on `triage()` forwarded to
  `_heuristic_reject`; it guards **only** the two duplicate branches. Size
  cap, suffix allowlist, sensitivity and both LLM stages still run.
- **Doc page identity vs. source slice (S1).** The doc page is
  `origin="authored"`, `source_id=None`. Never give it the orchestrator's
  `source_id`: `replace_source_slice` would delete it (and every edge
  touching it) on the next re-ingest of that source.
- **Verify before archive (S2).** `IngestReport.status == "ok"` is not
  evidence of persistence; `verify_persisted` re-reads the manifest entry,
  the child pages, the doc page and the markdown file.
- **Whole-run write lock (S9).** `with wiki_write_lock(storage_path,
  timeout=config.inbox.lock_timeout) as acquired:` wraps `_run(processor.run(...))`
  in the CLI thread, exactly like `upsert` (`cli.py:1813`); not acquired →
  `InboxLockBusy` → exit 3. LLM calls happen under the lock by design
  (human-paced runs; removes the double-triage race).
- **Path safety (S10).** `validate_inbox_paths` runs in
  `InboxProcessor.__init__`; `discover` drops symlinks and escapes. Never
  move or stage a file whose resolved path is outside the inbox dir.
- **Source repointing (S5).** Fireflies hit → `update_source_uri(existing, inbox_path)`
  before `ingest()`; every archived source → `update_source_uri(source_id, destination)`
  after the move (the file must exist at the destination first).
- **ADR reuse (S6).** `DecisionRepository.get(decision_id)` before
  `save(record, None)`; an existing record is reused, never overwritten.
- **Fail closed on structured output (S8).** `isinstance(result, Model)` or
  treat as failure; fallback to `default_kind` only for an explicit unknown
  kind.
- **Conventions**: aiohttp only (no new HTTP), Pydantic v2, `self.logger`,
  Google docstrings, strict typing, `black` 120 / `ruff`; tests under
  `packages/ai-parrot/tests/`; run with `PYTHONPATH=packages/ai-parrot/src`
  inside a worktree.

### Known Risks / Gotchas
- **Shared `cli.py` with FEAT-569** (in progress): M8 touches `cli.py` and
  M2 touches `project.py`, both also edited by FEAT-569. Order M2/M8 last in
  the task graph and rebase on `dev` if FEAT-569 lands first. `tools.py` /
  `mcp_server.py` are not touched (MCP tool deferred).
- **Crash consistency is backend-dependent (S3).** Only the `sqlite` backend
  replaces a source slice in one transaction (`store.py:1696`); the `memory`
  backend deletes/writes files step by step and `arangodb` issues separate
  delete/upsert calls. The persist → project → verify → archive ordering
  holds on every backend, but a crash *inside* a slice write on those two
  backends may leave a partial slice until the next run re-ingests the file
  (which is still in the inbox). Documented; no recovery journal in v1.
- **Additive seams in FEAT-402/260 code (M10).** `triage.py` and
  `export.py` each gain one defaulted kwarg. The FEAT-402 triage tests and
  the memory-backend/export tests are the byte-identity oracle; run them in
  the M10 task.
- **Fireflies overlap with FEAT-481** (in progress): both produce meeting
  pages. The pre-check uses the `fireflies:<id>` external id; if FEAT-481's
  final id format differs, adjust `_FIREFLIES_RE` in M7 only.
- **Multi-line `Field(` anchor** in `project.py:509`: the `inbox` field must
  be inserted after the closing parenthesis, not after the anchor line.
- **`IngestReport` has no page ids**: read `get_source(source_id).pages_generated`
  right after `ingest()`; an empty list (orchestrator produced no pages)
  still yields a doc page with no `part_of` edges.
- **Inferred decisions must keep `source_status="unknown"`**
  (`decisions/models.py:170`) or validation fails; `candidate_decision_id`
  is in `codec.py`, not `generation.py`.
- **Charter fingerprint**: adding a `taxonomy:` block to a charter changes
  its fingerprint — expected and desirable (decisions are versioned by
  charter); a charter *without* the block keeps its old fingerprint because
  the default is applied in code, not in the YAML.
- **`build` must never rescan the projection**: the repo config excludes
  `.parrot/wiki`; a custom `markdown_dir` outside the storage dir is the
  operator's responsibility (document it).
- **Archive across filesystems**: `os.replace` fails with `EXDEV`; fall
  back to `shutil.move` and verify the destination before any git call.
- **Git staging after the move**: `git rm --cached` on a path that no
  longer exists in the worktree is valid (it only touches the index); never
  run `git rm` without `--cached` (the file is already gone) and never
  `git commit`.
- **LLM cost**: three structured calls per admitted document (triage,
  classify, link) on the lightweight tier; discards and duplicates pay one
  or zero. Document `--limit` for large backlogs.
- **Legacy test tree**: `tests/knowledge/wiki/` at the repo root duplicates
  older wiki tests; new tests go under `packages/ai-parrot/tests/` only.
- **Edge cases carried from the brainstorm**: empty/missing inbox (exit
  0 / 2), undecodable binaries (skipped, left in place), unknown kind
  (fallback), link id not in store (dropped), markdown write failure (not
  archived), archive collision (`-N`), git unavailable (`staged_git=False`,
  no error), interrupted run (persist → project → archive ordering).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `click` | already a dependency | `wikitoolkit inbox` command |
| `pydantic` | `>=2` (already) | taxonomy, config, inbox models, structured LLM outputs |
| `pyyaml` | already | OKF frontmatter rendering (via `export.page_frontmatter`) |
| `ai-parrot-loaders` | optional extra (already wired by FEAT-451) | PDF/DOCX/PPTX/XLSX extraction through `DocumentAcquirer` |
| `git` CLI | system | staging the deletion of tracked originals |

No new runtime dependency is added.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

All brainstorm questions were resolved with the user on 2026-10-03 and are
reflected in §1–§7; they are echoed here for the audit trail.

- [x] Separate classification call or merged into triage Stage 1? — *Resolved in brainstorm*: separate `InboxClassification` call on the lightweight tier; FEAT-402 prompts and `TriageOutput` stay byte-identical; discards never pay for it.
- [x] Tags representation? — *Resolved in brainstorm*: `tag:<slug>` pages + `tagged` edges; no schema migration in any store; tags also rendered in the OKF frontmatter.
- [x] Document page identity? — *Resolved in brainstorm*: dedicated `doc:<slug>` page carries category, summary, tags, links, frontmatter and the markdown projection; PageIndex pages stay as children joined by `part_of` edges; the orchestrator's output is never rewritten.
- [x] Git staging policy? — *Resolved in brainstorm*: stage the deletion only (`git rm --cached` after the move when tracked); no `--commit` flag; the command never commits.
- [x] Duplicate policy? — *Resolved in brainstorm*: treat as rejected — Stage-0 heuristic reject archived under `rejected/` with bookkeeper reason `duplicate`; `--force` re-ingests.
- [x] Markdown projection location? — *Resolved in brainstorm*: `<storage_dir>/inbox/<category-plural>/<flat-id>.md`; never `pages/` (owned by the `memory` backend bundle).
- [x] Default taxonomy and ADR feed? — *Resolved in brainstorm*: six kinds — meeting→summary, briefing→overview, decision→concept, report→synthesis, memo→summary, note→concept, `default_kind: note`; and `decision` kinds emit an `origin="inferred"`, `review_status="unreviewed"` candidate into the FEAT-578 decisions plane via `DecisionRepository.save` for `wikitoolkit adr review`.
- [x] Link relation vocabulary and `supersedes` semantics? — *Resolved in brainstorm*: closed set `references`, `relates_to`, `mentions`, `follows_up`, `supersedes`; `supersedes` is informational only in v1 (no ranking demotion).
- [x] Candidate cap and search mix? — *Resolved in brainstorm*: at most 20 candidates (combined search top-k ∪ per-tag FTS, deduped); `sym:`/`file:` code pages enter only when the document names the symbol or path verbatim.
- [x] MCP tool timing? — *Resolved in brainstorm*: defer `wiki_inbox` to a follow-up feature (ledger item opened at `/sdd-done`); this spec ships the CLI only, with the processor shaped so the tool is a thin wrapper.
- [x] Fireflies overlap (FEAT-481)? — *Resolved in brainstorm*: detect the Fireflies id, look it up with `SourceCollectionManager.find_by_external_id`, and on a hit re-ingest that source (`replace_source_slice`) and update its doc page instead of creating a second one.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.157.0, reasoning high,
> 5 min 32 s) · Status: completed · Transcript: `sdd/state/FEAT-626/design_research/`
> All 28 cited paths passed repository containment and existence checks; every claim
> below was re-verified against the source before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Keep the document page outside the orchestrator source slice (architecture) | CONFIRM | `replace_source_slice` deletes `pages WHERE source_id = ?` plus every edge touching them (`store.py:1664-1750`); a doc page sharing the id would vanish on re-ingest. Doc page is now `origin="authored"`, `source_id=None`, identity in frontmatter; `part_of` edges rewritten per ingest. | §2 step 7, §3 M5, AC6 |
| S2 | Do not archive after a false-success `IngestReport` (risk) | CONFIRM | Store-sync, manifest and bookkeeping failures are logged as warnings and `status="ok"` is returned (`ingest.py:436-546`). Added `verify_persisted` gating the archive. | §2 step 8b, §3 M7, AC16 |
| S3 | Define crash consistency per backend (architecture) | CONFIRM (scoped) | SQLite slice replacement is one `_write` transaction (`store.py:1696`); `memory`/`arangodb` write in steps. Guarantee scoped to `sqlite`, best-effort elsewhere; no journal in v1. | §2 Overview, §7 Risks, AC10 |
| S4 | Extend the projection contract for free-form tags (api) | CONFIRM | `page_frontmatter` hard-codes `tags=[category]` (`export.py:95`); added an optional `tags` kwarg (default byte-identical) instead of string surgery. Search coerces unknown categories to `None` (`search.py:265-269`), so `tag` pages are safe. | §3 M6/M10, §6 Edit Sites, AC8 |
| S5 | Fireflies re-ingestion must preserve source identity (risk) | CONFIRM | The orchestrator resolves by URI and `add_source`s a new path (`ingest.py:316-335`); `update_source_uri` keeps `source_id`/`external_id` (`sources.py:948`). Repoint before ingest (Fireflies) and after the move (every archived source). | §2 steps 2 & 9, §3 M6/M7, AC11, AC21 |
| S6 | Make ADR candidate creation idempotent (risk) | CONFIRM | `save(record, None)` is insert-only and raises `ADR_REVISION_CONFLICT` (`repository.py:96-132`). `get()` first; reuse, never overwrite. | §3 M5, AC7 |
| S7 | Add force semantics below the CLI layer (api) | CONFIRM | `_heuristic_reject` runs unconditionally (`triage.py:318`, `:367`). Additive `skip_duplicate_check` kwarg bypasses only the duplicate branches. | §3 M10, §6 Edit Sites, AC19 |
| S8 | Fail closed on malformed structured responses (risk) | CONFIRM | `ask_structured` may return a dict-validated model, a list or the raw parsed value (`llm_adapter.py:125-150`). `isinstance` checks; fallback only for an explicit unknown kind; duplicates/self-links dropped. | §3 M3/M4, AC20 |
| S9 | Serialize inbox runs against concurrent writers (architecture) | CONFIRM | `wiki_write_lock` (`project.py:74`) guards `build`/`upsert` (`cli.py:1538`, `:1813`). Whole run holds it; busy → exit 3. | §2 Overview, §3 M7/M8, AC17 |
| S10 | Constrain configurable inbox/archive paths (risk) | CONFIRM | `storage_path` joins to root; `resolve_sources` follows `p.resolve()` with no symlink filter (`documents.py:195-199`). `validate_inbox_paths` + symlink/escape filter in `discover`. | §3 M2/M7, AC18 |

Summary: **10** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-03 | Jesus Lara / Claude | Initial draft from the accepted brainstorm (Option A, 11 resolved questions); 10 design-research suggestions confirmed (S1–S10) and folded in: doc page outside the source slice, verify-before-archive, sqlite-scoped crash safety, `page_frontmatter(tags=)`, source repointing, ADR reuse, triage `skip_duplicate_check`, fail-closed structured output, whole-run write lock, path validation |
