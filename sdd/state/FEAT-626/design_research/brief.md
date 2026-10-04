<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

Resolutions from the open-questions round (2026-10-03) — also binding:

- **Separate classification call**: a dedicated `InboxClassification`
  structured call on the lightweight tier; FEAT-402 triage prompts and
  `TriageOutput` stay byte-identical. Discards never pay for it.
- **Tags** are `tag:<slug>` pages (category `tag`, origin `authored`) joined
  by `tagged` edges — no `pages` schema migration in any store. Tags are also
  rendered in the OKF frontmatter.
- **Document page**: a dedicated `doc:<slug>` page created by the inbox is
  the carrier of category, summary, tags, links, frontmatter and the
  markdown projection. The PageIndex pages the orchestrator creates stay as
  children, each joined to the doc page by a `part_of` edge; the
  orchestrator's own output is never rewritten.
- **Git**: archiving a tracked original stages its deletion
  (`git rm --cached` after the move). No `--commit` flag; the command never
  commits.
- **Duplicates**: an unchanged file re-dropped in the inbox is a Stage-0
  heuristic reject → archived under `rejected/`, bookkeeper reason
  `duplicate`; `--force` re-ingests.
- **Markdown path**: `<storage_dir>/inbox/<category-plural>/<flat-id>.md`
  (never `pages/`, which the `memory` backend owns).
- **Default taxonomy**: six kinds — meeting→summary, briefing→overview,
  decision→concept, report→synthesis, memo→summary, note→concept;
  `default_kind: note`. **`decision` kinds additionally emit an ADR
  candidate** into the FEAT-578 decisions plane (`origin="inferred"`,
  `review_status="unreviewed"`) for `wikitoolkit adr review`.
- **Relation vocabulary** (closed): `references`, `relates_to`, `mentions`,
  `follows_up`, `supersedes`. `supersedes` is informational in v1 — no
  ranking demotion.
- **Link candidates**: at most 20 sent to the LLM (combined search top-k ∪
  per-tag FTS, deduped); `sym:`/`file:` code pages enter the candidate set
  only when the document names the symbol or path verbatim.
- **MCP tool deferred**: no `wiki_inbox` tool in this feature (FEAT-569 is
  in flight on `tools.py`/`mcp_server.py`); a ledger follow-up is opened at
  `/sdd-done`. The processor is built so the tool is a thin wrapper later.
- **Fireflies**: when a document carries a Fireflies id (frontmatter
  `fireflies_id` / `external_id`, or a `fireflies:<id>` marker), the inbox
  looks it up with `SourceCollectionManager.find_by_external_id`; a hit
  re-ingests that existing source (`replace_source_slice`) and updates its
  doc page instead of creating a second one.

---

### Recommended option / probable scope
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
ingest, and one extra `doc:<slug>` page per document. Both are acceptable
for a human-paced inbox (tens of documents per run, not thousands). The
user explicitly chose the separate classification call over merging it into
the Stage-1 prompt, and the dedicated doc page over rewriting the
orchestrator's root page (see the resolved questions at the end).

---

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
6. **Document page** (new) — upsert a dedicated `doc:<slug>` page
   (`origin="ingest"`, `asserted_by="agent:wikitoolkit-inbox"`,
   `source_id` = the orchestrator's source) carrying the taxonomy category,
   the classification title/summary, the FEAT-451 frontmatter and a
   `## Related` section of `[[wikilinks]]`. Recover the orchestrator's page
   ids from `SourceCollectionManager.get_source(source_id).pages_generated`
   and join each to the doc page with a `part_of` edge. Write
   `(doc_page, dst, rel, "asserted")` edges for the selected links and
   `tag:<slug>` pages + `tagged` edges (tags become graph nodes — no schema
   change). For `kind == decision`, also save an ADR candidate
   (`DecisionRecord(origin="inferred", review_status="unreviewed",
   evidence=[EvidenceRef(kind="document", page_id=doc_page, …)])`) through
   `DecisionRepository.save(record, None)` so `wikitoolkit adr review` can
   accept or reject it.
7. **Project markdown** (new) — render the document page as an OKF file
   under `<storage_dir>/inbox/<category-plural>/<flat-id>.md` using
   `page_frontmatter()` + the machine-field block, exactly as
   `SQLiteFileStore._render_page_file` does, written atomically
   (temp + `os.replace`); regenerate `<storage_dir>/inbox/index.md`.
8. **Archive** (new) — move the original to
   `<archive_dir>[/rejected]/<stem>.<YYYY-MM-DD>.<ext>` (suffix `-N` on
   collision); if the file is tracked, stage the deletion through
   `git rm --cached` (pattern: `cli.py:3192` already shells out to
   `git -C <root>`); persist `archived_to` into the source's
   `DocumentMetadata.extra` via `record_document_metadata`; bookkeeper
   `ARCHIVE_ORIGINAL` line. Duplicates (Stage-0 hash hit) and discards go
   under `rejected/`.

Before step 2, a **Fireflies pre-check**: a document carrying a Fireflies
id is matched against `find_by_external_id("fireflies:<id>")`; on a hit the
run re-ingests that existing source and updates its doc page instead of
creating a new one.

Charter gains an optional `taxonomy:` block (kinds with `id`, `description`,
`category`, optional `tag_hints`; `default_kind`; `max_tags`). A missing block
yields the built-in default taxonomy, so existing charters keep validating.
`WikiProjectConfig` gains an optional `inbox: InboxConfig` (`dir`,
`archive_dir`, `rejected_subdir`, `markdown_dir`, `date_format`, `stage_git`).

CLI: `wikitoolkit inbox [--dry-run] [--limit N] [--charter PATH]
[--lightweight-model] [--model] [--no-archive] [--force] [--json]`.
MCP: **deferred** — `InboxProcessor` is designed so a later `wiki_inbox`
tool is a thin wrapper, but no tool ships in this feature (FEAT-569 owns
`tools.py`/`mcp_server.py` right now).

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
- `IngestReport` does not return page ids, so the document-page stage must
  read them back from the source manifest — a small indirection.
- One extra page per document (`doc:<slug>`) alongside the PageIndex pages;
  consumers must learn that the doc page, not the PageIndex root, is the
  entry point (mitigated by `part_of` edges and the markdown projection).
- The ADR-candidate hook couples the inbox to `decisions/`; it must be
  imported lazily (as `LazyAdrGroup` does for the CLI) so the hook fast path
  and non-decision documents never pay for it.
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
- `parrot/knowledge/wiki/decisions/` — `DecisionRecord`, `EvidenceRef`, `DecisionRepository.save` for the ADR-candidate hook (lazy import).
- `parrot/knowledge/wiki/sources.py` — `find_by_external_id` for the Fireflies pre-check.

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/knowledge/okf/utils.py
packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py
packages/ai-parrot/src/parrot/knowledge/wiki/charter.py
packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/documents.py
packages/ai-parrot/src/parrot/knowledge/wiki/entry.py
packages/ai-parrot/src/parrot/knowledge/wiki/export.py
packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py
packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py
packages/ai-parrot/src/parrot/knowledge/wiki/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/project.py
packages/ai-parrot/src/parrot/knowledge/wiki/review.py
packages/ai-parrot/src/parrot/knowledge/wiki/search.py
packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
packages/ai-parrot/src/parrot/knowledge/wiki/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
packages/ai-parrot/tests/knowledge/wiki/test_cli.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
