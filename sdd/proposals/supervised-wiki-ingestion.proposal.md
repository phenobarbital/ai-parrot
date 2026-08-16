---
id: FEAT-402
title: Supervised ingestion for LLM Wiki — charter-driven triage router with HITL manifest review
slug: supervised-wiki-ingestion
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-30
  summary_oneline: Add charter-scored, HITL-reviewable "supervised ingestion" for document corpora to wikitoolkit
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-402-supervised-wiki-ingestion/
created: 2026-07-30
updated: 2026-08-02
---

# FEAT-402 — Supervised ingestion for LLM Wiki (charter-driven triage + HITL manifest review)

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` (brainstorm 2026-07-30) + `file`: 3 reference schemas — see §0
> **Audit**: [`sdd/state/FEAT-402-supervised-wiki-ingestion/`](../state/FEAT-402-supervised-wiki-ingestion/)

> **Note on the id**: `FEAT-402` was allocated per FEAT-387 via
> `scripts/sdd/reserve_ids.py` against `sdd/tasks/.id_ledger.json`
> (ledger commit `00ba864fa`, 2026-08-02).

---

## 0. Origin

The original request, preserved verbatim (es), is at
`sdd/state/FEAT-402-supervised-wiki-ingestion/source.md`. Abridged:

> En este escrito sobre Wiki LLM […] habla de "assisted ingestion" o de
> "supervised ingestion", por ahora, comandos como "wikitoolkit build" solo
> hacen unsupervised ingestion y para folders llenos de documentos (que no son
> datos), puede ser un problema. […] que el LLM Ingestion tenga un intent
> router que permita evaluar el contenido por encima, clasificarlo […] evaluar
> el propio contenido contra las reglas de scoring […] y ante cualquier duda,
> el CLI ejecutar un HITL call mostrando el documento, el briefing y preguntar
> al usuario si ese documento debe ir (o no) al wiki […] si en una reunión solo
> se contaron chistes, se debería descartar del wiki.

**Reference design artifacts** (produced during the brainstorm, copied into
`sdd/state/FEAT-402-supervised-wiki-ingestion/references/`):

| File | Role |
|------|------|
| `references/charter.example.yaml` | Editorial charter: scope include/exclude, scoring dimensions + weights, thresholds (admit/reject → gray zone), routing destinations, calibration policy, few-shot examples, amendments log |
| `references/manifest.example.jsonl` | Review manifest: `run_header` line + per-doc entries (briefing, dimension scores + composite, proposed_action, claims, decision/decision_source, audit sampling flags) |
| `references/schemas.py` | Pydantic sketch: `TriageOutput`, `DimensionScores`, `Claim`, `ManifestDocEntry`, `ManifestRunHeader`, `Charter`, `Thresholds.route()`, `agreement_rate()` |

**Initial signals** (extracted, not interpreted):
- Verbs: "evaluar", "clasificar", "filtrarlo pre-ingestion" → feature/enrichment, not a bug.
- Named entities: `wikitoolkit build`, LLM Wiki, GraphIndex, HITL, intent router, Karpathy gist (LLM wiki / 3-layer architecture).
- Components: `parrot.knowledge.wiki`, `parrot.knowledge.pageindex`, `parrot.knowledge.graphindex`, CLI.
- Acceptance criteria provided: no (brainstorm level).

---

## 1. Synthesis Summary

The request asks for a **supervised (assisted) ingestion mode** for the LLM
Wiki so that document corpora — meetings, summaries, "corporate digital life"
— are triaged *before* they become wiki pages, instead of the admit-everything
behaviour of today's `wikitoolkit build`. Research confirms the premise:
`build` (`packages/ai-parrot/src/parrot/knowledge/wiki/cli.py::build`) is
deterministic and offline by documented design, and its `_ingest_files` helper
admits every scanned file with staleness as the only gate. The LLM ingest
plane already exists and is the natural host: `WikiIngestOrchestrator.ingest`
(`wiki/ingest.py`) delegates to `TwoStepIngester`
(`pageindex/ingest.py`), which already runs a lightweight-model analysis step
and even accepts a `hint` parameter that a triage briefing can feed. The
proposal is therefore additive: a new charter-driven `IngestTriageRouter`
(modeled on the cascade pattern of `IntentRouterMixin`), a JSONL review
manifest with `--dry-run` / `--review` / `--auto` + stratified audit sampling,
and a new `wikitoolkit ingest` command for document folders — leaving `build`
untouched for code repositories. Configuration hooks (`WikiConfig`'s dual
`lightweight_model`/`model` tiers), structured outputs
(`StructuredOutputConfig` / `ask_structured`), the SQLite source manifest, the
bookkeeper audit trail, and grounding for the novelty score are all already in
place, which keeps the scope well-bounded.

---

## 2. Codebase Findings

> All entries are grounded in the research findings persisted at
> `sdd/state/FEAT-402-supervised-wiki-ingestion/findings/`. Each cites the
> finding ID(s) that justify its inclusion. **No fabricated paths or symbols.**
> Line numbers refer to `main` @ `e4724a0e` (2026-07-30).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/pyproject.toml` | `[project.scripts]` | 110-115 | `wikitoolkit = parrot.knowledge.wiki.cli:main` entry point | F001 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | `build` | 606-738 | unsupervised build: scan → `_ingest_files` → export | F001 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | `_ingest_files` | 264-326 | admits everything; only staleness gate | F002 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | `scan_repository` + suffix/size constants | 1-80 | deterministic offline scanner (no LLM by design) | F003 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` | `WikiIngestOrchestrator.ingest` | 69-301 | LLM ingest pipeline; insertion point for the triage gate | F004 |
| 6 | `packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py` | `TwoStepIngester.ingest(content, hint)` | 43-108 | light CoT + heavy `ask_structured`; `hint` accepts triage briefing | F004 |
| 7 | `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | `WikiConfig`, `WikiPageCategory` | 25-135 | dual model tiers, categories, validator precedent; home for charter config | F005 |
| 8 | `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | `SourceCollectionManager` | 40-480 | SQLite manifest (`add_source`/`is_stale`/`mark_ingested`); decision columns land here | F006 |
| 9 | `packages/ai-parrot/src/parrot/models/outputs.py` | `StructuredOutputConfig` | 67 | structured-output config consumed by `clients/base.py:1476-1640` | F007 |
| 10 | `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | `IntentRouterMixin`, `_KEYWORD_STRATEGY_MAP` | 1-60 | cascade-routing pattern to mirror (fast path → LLM) | F008 |
| 11 | `packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py` | `WikiBookkeeper.log_operation` | 175 | audit log for admission decisions | F011 |
| 12 | `packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py` + `cli.py::ground` | grounding evaluator | — | reusable machinery for the `novelty` dimension | F010 |

### 2.2 Constraints Discovered

- **`build` is documented as deterministic and offline.** Its docstring and
  `repo_scan.py`'s ("no LLM, no embeddings") make the offline guarantee part
  of the contract; a git post-commit hook depends on it being fast.
  *Implication*: supervised triage must be **opt-in** — a new command
  (`wikitoolkit ingest`) or explicit flag — never a default change to `build`.
  *Evidence*: F001, F003

- **Async-first + Pydantic are non-negotiable repo rules.** All new public
  methods async; no blocking I/O in async contexts (existing code offloads
  SQLite/hash work via `asyncio.to_thread`); Pydantic models for all data
  structures; Google-style docstrings; `uv` for packaging.
  *Implication*: HITL prompts (questionary is blocking) must run *outside* the
  async pipeline — the manifest-file flow does this naturally.
  *Evidence*: F004, F006, CLAUDE.md

- **Dependencies for the TUI already exist.** `click`, `rich`, `questionary`
  are declared in `pyproject.toml`; no new runtime deps required.
  *Evidence*: F009

- **The source manifest is SQLite with a migration precedent.** New columns
  (destination, decision_source, charter_version) must follow the
  `_migrate_json_manifest` migration pattern so existing wikis keep working.
  *Evidence*: F006

- **`wiki/cli.py` is a hot file (8+ commits in 3 weeks).** Long-lived branches
  touching it will conflict. Keep changes additive (new modules; one new
  command registration) and rebase frequently.
  *Evidence*: F012

- **SDD process constraints.** Proposal/spec/tasks must be committed to `dev`;
  FEAT/TASK ids allocated via `scripts/sdd/reserve_ids.py` (FEAT-387), never
  hand-numbered.
  *Evidence*: F012

### 2.3 Recent History (Relevant)

See F012 for the full table. Highlights: `e9ea0378` (wiki CLI authoring
surface — `remember`/`note`/`link` + audit), `09fe7df6` (grounding evaluator),
`a76413d6` (LLM-typed knowledge extraction in GraphIndex), `1d158c2f`
(codex/gemini wiki integrations). The subsystem is under active development by
Jesus, Javier León, and Claude-driven sessions — no dormant-code risk, but
high merge pressure.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`parrot/knowledge/wiki/charter.py`** — `Charter` Pydantic model + YAML
  loader/validator (weights sum to 1.0, `reject < admit`), sha256 fingerprint,
  amendments log. Adapted from `references/schemas.py` + `charter.example.yaml`.
- **`parrot/knowledge/wiki/triage.py`** — `IngestTriageRouter`: cheap-first
  cascade (hash/dup/size heuristics → lightweight-model `TriageOutput` via
  structured output → heavy-model escalation only in gray zone). Emits
  `DimensionScores` (density/novelty/durability); code computes the weighted
  composite; `Thresholds.route()` yields admit/defer/reject bands; LLM refines
  within the band (`extract` with claims; `sensitive` flag forces discard).
  Novelty backed by the store's search plane / grounding (F010).
- **`parrot/knowledge/wiki/review.py`** — manifest layer: `ManifestRunHeader`
  + `ManifestDocEntry` JSONL writer/reader, stratified audit sampler
  (near-threshold + uniform fractions), `agreement_rate()`, gray-zone widening
  per charter `calibration` policy.
- **`wikitoolkit ingest <folder>`** (new command in `wiki/cli.py`) — modes:
  `--dry-run` (emit manifest, decisions null), `--review <manifest.jsonl>`
  (apply human-edited decisions), `--interactive` (questionary per-doc for
  small batches), `--auto` (thresholds decide; audit sample flagged for
  post-hoc review), `--charter <path>`.
- **Tests** — `tests/knowledge/wiki/test_charter.py`, `test_triage.py`,
  `test_review.py`, CLI tests alongside existing `tests/knowledge/wiki/test_cli.py`.

### What Changes

- **`wiki/models.py`::`WikiConfig`** — add `charter_path: Optional[Path]` and
  triage defaults (thresholds/calibration fall back to charter). *Evidence*: F005
- **`wiki/ingest.py`::`WikiIngestOrchestrator.ingest`** — accept an optional
  pre-computed `TriageOutput`/decision; forward `briefing` as the
  `TwoStepIngester` `hint` so triage work is reused, not repeated. *Evidence*: F004
- **`wiki/sources.py`::`SourceCollectionManager`** — new manifest columns:
  `destination`, `decision_source`, `charter_version`, `composite_score`
  (with migration). *Evidence*: F006
- **`wiki/bookkeeper.py` usage** — log `TRIAGE`/`ADMIT`/`ARCHIVE`/`DISCARD`
  operations so `wikitoolkit audit` shows admission history. *Evidence*: F011
- **`wiki/cli.py`** — register the `ingest` command (additive; ~1 import + 1
  command block). *Evidence*: F001, F012

### What's Untouched (Non-Goals)

- `wikitoolkit build` and `repo_scan.py` — code-repo path stays deterministic,
  offline, unsupervised (explicitly per F003 contract).
- GraphIndex builder/extractors — only *consumed* (grounding/novelty), not
  modified.
- Query/search plane (`search.py`, `store.py` read paths), `query`/`page`/
  `related` commands.
- `IntentRouterMixin` itself — pattern donor only.
- Archive destination as a *separate storage plane* — v1 models `archive` as a
  manifest destination + excluded-from-wiki flag; a searchable archive plane
  is future work (see §5).

### Patterns to Follow

- Dual-adapter cascade + `hint` of `TwoStepIngester`; `lightweight_model` /
  `model` tiers of `WikiConfig`. *Evidence*: F004, F005
- `ask_structured` / `StructuredOutputConfig` for `TriageOutput`. *Evidence*: F007
- Keyword-fast-path-then-LLM + typed decision/trace models from
  `IntentRouterMixin`. *Evidence*: F008
- `replace_source_slice` idempotence (re-review must not duplicate pages);
  `asyncio.to_thread` for sync I/O; `_migrate_json_manifest`-style migration.
  *Evidence*: F002, F004, F006
- `WikiBookkeeper.log_operation` + `audit` command for decision trail. *Evidence*: F011

### Integration Risks

- **Double-LLM cost on large corpora**: triage + TwoStepIngester per admitted
  doc. *Mitigation*: cascade (heuristics kill duplicates/oversize free;
  lightweight model for triage; heavy only in gray zone) and briefing→`hint`
  reuse. *Evidence*: F004
- **Blocking TUI in async pipeline**: questionary prompts are sync.
  *Mitigation*: interactive mode collects decisions *before* launching the
  async apply-pipeline; manifest flow avoids the problem entirely. *Evidence*: F009, CLAUDE.md
- **Manifest schema migration**: older wikis must open cleanly.
  *Mitigation*: follow `_migrate_json_manifest` precedent + defaulted columns.
  *Evidence*: F006
- **Merge pressure on `wiki/cli.py`**: hot file. *Mitigation*: new logic lives
  in new modules; cli.py change is a single additive command block. *Evidence*: F012
- **Charter drift / reproducibility**: decisions must be auditable against the
  policy that produced them. *Mitigation*: charter sha256 + version in every
  `run_header`; amendments only via versioned charter edits
  (`autotune: propose`, never `apply` in v1). *Evidence*: F011, references

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `wikitoolkit build` is unsupervised: only staleness/suffix/size gates, no content evaluation | F001, F002, F003 | high | direct read of `build`, `_ingest_files`, `repo_scan.py` |
| C2 | `WikiIngestOrchestrator` → `TwoStepIngester` is the LLM ingest plane and accepts a `hint` usable for the triage briefing | F004 | high | direct read of both files; `hint` param confirmed |
| C3 | Structured outputs are available at client and adapter level | F007 | high | `StructuredOutputConfig` (outputs.py:67), `ask_structured` in-subsystem |
| C4 | `IntentRouterMixin` is a suitable pattern donor for cascade triage | F008 | high | module read; routes queries not docs (pattern, not reuse) |
| C5 | click/rich/questionary suffice for the HITL TUI (no new deps) | F009 | high | pyproject grep |
| C6 | Grounding machinery can back the `novelty` score | F010 | medium | command + module exist; API fit for scoring not yet traced call-by-call |
| C7 | Manifest columns can be added with a safe migration | F006 | medium | migration precedent exists; exact SQLite schema change not yet drafted |
| C8 | No existing `wikitoolkit ingest` command name collision | F001 | high | full `@wiki.command` inventory of cli.py (15 commands, no `ingest`) |
| C9 | Keeping `build` untouched preserves the post-commit hook contract | F003, F012 | high | docstrings + hook commits (`cd6ac5e6`) |
| C10 | Archive-as-manifest-destination (no separate plane) is acceptable for v1 | — | low | design choice from brainstorm; no code evidence either way — flagged in §5 |

Distribution: **7** high, **2** medium, **1** low.

The single low-confidence claim (C10) affects the routing model, not the
localization or feasibility; overall confidence stays **high**.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Where does HITL live given async-first?** — *Resolved*: manifest-file
  flow (`--dry-run` → edit → `--review`) as primary; blocking interactive mode
  only as an explicit small-batch option, run before the async pipeline.
  *Resolves claims*: C5
- [x] **New command vs. changing `build`?** — *Resolved*: new
  `wikitoolkit ingest` command; `build` keeps its offline contract.
  *Resolves claims*: C1, C9
- [x] **Uniform vs. stratified audit sample?** — *Resolved*: stratified
  (60% near-threshold / 40% uniform, configurable in charter) — uniform-only
  oversamples easy cases and inflates agreement.

### Unresolved (defer to spec / implementation)

- [ ] **Claim-level admission (`extract`) in v1 or fast-follow?** — *Owner*: Jesus
  *Blocks claims*: C2 (scope of orchestrator change)
  *Plausible answers*: a) v1 document-level + `extract` behind a flag ·
  b) full claim-level from day one (bigger orchestrator surface)
- [ ] **Where do `archive` destinations physically live?** — *Owner*: Jesus
  *Blocks claims*: C10
  *Plausible answers*: a) manifest-only flag (v1 sketch) · b) `archive`
  category pages excluded from query ranking · c) separate SQLite table/plane
- [ ] **Novelty via grounding vs. store FTS/embedding search?** — *Owner*: tbd
  *Blocks claims*: C6
  *Plausible answers*: a) `grounding.py` evaluator · b) `store.search` top-k
  similarity as cheap proxy · c) both, cascade
- [ ] **Where are human decisions persisted for the few-shot loop?** — *Owner*: tbd
  *Plausible answers*: a) charter `examples`/`examples_file` (per brainstorm) ·
  b) `wikitoolkit remember` memories plane (F011) — reuse existing surface
- [ ] **Default thresholds for a corporate-docs charter** (0.75/0.35 in the
  reference) — calibrate on a real corpus during implementation. *Owner*: Jesus

---

## 6. Recommended Next Step

**`/sdd-spec supervised-wiki-ingestion`** — *Rationale*: localization is
high-confidence (C1-C5, C8-C9), the reference schemas already fix the data
contracts, and the scope decomposes cleanly into 4-6 atomic tasks (charter →
triage → review/manifest → CLI → orchestrator wiring → migration). No
architectural fork remains that would justify a brainstorm round.

### Alternatives

- **`/sdd-brainstorm supervised-wiki-ingestion`** — only if the archive-plane
  question (C10) or claim-level-v1 question is considered architectural enough
  to explore first.
- **`/sdd-task`** — not suitable: multi-module feature, not a localized fix.
- **Manual review** — read `references/schemas.py` against
  `parrot/knowledge/wiki/models.py` conventions before spec-ing if naming
  consistency matters (e.g. `WikiPageCategory` vs. triage categories).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| Source (raw) | `sdd/state/FEAT-402-supervised-wiki-ingestion/source.md` |
| Findings (digests) | `sdd/state/FEAT-402-supervised-wiki-ingestion/findings/F001-*.md` … `F012-*.md` |
| Reference schemas | `sdd/state/FEAT-402-supervised-wiki-ingestion/references/{charter.example.yaml, manifest.example.jsonl, schemas.py}` |
| State checkpoints / research plan / synthesis JSON | not produced — research ran interactively in a Cowork session, not via `/sdd-proposal` |

**Budget consumed** (approximate; interactive session, no hard budget):
- Files read (full or partial): 14
- Grep/inventory calls: 13
- Git calls: 2 (clone + log)
- Repo snapshot: `main` @ `e4724a0e`, shallow clone depth 50, 2026-07-30
- Truncated: **no**

**Mode determination**: `enrichment` (no negation/bug language in source; the
request describes new capability).

**Verification pass**: every path/symbol/line cited in §2.1 was re-checked
against the clone with grep before publication (see session log).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | Claude (Cowork session), following `proposal.md` template v1.0 |
| Template source | user-supplied `proposal.md` (uploaded 2026-07-30) |
| Research method | interactive clone + read/grep (not `/sdd-proposal` automation) |
| Schema versions | reference schemas v0 (brainstorm sketch, pre-spec) |
| Operator | Jesus (jesuslarag@gmail.com) |
