---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent

**Date**: 2026-08-28
**Author**: Arturo Martinez
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The user maintains a mature, Obsidian-based **LLM-Wiki Operating Contract**
(`sdd/references/obsidian-wiki-operating-contract.md` — a 36-section
governance document, NOT itself a brainstorm) that defines how meeting
transcripts and summaries should be compiled into a trustworthy, provenance-
preserving knowledge base: immutable raw sources, canonical normalized meeting
pages, living current-state project pages, entities/concepts/contradictions,
daily diary synthesis, and continuous integrity checks.

Today there is **no agent that implements this contract**. The closest existing
code — `FirefliesWikiAgent` (`agents/fireflies_wiki.py`) and its parent
`FirefliesObsidianAgent` (`packages/ai-parrot/src/parrot/agents/obsidian.py`) —
has the *concept* (fetch from Fireflies → write to Obsidian → ingest into a
GraphIndex LLM Wiki) but is architecturally on the wrong side of almost every
contract rule:

- It **downloads and dumps the raw transcript verbatim into one flat note** in a
  single `meetings/` folder; the contract requires raw to stay immutable in
  `Raw/` and a *separate* normalized page to be compiled.
- Its **dedup is filename-stem-only** (`_make_note_title` +
  `_get_existing_meeting_titles`); the contract mandates `source_id` + SHA-256
  hash dedup, recorded in an append-only registry, *before* semantic reading —
  and it re-queries the Fireflies MCP for the same meetings on every run.
- It has **no classification, no project reconciliation, no entities/concepts,
  no contradiction protocol, no daily diary, no review queue, no
  lint/health/archive, no post-op validation** — the substance of the contract.

**Who is affected:** the user (single operator) who wants their Fireflies
meetings to flow, unattended, into the governed Obsidian knowledge base without
re-downloading processed meetings, and to keep a GraphIndex LLM Wiki as a fast
query/retrieval layer over that vault.

**Why now:** the operating contract already exists and is stable; the missing
piece is the Parrot agent that faithfully executes it.

## Constraints & Requirements

- **Contract fidelity is the acceptance bar.** The agent must follow the
  operating contract *to the letter*, and the contract's own §34 Post-Operation
  Validation + §36 Quality Standard become the **QA/verification oracle** — QA
  checks the agent's output against the document, section by section. (Delivery
  may be sequenced across tasks, but the acceptance target is the whole
  contract.)
- **Flag document contradictions**, don't silently paper over them — every
  ambiguity/inconsistency found in the contract is surfaced in *Open Questions*
  for the user to resolve before/with `/sdd-spec`.
- **Fetch must be participant-filtered** and must **never re-download an
  already-processed meeting** through the MCP.
- **Build on FEAT-472 (`MeetingRegistry`) — do not re-implement it.** The
  fireflies-meeting-registry feature is **merged** (PR #1264; all 7 tasks done
  2026-08-29) and already provides the id-keyed dedup gate, content fingerprints,
  the `suggest_from_date` watermark, no-refetch skip + `force_refetch`, path
  repair, backfill/merge, per-meeting lifecycle stamps, and
  `ObsidianToolkit.move_note`/`delete_note`. This agent **reuses that spine** and
  adds only the `Raw/` layer, the compiled pages, and the contract governance on
  top. This is a **hard dependency, now satisfied.**
- **Authoritative dedup gate = `MeetingRegistry` (the FEAT-472 `external_id`
  registry on `wiki.db`) ∪ a scan of the `Raw/` tree** — a deterministic id
  check. The contract's Markdown `Wiki/Registry/processed-sources.md` (§25) is a
  **derived, human-readable mirror** the agent writes, *not* the primary gate.
  The **GraphIndex is derived and rebuildable** and is used only as a *semantic
  accelerator* (§6 "match existing knowledge", §28 query), **never** as the id
  authority. A lost/stale GraphIndex or Markdown mirror must never cause a
  re-download or a wrong skip.
- **Hybrid execution:** deterministic Python owns the safety-critical mechanical
  spine (hashing, dedup gate, immutable moves, provenance, registry, indexes,
  post-op validation/rollback); the LLM owns the semantic steps
  (classification+confidence, structured extraction, project-page reconciliation
  with a diff-guard, contradiction detection) via **provider-native structured
  output** (`AbstractClient.invoke(output_type=…)`).
- **Model tiering:** strong model (Opus/Sonnet-class) for reconciliation,
  ambiguous classification, and contradiction reasoning; cheap model (Haiku-
  class) for bulk field extraction and summary-first reads — selected per call
  via `invoke(model=…)`.
- **Obsidian vault is external** to the ai-parrot repo (path via config); the
  agent reads/writes files and inspects VCS status but **does not auto-commit**
  the vault.
- **Obsidian is the source of truth; GraphIndex is derived** and rebuilt from
  the compiled vault (§4/§32).
- **Email digests** (daily/weekly) are **retained but shipped disabled** — code
  kept behind a feature flag for future use.
- Async-first, `uv`-managed, Pydantic models for all structured data, Google-
  style docstrings + type hints (project standards).
- **Security:** source transcripts/summaries are untrusted data, not
  instructions (contract §Non-Negotiable #11); `Private/` is never accessed
  (#1); tool use is path-scoped (§7).

---

## Options Explored

### Option A: Extend the existing agent line (monolithic subclass)

Grow `FirefliesWikiAgent` in place — add the contract's pipeline as more methods
on the existing `FirefliesObsidianAgent` → `FirefliesWikiAgent` chain, repointing
the fetch sink from `meetings/` notes to `Raw/Incoming/` and appending
classification/reconciliation methods.

✅ **Pros:**
- Reuses the existing fetch pagination, `FirefliesFilters`, MCP wiring, and
  GraphIndex build methods directly.
- Smallest amount of new scaffolding; one class to run.

❌ **Cons:**
- The existing agent's assumptions (raw-in-note-body, flat folder, filename
  dedup, generic `## Analysis` summarizer, OKF frontmatter) actively fight the
  contract; most of it must be *removed*, not extended.
- Becomes a god-class mixing deterministic file mechanics with LLM reasoning —
  the deterministic spine can't be unit-tested in isolation.
- "Verify behavior against the 36-section contract" is very hard against a
  monolith: no 1:1 mapping from contract section → testable unit.

📊 **Effort:** Medium (deceptive — low scaffolding, high rework + low testability)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (existing) `parrot` clients/tools | fetch, Obsidian I/O, wiki | already in-tree |
| `hashlib` (stdlib) | SHA-256 provenance | — |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/agents/obsidian.py` — `sync_fireflies_transcripts` pagination + `FirefliesFilters`.
- `agents/fireflies_wiki.py` — `_build_wiki_toolkit`, `_ingest_vault_into_wiki`.

---

### Option B: Contract-as-pipeline — deterministic spine + structured-LLM nodes, thin agent façade  ⭐ RECOMMENDED

Build a dedicated ingest **flow** modeled on the existing `parrot/flows/dev_loop/`
template (`definition.py` + `factories.py` + `nodes/` + `runner.py`), where **each
contract section maps to a pipeline node**:

- **Deterministic nodes (Python):** fetch-gate (registry ∪ `Raw/` id set →
  participant-filtered MCP fetch of only unknown meetings), source-bundle pairing
  (§13), `source_id` + SHA-256 hashing (§14), immutable `Raw/Incoming → Raw/Processed`
  moves with pre/post hash verify, canonical-page/registry/index writers,
  archive (§31), and the §34 post-op validation + rollback.
- **Structured-LLM nodes:** summary-first classification + confidence (§15),
  typed extraction (decisions/requirements/action-items/risks/open-questions),
  project-page reconciliation with a **diff-guard** (§19), entity/concept
  match-before-create (§20/§21), contradiction detection (§22) — each via
  `AbstractClient.invoke(output_type=<PydanticModel>, model=<tier>)`.
- **Thin Parrot `Agent` façade:** exposes the contract's plain-English intents
  (`ingest`, `query`, `health`, `lint`, `archive`, `graph`) as tools/commands;
  the agent orchestrates, it does not free-form reason over the whole vault.
- **GraphIndex derived rebuild:** after a successful ingest, (re)ingest the
  compiled vault via `LLMWikiToolkit.ingest_obsidian_vault(..., incremental=True)`
  to keep the derived retrieval plane fresh; queries read the GraphIndex for
  candidate retrieval, then verify against the Obsidian source pages for
  provenance.

The shared contract between nodes is a set of **Pydantic frontmatter/schema
models** (one per §10 page type) plus the §34 validation checklist rendered as an
executable function — this *is* the QA oracle.

✅ **Pros:**
- **1:1 contract-section → node → test** mapping makes "verify against the
  document" tractable; §34 becomes an executable gate.
- Deterministic spine is pure-Python and unit-testable without an LLM; LLM nodes
  are structured-output and mockable.
- Reuses the proven `AgentsFlow`/`dev_loop` pattern, `invoke()` structured
  output, `LLMWikiToolkit`, `ObsidianToolkit`, and `FirefliesFilters`.
- Model tiering and the diff-guarded project rewrite (the highest-risk step) are
  explicit, isolated nodes with their own guardrails.
- Cleanly honors every locked decision (registry-authoritative dedup, derived
  GraphIndex, external vault, hybrid execution, disabled email).

❌ **Cons:**
- Most upfront scaffolding of the three options; a new subsystem
  (`parrot/flows/wiki_ingest/` or `parrot_tools`-side toolkit set).
- Requires freezing the Pydantic schema contract early so page-type nodes can
  fan out.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (in-tree) `parrot.bots.flows` / `parrot.flows.dev_loop` | DAG/node pattern to copy | `AgentsFlow`, `Node`, `runner.py` |
| (in-tree) `AbstractClient.invoke` | provider-native structured extraction | `clients/base.py:1747`, `output_type=` + `model=` |
| (in-tree) `LLMWikiToolkit` | derived GraphIndex rebuild + query | `knowledge/wiki/toolkit.py` |
| (in-tree) `ObsidianToolkit` | vault read/write/search | `tools/obsidian.py` |
| `pydantic` (already a core dep) | §10 frontmatter schemas + `invoke` output types | v2 |
| `python-frontmatter` (already used by ObsidianToolkit) | parse/preserve YAML frontmatter | see `update_note` |
| `hashlib` (stdlib) | SHA-256 raw provenance | — |
| `PyYAML` (already used) | frontmatter render | `create_note` |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/` — template for `definition.py`/`factories.py`/`nodes/`/`runner.py`.
- `packages/ai-parrot/src/parrot/agents/obsidian.py` — `FirefliesFilters` (participant filter) + fetch pagination loop (sink repointed to `Raw/Incoming`).
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — `ObsidianToolkit` read/list/search/create/update.
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` — `LLMWikiToolkit.ingest_obsidian_vault` / `query` / `create_wiki`.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` — `build_graph_memory_toolkit`.
- `agents/fireflies_wiki.py` — `_build_wiki_toolkit` / `_build_pageindex_toolkit` wiring, and the (kept-disabled) email digest machinery.

---

### Option C: Producer / compiler two-stage split (unconventional)

Two decoupled units: (1) a **minimal producer** — participant-filtered fetch +
registry/`Raw/` dedup gate that drops immutable `transcript`/`summary`/`metadata`
bundles into `Raw/Incoming/` and nothing else; (2) a **compiler** stage that runs
the full contract over `Raw/Incoming/`. The two communicate only through the
filesystem contract that the operating document already implies (rule #3: "a
separate process places files in `Raw/Incoming/`").

✅ **Pros:**
- Matches the contract's own mental model **literally** — the downloader is
  explicitly *not* the compiler.
- The producer is tiny, deterministic, and extremely robust; the compiler can
  evolve (or even be run by Claude-Code-on-the-vault) independently.
- Clean failure isolation: a compiler bug never risks the fetch/dedup state.

❌ **Cons:**
- The user explicitly wants **one Parrot agent** doing download → process →
  GraphIndex; a two-process split adds a handoff contract and coordination the
  user didn't ask for.
- The "keep a GraphIndex together with Obsidian" goal spans both stages, so the
  seam has to be re-crossed anyway.
- Two deploy/scheduling surfaces instead of one.

📊 **Effort:** High (two subsystems + an inter-stage contract)

📦 **Libraries / Tools:** same in-tree set as Option B, split across two entry points.

🔗 **Existing Code to Reuse:** same as Option B; the producer reuses only the
fetch + dedup portions.

---

## Recommendation

**Option B — Contract-as-pipeline.**

The decisive requirement is *"follow the contract to the letter and make the
contract the QA oracle."* Option A cannot satisfy that: a monolith gives no
section-to-test mapping and buries the deterministic spine inside LLM code.
Option C satisfies fidelity but violates the explicit "one Parrot agent"
directive and doubles the operational surface for a single-operator tool.

Option B is the only one that makes the *whole contract executable and
verifiable*: every §-section becomes a node with a Pydantic contract and a unit
test, §34 validation becomes a runtime gate, and the highest-risk operation (the
§19 whole-project-page rewrite) is an isolated, diff-guarded node rather than an
emergent behavior. It also maximizes reuse of proven in-tree machinery
(`AgentsFlow`/`dev_loop`, `invoke()` structured output, `LLMWikiToolkit`,
`ObsidianToolkit`, `FirefliesFilters`).

What we trade off: the most upfront scaffolding and an early schema-freeze
requirement. That's acceptable — the schema contract is small, and freezing it
first is exactly what enables parallel fan-out of the page-type nodes afterward.

---

## Feature Description

### User-facing behavior

A single registered Parrot agent (`fireflies_wiki_kb`, name TBD) that the user
drives with plain-English intents (contract §6), e.g.:

- `ingest incoming meetings` — fetch new participant-matched meetings from
  Fireflies (skipping anything already processed), drop immutable bundles into
  `Raw/Incoming/`, then compile them into the vault per the contract, and refresh
  the derived GraphIndex.
- `query: what is the current <Project> plan?` — answer from compiled knowledge
  (GraphIndex retrieval → Obsidian page verification), with `[[wikilinks]]` to
  sources; save as a synthesis only on request.
- `health`, `lint`, `lint --fix`, `archive old notes`, `build a graph report for
  <Project>` — the read-only/maintenance workflows (§29–§32).

Each operation ends with the contract's **Required Final Change Summary** (§35):
created/updated/moved/skipped/contradictions/review-required/validation. Runs are
idempotent; a re-run of an already-processed meeting is a `duplicate-skip`.

Optionally scheduled (like the current agent's 07:00 sync). Email digests exist
but are **off by default** behind a feature flag.

### Internal behavior (high-level flow, no code)

1. **Fetch-gate (deterministic — reuse FEAT-472).** Use
   `MeetingRegistry.suggest_from_date()` for the watermark and
   `MeetingRegistry.classify()` (∪ a `Raw/` id scan) so the Fireflies MCP is
   called with the participant filter and only *unknown/changed* meetings are
   fetched (transcript + summary + metadata). `force_refetch` overrides.
2. **Drop to `Raw/Incoming/` (deterministic — new sink).** Write the raw bundle
   unchanged; the FEAT-472 `fingerprint()`/hashes provide provenance.
3. **Pair + dedup gate (deterministic, §13/§14).** Pair transcript/summary/
   metadata by strongest key; the FEAT-472 `classify()` result drives
   duplicate/revise/probable-duplicate; **override revise** to route to
   `Raw/Processed/Revisions/` + Review Queue (§14.3) instead of in-place update;
   all *before any semantic read*.
4. **Read existing context (deterministic + retrieval).** Read `Wiki/index.md`,
   `Wiki/overview.md`, the registry; use the GraphIndex to *accelerate* "match
   existing knowledge" (§6) — candidate projects/entities/concepts.
5. **Summary-first classification (LLM, structured).** Classify primary/
   additional projects, clients, people, products, concepts + confidence;
   apply the transcript-fallback ladder (§15.4) only when triggered.
6. **Detect contradictions first (LLM, §22)** against current project/Wiki
   knowledge; create contradiction records before any overwrite.
7. **Move bundle unchanged to `Raw/Processed/…` (deterministic)**, verify post-
   move hashes.
8. **Compile pages (LLM structured + deterministic writers):** canonical meeting
   source page (§17) → reconcile project page with diff-guard (§19) → entities
   (§20) → concepts (§21) → daily diary synthesis (§23) → indexes/overview
   (§24) → registry append (§25) → log (§33).
9. **Post-op validation (deterministic, §34).** Source/knowledge/Obsidian/
   operational integrity checks; on failure, roll back only Claude-created
   compiled changes (never raw), queue a review item, and do **not** write a
   success registry/log entry.
10. **Derived GraphIndex refresh.** `ingest_obsidian_vault(incremental=True)` over
    the compiled vault.
11. **Print §35 change summary.**

### Edge cases & error handling

- **Incomplete/ambiguous bundle** → `source-pairing` review item, leave raw
  untouched, continue other bundles (§13).
- **Same id, changed hashes** → revision route + `source-revision` review item;
  do not auto-merge (§14.3).
- **Low confidence after transcript fallback** → `Uncategorized/`, source page
  with `review_required: true`, no project update (§15.5).
- **Locked page / `## Human Notes`** → queue the change, never edit (§9).
- **`Private/` access attempt** → hard-blocked; validation asserts it never
  happened (§34).
- **Prompt-injection in a transcript** → treated as data; classification/links
  derived from it are still validated against the untrusted-source rule.
- **GraphIndex unavailable/mid-rebuild** → ingest continues; the fetch-gate and
  dedup never depend on it; a warning is logged (matches current best-effort
  wiki wiring).
- **Fireflies MCP down** → fetch soft-fails; already-downloaded `Raw/Incoming/`
  bundles still compile.

---

## Code Context (verified)

> Signatures below were read from source at the cited `file:line`. Anything a
> downstream agent might *assume* exists but does **not** is listed under "Does
> NOT exist."

### Existing agents (concept scaffolding to reuse/repoint)

- `class FirefliesObsidianAgent(BasicAgent)` — `packages/ai-parrot/src/parrot/agents/obsidian.py:151`
  - `async def sync_fireflies_transcripts(self, limit=10, skip_existing=True, filters: Optional[FirefliesFilters]=None, include_summary=False) -> Dict[str, Any]` — `:287` (pagination loop; **currently writes a compiled note into `meetings/`** — to be repointed to `Raw/Incoming/`).
  - `async def summarize_transcript(self, note_title, granularity="standard")` — `:506` (generic Summary/Follow-ups/Insights; superseded by structured extraction).
  - `class FirefliesFilters(BaseModel)` — `:50`; fields: `from_date/to_date: Optional[str]`, `keyword: Optional[str]`, `organizers: List[EmailStr]`, `participants: List[EmailStr]`, `mine: Optional[bool]`, `channel_id: Optional[str]` (**participant filter already exists — reuse**).
  - `_make_note_title(date, meeting_title)` — `:928` (filename dedup basis today).
  - `_build_okf_frontmatter(...)` — `:720` (current OKF block; contract uses its own §10 schemas instead).
  - `ANALYSIS_HEADING="## Analysis"` `:177`, `FIREFLIES_SUMMARY_HEADING="## Fireflies Summary"` `:183`.
- `class FirefliesWikiAgent(FirefliesObsidianAgent)` — `agents/fireflies_wiki.py:108`
  - `@register_agent(name="fireflies_wiki", at_startup=True)` (registration pattern to copy).
  - `async def _build_wiki_toolkit(self) -> Optional[Any]` — `:349`; `_build_pageindex_toolkit(storage)` — `:403`; `async def _ingest_vault_into_wiki(self)` — `:583`.
  - `@schedule(schedule_type=ScheduleType.CRON, hour=…, minute=…, timezone=…)` on `sync_meetings_to_wiki` — `:519` (scheduling pattern; email digest methods `email_daily_meeting_digest`/`email_weekly_insights` to be kept **disabled**).

### Obsidian I/O — `class ObsidianToolkit(AbstractToolkit)` `packages/ai-parrot/src/parrot/tools/obsidian.py:78`

- `async def read_note(self, path, include_content=True)` — `:212`
- `async def list_notes(self, folder=…, recursive=…)` — `:257`
- `async def search_notes(self, query, limit=20)` — `:300`; `search_by_tag(tag, limit=50)` — `:314`; `search_with_backlinks(...)` — `:331`
- `async def create_note(self, path, content, frontmatter: Optional[Dict]=None)` — `:439` (renders YAML frontmatter; `overwrite=False`, raises `FileExistsError`)
- `async def update_note(self, path, content, preserve_frontmatter=True)` — `:471` (keeps existing frontmatter by default — useful for the §19 project reconcile)
- `async def delete_note(self, path)` — `:522`
- `async def move_note(self, source, destination)` — `:538` (**move/rename EXISTS**; returns `affected_backlinks` but **does NOT rewrite links** — §8.1 link-fixup is still on us).
- `__init__` takes `allowed_operations` set (`:127`); FEAT-472 added `move`/`delete` to the Fireflies agent's set — enable the same here.

### Structured extraction — `class AbstractClient` `packages/ai-parrot/src/parrot/clients/base.py`

- `async def invoke(self, prompt, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt=None, max_tokens=4096, temperature=0.0, use_tools=False, tools=None) -> InvokeResult` — `:1747` (**provider-native structured output**; `output_type=<Pydantic>`, per-call `model=` override → the model-tiering mechanism). `_get_structured_config(...)` `:1605`.

### Wiki / graph planes

- `class LLMWikiToolkit(AbstractToolkit)` — `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:54`
  - `__init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit, config: WikiConfig, agent_id="agent", store=None, **kwargs)` — `:83`
  - `async def ingest_obsidian_vault(self, wiki_name, vault_path, incremental=False, extract_entities=False, granularity="standard")` — `:295` (derived rebuild; Phase 1b imports the vault `[[wikilink]]` graph)
  - `async def query(...)` — `:403`; `async def create_wiki(...)` — `:544`; `_config_for(wiki_name)` raises on wiki_name mismatch — `:1378`.
- `class WikiConfig(BaseModel)` — `packages/ai-parrot/src/parrot/knowledge/wiki/models.py:52`
- `async def build_graph_memory_toolkit(db_dir, tenant_id="default", agent_id="agent", run_id=None, embedder=None, client=None, dimension=…) -> GraphIndexToolkit` — `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py:203`
- `class PageIndexToolkit(AbstractToolkit)` — `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:50`; `class PageIndexLLMAdapter` — `…/pageindex/llm_adapter.py:42`

### FEAT-472 `MeetingRegistry` (merged PR #1264 — REUSE, do not rebuild)

- `class MeetingRegistry` — `packages/ai-parrot/src/parrot/agents/meeting_registry.py`
  - `__init__(self, registry_dir, *, manager: SourceCollectionManager | None = None)` — defaults to a manager on `registry_dir/"wiki.db"`; every call dispatched via `asyncio.to_thread`.
  - `async def classify(self, item, *, fetch, fetch_summary, force_refetch=False) -> Classified` — create | skip | revise, with `probable_duplicate_of` for contract §14.3 (hash match, different id).
  - `async def suggest_from_date(self, *, overlap_days) -> str | None` — the fetch **watermark** (resolves brainstorm Q3).
  - `record_synced`, `pending_analysis`, `mark_analyzed`, `mark_analysis_failed`, `mark_wiki_ingested`, `repair_path`, `backfill_from_vault`, `merge_duplicates`, `forget(reject=True)`, `unique_slug`, `available`.
  - Helpers: `normalise_transcript(text)` and `fingerprint(text)` = `sha256(normalise_transcript(text))` — **content-only** transcript hash (summary hashed separately). *(Partially answers D5.)*
- `SourceCollectionManager` gained `external_id` support — `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`: `find_by_external_id`, `find_entries_by_external_ids`, `list_by_external_prefix("fireflies:")`, `set_external_id`, `update_source_uri` (keeps `source_id`, re-hashes at new path). `SourceManifestEntry.external_id: str | None` — `.../wiki/models.py:248`.
- Registry shares one `wiki.db` row per meeting with `LLMWikiToolkit.ingest_obsidian_vault` (sync writes `external_id` + `doc_metadata.fireflies`; ingest fills `pages_generated`/`file_hash`).
- **Divergence to override (FEAT-472 §7/§8):** on "same id, changed content" FEAT-472 updates the note **in place**; this agent must instead route to `Raw/Processed/Revisions/` + Review Queue per contract §14.3/§22 (consume `report["revised"]`).

### Config & MCP

- Fireflies/wiki config keys — `packages/ai-parrot/src/parrot/agents/conf.py`: `FIREFLIES_WIKI_LLM` `:133`, `WIKI_MODEL` `:144`, `FIREFLIES_WIKI_NAME` `:151`, `FIREFLIES_WIKI_STORAGE_DIR` `:152`, `FIREFLIES_WIKI_EXTRACT_ENTITIES` `:156`, schedule + recipients keys `:112–188`. FEAT-472 **added** `FIREFLIES_REGISTRY_DIR`, `FIREFLIES_SYNC_OVERLAP_DAYS` (2), `FIREFLIES_RECHECK_DAYS` (7). New keys still needed: external vault path, participant allowlist, model tiers, email-disabled flag, `Raw/` layout roots.
- `async def add_fireflies_mcp_server(self, api_key=…)` — `packages/ai-parrot/src/parrot/mcp/integration.py:1447` (transcript/summary MCP tools).
- Registration/scheduling: `from parrot.registry import register_agent`; `from parrot.scheduler import ScheduleType, schedule` (usage verified in `agents/fireflies_wiki.py`).

### Prior art to REUSE — verified, do NOT rebuild (Jesus review + FEAT-472)

- **`ObsidianToolkit.move_note` EXISTS** — `tools/obsidian.py:538`; move/rename is covered. (Residual: it reports `affected_backlinks` but does not rewrite them — §8.1 link-fixup is the only piece we add.)
- **Hash-based staleness EXISTS** — `knowledge/wiki/sources.py` (SHA-1 + mtime), consumed by `ingest_obsidian_vault(incremental=True)`.
- **Id-keyed dedup registry EXISTS (FEAT-472)** — `MeetingRegistry` + `external_id`, `classify()`, content `fingerprint()`, `suggest_from_date()` watermark, no-refetch skip / `force_refetch`, `repair_path`, `backfill_from_vault`, `merge_duplicates`, lifecycle stamps. (See the FEAT-472 Code Context block above.)

### Genuinely missing — this feature builds (smaller than v0 of this doc implied)

- **No `Raw/` immutable-bundle layer** — nothing drops `transcript`/`summary`/`metadata` into `Raw/Incoming/` or moves them to `Raw/Processed/…` with hash verify (§13/§14/§27). FEAT-472 keeps raw *in the note body*; the dedup-gate logic is reusable — only the **sink changes** to `Raw/`.
- **No contract-shaped compilation** — canonical meeting page (§17), living project reconciliation (§19), entities/concepts (§20/§21), contradiction protocol (§22), daily diary (§23), review queue (§26), lint/health/archive (§29–§31), §34 validation. None exist.
- **No Markdown `processed-sources.md` mirror (§25)** — FEAT-472 keeps the registry in `wiki.db` only; the human-readable mirror is this agent's job (explicitly deferred to it by the FEAT-472 spec).
- **No auto-link-rewrite after move/rename (§8.1)** — `move_note` reports broken backlinks but does not fix them.
- **No server-side "exclude already-processed" on `fireflies_get_transcripts`** — confirmed still true; **unnecessary** given the client-side `MeetingRegistry` gate + `suggest_from_date` watermark.
- `ModelSwitchingMixin` exists but is optional — the confirmed per-call tiering mechanism is `invoke(model=…)`.

---

## Capabilities

**Reused from FEAT-472 / existing code (wire in — NO new build):**
- id-keyed dedup + `classify` (create/skip/revise/probable-duplicate), content fingerprints, `suggest_from_date` watermark, no-refetch skip / `force_refetch`, `repair_path`, `backfill_from_vault`, `merge_duplicates`, lifecycle stamps — `MeetingRegistry`.
- `ObsidianToolkit.move_note`/`delete_note`; incremental note-file staleness (`sources.py`).
- `AbstractClient.invoke(output_type=, model=)` — structured extraction + per-call model tiering.
- `LLMWikiToolkit.ingest_obsidian_vault(incremental=True)` — derived GraphIndex rebuild.

**New (this feature):**
- `raw-bundle-layer` — drop immutable `transcript`/`summary`/`metadata` into `Raw/Incoming/`; move to `Raw/Processed/…` with pre/post hash verify (§13/§14/§27).
- `meeting-source-compiler` — canonical §17 page via structured extraction.
- `project-page-reconciler` — diff-guarded §19 living-state rewrite.
- `entity-concept-resolver` — match-before-create for §20/§21.
- `contradiction-protocol` — first-class §22 records.
- `daily-diary-synthesizer` — §23 synthesis (not concatenation).
- `wiki-index-overview-maintainer` — §24 navigation + living overview.
- `processed-sources-mirror` — §25 Markdown mirror of the FEAT-472 `wiki.db` registry.
- `review-queue-manager` — §26 non-blocking human-judgment queue.
- `ingest-pipeline-orchestrator` — §27 ordered flow (wraps the FEAT-472 gate).
- `wiki-query` — §28 retrieval-then-verify.
- `wiki-health` / `wiki-lint` / `wiki-archive` / `graph-report` — §29/§30/§31/§32.
- `post-op-validation` — §34 executable checklist = QA oracle.
- `link-fixup` — rewrite `[[wikilinks]]` after a move/rename (§8.1).

**Modified:**
- `fireflies-obsidian-fetch` — the FEAT-472 sync writes a compiled note; repoint the sink to `Raw/Incoming/` bundles, and **override the in-place `revise`** with the contract's Revisions + Review-Queue routing (§14.3).
- `email-digests` — retained, shipped disabled behind a feature flag.

---

## Impact & Integration

| Component | Change | Notes |
|---|---|---|
| `agents/fireflies_wiki.py` | superseded / repurposed | keep as reference + reuse wiki-build + (disabled) email methods |
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | reuse + modify | reuse `FirefliesFilters` + fetch loop; repoint sink |
| `packages/ai-parrot/src/parrot/agents/meeting_registry.py` (FEAT-472) | reuse (hard dep) | `MeetingRegistry` dedup gate, watermark, lifecycle — the spine this agent builds on |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` (FEAT-472) | reuse | `external_id` lookups, `update_source_uri`, staleness hashing |
| `packages/ai-parrot/src/parrot/tools/obsidian.py` | reuse | `move_note`/`delete_note` exist (:538); add only §8.1 link-fixup |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | reuse | derived GraphIndex rebuild + query |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | reuse | graph plane |
| `packages/ai-parrot/src/parrot/clients/base.py` (`invoke`) | reuse | structured extraction + model tiering |
| `packages/ai-parrot/src/parrot/agents/conf.py` | extend | new config keys (vault path, participant allowlist, model tiers, email-disabled flag) |
| new subsystem `parrot/flows/wiki_ingest/` (or `parrot_tools` toolkit set) | create | pipeline nodes + runner + Pydantic schemas + §34 validator |
| `parrot/registry`, `parrot/scheduler` | reuse | `@register_agent`, `@schedule` |
| `parrot/mcp/integration.py` | reuse | `add_fireflies_mcp_server` |
| **External Obsidian vault** (outside repo) | write target | path via config; no auto-commit |
| `sdd/references/obsidian-wiki-operating-contract.md` | reference oracle | the authoritative Obsidian operating contract (not a brainstorm) |

**Dependencies & prior art:**
- **FEAT-472 fireflies-meeting-registry** — MERGED (PR #1264, done 2026-08-29). **Hard dependency, satisfied.** Provides the dedup/fingerprint/watermark spine this agent builds on.
- **FEAT-473 a2ui-v1-structured-outputs** — MERGED (PR #1267). Maturing structured-output infra (`adapters/structured.py`, `data_model=` passthrough); the core `invoke(output_type=)` we rely on predates it — note only, no dependency.
- **FEAT-392** `LLMWikiToolkit` Obsidian ingest — leveraged for the derived GraphIndex rebuild.
- **toolmanager-tooldefinition-enforcement** — a feature whose ids were just *reserved* (not built, 2026-08-29). May change how toolkits declare tools; re-check at `/sdd-spec` time before finalizing the agent's tool surface.
- Related (not conflicts): `sdd/specs/fireflies-mcp-improvements.spec.md`, `sdd/specs/integrate-mcp-fireflies.spec.md` (the `FirefliesFilters` + native-summary work this fetch reuses).

---

## Open Questions

> The user asked that document contradictions be flagged for discussion. Items
> D1–D8 are contradictions/ambiguities **in the operating contract itself**;
> Q1–Q4 are implementation decisions.

**Document contradictions / ambiguities (owner: user, to resolve before/with `/sdd-spec`):**

- **D1 — Raw provenance links.** §10.1/§17 store `raw_transcript`/`raw_summary`
  as `[[wikilinks]]` into `Raw/Processed/…`, but raw files can be non-Markdown
  (`transcript.<ext>`, §4) and §8.1 forbids links to non-existent pages /
  reserves Markdown links for external URLs. Proposal: use **plain relative
  paths** (not wikilinks) for raw provenance pointers. Which wins?
- **D2 — `primary_project ∈ projects[]`.** §10.1 lists both but never states the
  invariant. Add the rule?
- **D3 — GraphIndex vs "Obsidian graph is primary / derived-only" (§4/§32).** The
  contract's own model has **no code-side wiki plane**; the user wants a
  GraphIndex LLM Wiki alongside Obsidian. We resolved it as a *derived
  accelerator*, but should the contract be **amended** to acknowledge the derived
  plane (so a future reader doesn't treat GraphIndex as a rule violation)?
- **D4 — Dual IDs.** `id: "source:fireflies:<id>"` vs `source_id:
  "fireflies:<id>"` (§10.1) — which is authoritative for dedup/linking?
- **D5 — Content-fingerprint dedup fields undefined.** §14.1 #4 invokes a
  fingerprint when no external id exists but never says which fields feed it.
- **D6 — Embeddings vs groundedness.** §15/#15 forbid "external knowledge / web
  research" during normal ops. Does using the **GraphIndex's embeddings** (which
  index only repo sources) for §6 candidate retrieval count as *internal* (thus
  allowed)? We read it as allowed — confirm.
- **D7 — 14-day active window.** §18/§31 hard-code 14 days globally; make it
  per-project or configurable?
- **D8 — Query read path.** §28 says answer from compiled pages and drill to raw.
  Confirm: GraphIndex for *candidate retrieval only*, then **read the Obsidian
  source pages** for the actual answer + provenance (GraphIndex answers are never
  quoted as authority).

**Implementation decisions (owner: spec):**

- **Q1 — Agent home.** New subsystem under `parrot/flows/wiki_ingest/` (flow
  pattern) vs a `parrot_tools` toolkit set the agent composes. (Leaning: flow
  subsystem, matching `dev_loop/`.)
- **Q2 — Diff-guard for §19.** What exactly protects the project-page rewrite
  from dropping still-sourced claims — structured section-merge + a "no claim
  removed while its source is live" assertion in §34? Define the guard.
- **Q3 — Fetch watermark.** ✅ **RESOLVED by FEAT-472** — `suggest_from_date()`
  (= `max(synced_at) − FIREFLIES_SYNC_OVERLAP_DAYS`) ships the watermark; the
  `MeetingRegistry` id gate is the backstop. Reuse as-is.
- **Q4 — Scheduling & email flag.** Reuse the existing `@schedule` cadence for
  `ingest`; confirm the email-digest feature-flag key name and default (off).

**Reconciliation with FEAT-472 (owner: user/spec — decide before `/sdd-spec`):**

- **R1 — Registry substrate.** Confirm: `MeetingRegistry` (`wiki.db`) is the
  operational authority; `Wiki/Registry/processed-sources.md` (§25) is a derived
  Markdown mirror this agent writes. (Recommended; FEAT-472 already delegates the
  mirror to this agent.)
- **R2 — Vault layout migration.** FEAT-472's registry keys on the note in a flat
  `meetings_folder` with the raw transcript *in the note body*. Adopting the
  contract layout re-homes `source_uri` to the canonical `Wiki/Sources/Meetings/`
  page and moves raw to `Raw/`. Decide: migrate existing vaults via
  `backfill_from_vault` re-pointing, or start the contract layout fresh?
- **R3 — Revise policy override.** FEAT-472 updates a changed transcript **in
  place**; the contract requires Revisions-folder + Review-Queue routing, no
  auto-merge (§14.3/§22). Confirm the KB agent overrides FEAT-472's revise by
  consuming `report["revised"]`.

---

## Parallelism Assessment

- **Internal parallelism:** High, *after a foundation phase*. The shared contract
  is (a) the Pydantic §10 frontmatter/schema models, (b) the vault-access layer
  (`ObsidianToolkit` — `move_note` exists — plus the new §8.1 link-fixup and the
  reused `MeetingRegistry`), and (c) the §34 validation checklist. Once those are
  frozen, the compilation nodes — meeting §17, project §19, entities §20,
  concepts §21, contradictions §22, daily §23 — and each read-only workflow
  (query §28, health §29, lint §30, archive §31, graph §32) are largely
  independent. The dedup/provenance spine is mostly **reused from FEAT-472**, so
  the foundation phase is lighter than v0 of this doc assumed.
- **Cross-feature independence:** Mostly additive (new subsystem) on top of the
  now-merged FEAT-472. `obsidian.py` / `ObsidianToolkit` (fetch repoint, revise
  override, link-fixup) are the only contended files; FEAT-472 is merged so no
  in-flight spec is known to target them (not exhaustively checked — verify at
  `/sdd-task`).
- **Recommended isolation:** **mixed.** One sequential *foundation* worktree
  (schemas + vault access/mover + fetch-gate + provenance spine + §34 validator),
  then fan out the page-type compilers and read-only workflows into parallel
  worktrees against the frozen schema contract.
- **Rationale:** The schemas + validator are the coupling surface; freezing them
  first removes the merge hazard and lets the independent §-section nodes proceed
  concurrently.
