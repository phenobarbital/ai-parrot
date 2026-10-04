---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wikitoolkit, lint, knowledge-graph, adr, mcp, data-integrity]
---

# Feature Specification: wikitoolkit lint

**Feature ID**: FEAT-625
**Date**: 2026-10-03
**Author**: Jesus (with Claude)
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The wikitoolkit knowledge graph has no integrity gate that anyone can run.
That covers the SQLite plane, the ArangoDB backend, the markdown/OKF export,
and the memories/ADR plane.

Some pieces exist but none of them close the gap:

- The store has integrity helpers: `broken_edges`, `orphan_sources` and
  `missing_bodies`.
- `LLMWikiToolkit.lint()` exists, but it is Python-only. Neither the CLI nor
  the MCP server exposes it, and its `fix` parameter is a documented no-op.
- Nothing checks for:
  - duplicate slugs;
  - frontmatter schema;
  - edge symmetry;
  - ADR status consistency;
  - contradictions between memories.
- The export writes outgoing `relates_to` only, so "related" is one-way.

The graph is the agents' durable memory. When it rots, agents get confidently
wrong context: stale memories, superseded ADRs presented as current, and
dangling links.

### Goals

- G1: A shared, backend-agnostic lint engine.
  - It has rules, findings, a runner and reports.
  - It is generalized from `okf/lint.py`.
  - OKF lint becomes one rule pack on top of it.
- G2: Rule packs for four surfaces:
  - the plane: SQLite, ArangoDB, and any `BaseWikiStore`;
  - the exported markdown wiki;
  - memories;
  - ADRs.
- G3: Report by default. `--fix` is opt-in and applies only deterministic,
  idempotent, safe fixes, and it never deletes anything. The fixes are:
  - add inverse `related` edges;
  - rebuild the FTS index and repair `meta`;
  - re-export drifted pages;
  - repair derivable frontmatter fields.
- G4: Unfixable findings are routed to three destinations:
  - the work ledger, as idempotent issues keyed by fingerprint;
  - a JSON and markdown report;
  - `wikitoolkit note` on the affected page.
- G5: Exposed as `wikitoolkit lint` (CLI) and `wiki_lint` (MCP tool).
- G6: An opt-in LLM contradiction pass (`--llm`) with a hard pair cap.
- G7: The deterministic lint runs in CI with `--fail-on error`.

### Non-Goals (explicitly out of scope)

- Deleting pages or edges, or merging duplicates automatically. Duplicates
  are reported only.
- Running in the post-commit hook. The decision was CI only.
- A per-backend query catalogue (SQL/AQL). It was rejected in the
  brainstorm (Option C): duplicate rules, and it bypasses store triggers and
  CAS. See `sdd/proposals/wikitoolkit-lint.brainstorm.md`.
- Keeping `WikiLintReport`'s flat-list shape. This is a hard cut; every
  caller is updated in this feature.

---

## 2. Architectural Design

### Overview

This is the brainstorm's Option A: a shared rule-pack engine.

The new package `parrot/knowledge/lint/` holds a backend-neutral core:

- `Finding`: rule id, severity (`info` | `warning` | `error`), subject ids,
  message, `fixable`, and a stable `fingerprint`.
- The `LintRule` protocol: `check(ctx)`, plus an optional `fix(ctx, finding)`.
- `LintContext`: lazily caches the pages, edges, sources, decision records
  and export dir for one run.
- `LintRunner`: selects packs, runs checks, applies fixes in `--fix` mode,
  re-checks, routes the residue, and renders the reports.

Rule packs:

- **`okf`**: today's four checks, ported with identical output (parity tests).
- **`plane`**:
  - `broken-link`
  - `orphan-page`
  - `orphan-source`
  - `duplicate-slug`
  - `missing-body`
  - `stale-source`
  - `asymmetric-related`
  - `fts-index-drift`
- **`export`**:
  - `frontmatter-schema`
  - `export-drift`
  - `export-dangling-relates-to`
- **`adr`**:
  - `adr-superseded-active`
  - `adr-supersedes-broken`
  - `adr-conflict` (two accepted ADRs on the same symbol, where neither
    supersedes the other)
- **`memory`**:
  - `memory-dangling-link`
  - `stale-memory`
- **`llm`** (opt-in): `contradiction-llm`.

`LLMWikiToolkit.lint`, the CLI and the MCP tool are thin adapters over
`LintRunner`.

Decisions carried from the brainstorm:

- **`references` counts as a symmetric `related` relation.** When A→B
  (`references` or `related`) exists without B→A, `asymmetric-related`
  fires. `--fix` adds B→A with rel `related` and provenance `asserted`,
  attributed to `lint`, and logs it as `LINT_FIX` in the audit log.
- **The relation-inverse table** maps:
  - `references` and `related` → `related`;
  - `supersedes` → `superseded_by`.

  `contains`, `calls`, `defines`, `imports`, `mentions` and `depends_on` are
  hierarchical or directed and are excluded. The table is configurable.
- **Scope violation is the same as a broken link.** There is no separate
  scope policy. A link whose target does not resolve in the active wiki or
  namespace is `broken-link` (severity `error`). On a `FederatedWikiStore`
  the existing cross-namespace classification decides whether a target
  resolves.
- **Duplicate slug.** For every page, compute the slug from its title with
  the existing OKF `_slugify`. If that slug already exists for another page
  in the wiki (same namespace), both pages are reported as `duplicate-slug`
  (`warning`). This is reported only, never auto-fixed.
- **Stale memory.** A memory page whose linked page's `content_hash`
  changed after the memory's `updated_at`, or whose linked page is gone, is
  reported as `stale-memory` with severity **warning**.
- **CI.** A step in the existing `test-wiki-extras` job builds a plane over
  a fixture repo and runs `wikitoolkit lint --fail-on error`.
- **Contradiction semantics** combine three sources:
  - deterministic rules;
  - ADR status rules;
  - LLM judgement, opt-in.

**LLM pass (decided here).**

- **Model.** It resolves the model the same way `remember --extract` does
  (`cli.py:3735–3753`), but checks `WIKI_LINT_LLM` first. The order is:
  1. `--llm-model`
  2. `WIKI_LINT_LLM`
  3. `WIKI_EXTRACT_LLM`
  4. the coding-agent auto-detect, unless `PARROT_NO_AUTO_LLM=1`
- **Client.** `LLMFactory.create(spec, model_args={"temperature": 0.0})`.
- **Candidate pairs.** Memories and accepted ADRs that link the same page,
  ranked by shared links.
- **Pair cap.** `--llm-max-pairs` defaults to **50**.
- **Failure.** A per-call timeout or provider failure records an
  `llm-skipped` info finding. It never fails the deterministic run.

### Component Diagram

```
CLI `wikitoolkit lint` ─┐
MCP `wiki_lint` ────────┼─→ LintRunner ──→ LintContext ──→ BaseWikiStore (sqlite|arango|pg|federated)
LLMWikiToolkit.lint ────┘       │               ├──→ SourceCollectionManager.is_stale
                                │               ├──→ decisions/ (DecisionRecord)
                                │               └──→ export dir (frontmatter parse)
                                ├─→ rule packs: okf · plane · export · adr · memory · llm
                                ├─→ fixes → store.add_edges / rebuild_index / export_okf_bundle  (+ LINT_FIX audit)
                                └─→ routing → LedgerService.open_issue · report.json/.md · page notes
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `okf/lint.py` | modifies | Becomes the `okf` pack. `lint_knowledge_base()` stays as a parity wrapper, so the OKF tests keep passing. |
| `LLMWikiToolkit.lint` | modifies | Adapter over `LintRunner`; `fix` becomes real. |
| `WikiLintReport` | modifies (hard cut) | Replaced by `LintReport` from the engine. It stays exported, as an alias to the new model. |
| `BaseWikiStore` | extends | Adds `rebuild_index()`. The default is a no-op; SQLite runs the FTS5 `'rebuild'`. |
| `wiki/cli.py` | extends | New `lint` command. |
| `wiki/tools.py` | extends | New `WikiLintTool`, appended in `create_wiki_tools`. |
| `LedgerService.open_issue` | uses | `discovered_from="lint:<rule-id>"`. Deduplicated by fingerprint in the body marker. |
| `WikiBookkeeper.log_operation` | uses | `LINT`, `LINT_FIX`. |
| `export_okf_bundle` | uses | Re-export when the fix is `export-drift`. |
| `.github/workflows/ci.yml` | modifies | Adds the lint step to `test-wiki-extras`. |

### Data Models

```python
Severity = Literal["info", "warning", "error"]

class Finding(BaseModel):
    rule_id: str
    severity: Severity
    subjects: list[str]          # concept_ids / source_ids / file paths
    message: str
    fixable: bool = False
    fingerprint: str             # sha1(rule_id + sorted(subjects)), stable across runs
    data: dict[str, Any] = {}

class FixResult(BaseModel):
    fingerprint: str
    applied: bool
    detail: str

class LintReport(BaseModel):
    wiki_name: str
    backend: str
    rules_run: list[str]
    findings: list[Finding]      # remaining after fixes
    fixed: list[FixResult]
    counts: dict[str, int]       # by severity
    started_at: str
    duration_ms: int

class LintOptions(BaseModel):
    rules: list[str] | None = None        # pack or rule ids; None = all deterministic packs
    skip: list[str] = []
    fix: bool = False
    llm: bool = False
    llm_model: str | None = None
    llm_max_pairs: int = 50
    ledger: bool = True
    notes: bool = True
    ledger_cap_per_rule: int = 20
    fail_on: Severity | None = "error"
    export_dir: Path | None = None
```

### New Public Interfaces

```python
from parrot.knowledge.lint import LintRunner, LintOptions, LintReport, Finding, LintRule

runner = LintRunner(store, root=root, config=config)
report: LintReport = await runner.run(LintOptions(fix=True))
```

```
wikitoolkit lint [--path P] [--backend B] [--ns NAME]
                 [--rules R,...] [--skip RULE...] [--fix]
                 [--llm] [--llm-model SPEC] [--llm-max-pairs N]
                 [--report json|md] [--output FILE]
                 [--ledger/--no-ledger] [--notes/--no-notes]
                 [--fail-on error|warning|none] [--json]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: lint engine core | yes | models + `LintRule` protocol + `LintRunner` as below | — |
| M2: okf pack port | yes | output parity with `lint_knowledge_base` | — |
| M3: plane pack | yes | rule ids + inverse table + slug rule fixed in §2 | — |
| M4: store `rebuild_index` | yes | signature fixed; SQLite = FTS5 `'rebuild'` on `pages_fts`, `symbols_fts` | — |
| M5: export pack | yes | frontmatter model = keys of `page_frontmatter` | — |
| M6: adr + memory packs | yes | rules fixed in §2 | — |
| M7: llm pack | no | prompt and response schema need design judgement | prompt design |
| M8: routing | yes | ledger/report/notes contract fixed in §2 | — |
| M9: adapters (toolkit, CLI, MCP) | yes | signatures below | — |
| M10: CI step + docs | yes | job `test-wiki-extras` | — |

### Module 1: Lint engine core
- **Path**: `packages/ai-parrot/src/parrot/knowledge/lint/{__init__,models,rule,context,runner}.py` (new)
- **Responsibility**: the models, the rule protocol, the context cache, and the runner.
- **Depends on**: `BaseWikiStore` (`wiki/store.py:525`).
- **Interface Skeleton**:
  ```python
  # lint/rule.py (new)
  class LintRule(Protocol):
      rule_id: str
      pack: str
      default_severity: Severity
      async def check(self, ctx: "LintContext") -> list[Finding]:
          """Return findings; never mutate the store."""
      async def fix(self, ctx: "LintContext", finding: Finding) -> FixResult | None:
          """Apply an idempotent safe fix, or return None if this rule never fixes."""

  def make_fingerprint(rule_id: str, subjects: Sequence[str]) -> str:
      """sha1 of rule_id + sorted subjects; stable across runs."""

  # lint/context.py (new)
  class LintContext:
      """Per-run lazy cache over the store and auxiliary sources."""
      def __init__(self, store: BaseWikiStore, *, root: Path | None, config: Any | None,
                   options: LintOptions) -> None: ...  # BaseWikiStore verified: wiki/store.py:525
      async def pages(self) -> list[dict[str, Any]]: ...   # store.dump_pages verified: wiki/store.py:590
      async def edges(self) -> list[dict[str, Any]]: ...   # store.dump_edges verified: wiki/store.py:593
      async def page_ids(self) -> set[str]: ...
      def invalidate(self) -> None: """Drop caches after fixes."""

  # lint/runner.py (new)
  class LintRunner:
      def __init__(self, store: BaseWikiStore, *, root: Path | None = None, config: Any | None = None,
                   rules: Sequence[LintRule] | None = None) -> None: ...
      async def run(self, options: LintOptions) -> LintReport:
          """Check → (fix → invalidate → re-check) → route → log LINT. Refuses fix on schema mismatch."""
      def exit_code(self, report: LintReport, fail_on: Severity | None) -> int:
          """0 if no finding at or above fail_on, else 1."""

  def default_rules() -> list[LintRule]:
      """All deterministic packs (okf, plane, export, adr, memory); llm only added when options.llm."""
  ```

### Module 2: OKF pack port
- **Path**: `packages/ai-parrot/src/parrot/knowledge/lint/packs/okf.py` (new); modifies `pageindex/okf/lint.py:91`
- **Responsibility**: port the four OKF checks into rules. `lint_knowledge_base()` keeps its signature and its `LintReport`/`LintFinding` output, so `OKFToolkit.lint_knowledge_base` (`okf/tools.py:287`) and the existing tests stay unchanged.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # lint/packs/okf.py (new)
  def okf_findings(graph: KnowledgeGraph, tree: dict, content_store: NodeContentStore,
                   stale_days: int = 90) -> list[Finding]:
      """Pure; the four OKF checks expressed as engine Findings."""
  # pageindex/okf/lint.py:91 (modifies) — lint_knowledge_base(...) -> LintReport
  #   now builds its LintReport from okf_findings(); output identical.
  ```

### Module 3: Plane pack
- **Path**: `packages/ai-parrot/src/parrot/knowledge/lint/packs/plane.py` (new)
- **Responsibility**: the rules `broken-link`, `orphan-page`, `orphan-source`, `duplicate-slug`, `missing-body`, `stale-source`, `asymmetric-related` (fixable) and `fts-index-drift` (fixable).
  - Uses the store fast-paths `broken_edges`, `orphan_sources` and `missing_bodies` when they are available.
  - `duplicate-slug` uses `_slugify` from `pageindex/okf/concept_id.py:31`.
- **Depends on**: M1, M4
- **Interface Skeleton**:
  ```python
  INVERSE_RELATIONS: dict[str, str] = {"references": "related", "related": "related",
                                       "supersedes": "superseded_by"}
  class BrokenLinkRule: rule_id = "broken-link"           # store.broken_edges verified: wiki/store.py:2354
  class OrphanPageRule: rule_id = "orphan-page"
  class OrphanSourceRule: rule_id = "orphan-source"       # store.orphan_sources verified: wiki/store.py:2344
  class DuplicateSlugRule: rule_id = "duplicate-slug"     # _slugify verified: pageindex/okf/concept_id.py:31
  class MissingBodyRule: rule_id = "missing-body"         # store.missing_bodies verified: wiki/store.py:2364
  class StaleSourceRule: rule_id = "stale-source"         # SourceCollectionManager.is_stale verified: wiki/sources.py:532
  class AsymmetricRelatedRule:
      rule_id = "asymmetric-related"
      async def fix(self, ctx, finding) -> FixResult:
          """store.add_edges([(dst, src, INVERSE_RELATIONS[rel], "asserted")]) + LINT_FIX audit."""  # add_edges verified: wiki/store.py:547
  class FtsIndexDriftRule:
      rule_id = "fts-index-drift"
      async def fix(self, ctx, finding) -> FixResult: """await store.rebuild_index()."""
  ```

### Module 4: Store `rebuild_index`
- **Path**: modifies `wiki/store.py` (base and SQLite); the Arango, Postgres, InMemory and Federated stores inherit the no-op default.
- **Responsibility**: a public index rebuild and an FTS drift probe.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # wiki/store.py BaseWikiStore (modifies, near :600)
  async def rebuild_index(self) -> dict[str, Any]:
      """Rebuild derived search indexes and repair `meta`; default no-op → {"rebuilt": []}."""
  async def index_drift(self) -> dict[str, int]:
      """Return row-count mismatches between content and FTS tables; default {}."""
  # SQLiteWikiStore: runs INSERT INTO pages_fts(pages_fts) VALUES('rebuild') (pattern verified: wiki/store.py:1467)
  #   for pages_fts/symbols_fts and re-sets SCHEMA_VERSION in meta (wiki/store.py:50).
  ```

### Module 5: Export pack
- **Path**: `packages/ai-parrot/src/parrot/knowledge/lint/packs/export.py` (new)
- **Responsibility**:
  - `frontmatter-schema`: a Pydantic `ExportFrontmatter` model with the keys `page_frontmatter` writes (`wiki/export.py:86`).
  - `export-drift`: page ids in the plane but not in the export, or the reverse, or a `timestamp` that differs from `updated_at`. Fixable by re-running `export_okf_bundle` (`wiki/export.py:125`).
  - `export-dangling-relates-to`.
  - The pack is skipped, with an info finding, when no export dir exists.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  class ExportFrontmatter(BaseModel):
      type: str; title: str; id: str; tags: list[str]; timestamp: str
      summary: str | None = None
      relates_to: list[dict[str, str]] | None = None
  class FrontmatterSchemaRule: rule_id = "frontmatter-schema"
  class ExportDriftRule: rule_id = "export-drift"   # fix → export_okf_bundle(store, output_dir, wiki_name)
  class ExportDanglingRelatesToRule: rule_id = "export-dangling-relates-to"
  ```

### Module 6: ADR and memory packs
- **Path**: `packages/ai-parrot/src/parrot/knowledge/lint/packs/{adr,memory}.py` (new)
- **Responsibility**:
  - `adr-superseded-active`: `source_status == "accepted"` while another ADR supersedes it.
  - `adr-supersedes-broken`: a `supersedes` target is missing (`error`).
  - `adr-conflict`: two accepted ADRs explain the same symbol and neither supersedes the other (`warning`).
  - `memory-dangling-link` (`error`).
  - `stale-memory` (**warning**).
  - Memory pages are `pages.origin == 'memory'`.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  class AdrSupersededActiveRule: rule_id = "adr-superseded-active"   # DecisionRecord.source_status verified: wiki/decisions/models.py:153
  class AdrSupersedesBrokenRule: rule_id = "adr-supersedes-broken"   # DecisionLink.relation verified: wiki/decisions/models.py:115
  class AdrConflictRule: rule_id = "adr-conflict"
  class MemoryDanglingLinkRule: rule_id = "memory-dangling-link"
  class StaleMemoryRule: rule_id = "stale-memory"; default_severity = "warning"
  ```

### Module 7: LLM pack
- **Path**: `packages/ai-parrot/src/parrot/knowledge/lint/packs/llm.py` (new)
- **Responsibility**: `contradiction-llm`. It uses the model resolution and pair cap from §2, asks for a JSON verdict (`{contradicts: bool, explanation}`), and degrades to an `llm-skipped` info finding on failure.
- **Depends on**: M1, `LLMFactory` (`cli.py:3747` import pattern)
- **Interface Skeleton**:
  ```python
  def resolve_lint_llm_spec(explicit: str | None) -> str | None:
      """--llm-model > WIKI_LINT_LLM > WIKI_EXTRACT_LLM > auto-detect (honours PARROT_NO_AUTO_LLM)."""
  class ContradictionLLMRule:
      rule_id = "contradiction-llm"
      def __init__(self, client: Any, max_pairs: int = 50, timeout_s: float = 30.0) -> None: ...
  ```

### Module 8: Routing
- **Path**: `packages/ai-parrot/src/parrot/knowledge/lint/routing.py` (new)
- **Responsibility**: send the remaining findings to three places.
  - **Ledger** (when `options.ledger`):
    - Only `warning`/`error` findings that are not fixable.
    - `kind="tech_debt"`, or `"bug"` for errors.
    - `discovered_from="lint:<rule_id>"`.
    - Deduplicated on the `<!-- lint-fp:<fingerprint> -->` marker in the body.
    - Over `ledger_cap_per_rule`, the rest are aggregated into one issue.
  - **Report files**: `report.json` and `report.md`, written to `--output`, defaulting to `<storage_dir>/lint/`.
  - **Page notes** (when `options.notes`): appended through the same path as the `note` command, attributed `by="lint"`. Deduplicated on the fingerprint.
- **Depends on**: M1, `LedgerService.open_issue` (`wiki/ledger/service.py:168`)
- **Interface Skeleton**:
  ```python
  class FindingRouter:
      def __init__(self, store: BaseWikiStore, *, root: Path | None, config: Any | None,
                   ledger: "LedgerService | None") -> None: ...
      async def route(self, report: LintReport, options: LintOptions) -> dict[str, int]:
          """Return counts {ledger_opened, ledger_deduped, notes_added, report_files}."""
  def render_markdown(report: LintReport) -> str: ...
  ```

### Module 9: Adapters (toolkit, CLI, MCP)
- **Path**: modifies `wiki/toolkit.py:415`, `wiki/models.py:302`, `wiki/cli.py` (a new command next to `status`, `:2143`), `wiki/tools.py:830`
- **Responsibility**:
  - `LLMWikiToolkit.lint(wiki_name, fix=False)` delegates to `LintRunner` and returns `LintReport.model_dump()`.
  - `WikiLintReport` becomes an alias of the engine's `LintReport`.
  - The CLI command uses the existing `path_option`/`ns_option` and store resolution, and exits with `runner.exit_code(...)`.
  - `WikiLintTool` (`wiki_lint`) defaults to `fix=False` and `llm=False`, and returns a compact summary plus the report path.
- **Depends on**: M1–M8
- **Interface Skeleton**:
  ```python
  # wiki/cli.py (new command)
  @wiki.command("lint")
  @path_option
  @ns_option
  def lint(path_, ns_opt, backend_opt, rules, skip, fix, llm, llm_model, llm_max_pairs,
           report_fmt, output, ledger, notes, fail_on, as_json) -> None:
      """Lint the wiki graph, export, memories and ADRs; --fix applies safe fixes."""
  # wiki/tools.py (new)
  class WikiLintTool(AbstractTool):
      name = "wiki_lint"
      """Lint the wiki knowledge graph and report broken links, duplicates, stale memories, ADR conflicts."""
  ```

### Module 10: CI step and docs
- **Path**: modifies `.github/workflows/ci.yml` (job `test-wiki-extras`, `:207`); new `docs/wiki/lint.md`
- **Responsibility**: build a plane over a small fixture and run `wikitoolkit lint --fail-on error --no-ledger --no-notes`. The docs list the rules, their severities and the fix behaviour.
- **Depends on**: M9

---

## 4. Test Specification

Tests live in `packages/ai-parrot/tests/knowledge/lint/` and run against `InMemoryWikiStore` and a temp SQLite plane.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_fingerprint_stable` | M1 | Same rule and subjects in any order give the same fingerprint. |
| `test_runner_fix_then_recheck` | M1 | A fixed finding is gone from `findings` and present in `fixed`. |
| `test_runner_refuses_fix_on_schema_mismatch` | M1 | `meta.schema_version` is not equal to `SCHEMA_VERSION`, so no writes happen. |
| `test_exit_code_fail_on` | M1 | Covers the error, warning and none thresholds. |
| `test_okf_parity` | M2 | The existing `test_okf_lint.py` and `test_okf_integration.py` cases stay green. |
| `test_broken_link_is_error` | M3 | An edge to an unknown dst gives `broken-link`, severity error. |
| `test_asymmetric_references_fix` | M3 | A→B `references` without B→A: the fix adds B→A `related`, provenance asserted. It is idempotent. |
| `test_contains_not_symmetrized` | M3 | `contains` edges never fire `asymmetric-related`. |
| `test_duplicate_slug` | M3 | Two pages whose titles slugify to the same slug give one finding with both subjects. |
| `test_fts_rebuild_fix` | M3/M4 | A drifted FTS on SQLite is repaired by `rebuild_index()`. |
| `test_frontmatter_schema_invalid` | M5 | A missing `id` gives `frontmatter-schema`. |
| `test_export_drift_fix` | M5 | The fix re-exports, and the re-check is clean. |
| `test_adr_superseded_active` | M6 | An accepted ADR that is superseded gets flagged. |
| `test_stale_memory_warning` | M6 | The linked page's `content_hash` changed, giving a warning. |
| `test_llm_skipped_on_failure` | M7 | A failing client gives an `llm-skipped` info finding, and the run still succeeds. |
| `test_llm_pair_cap` | M7 | At most `llm_max_pairs` calls are made. |
| `test_ledger_dedup` | M8 | A second run opens no duplicate issue. |
| `test_ledger_cap_aggregates` | M8 | More findings than the cap give one aggregate issue. |
| `test_cli_lint_json` | M9 | `CliRunner` exits with a non-zero code on an error finding. |
| `test_wiki_lint_tool_registered` | M9 | `create_wiki_tools` includes `wiki_lint`. |

### Integration Tests
| Test | Description |
|---|---|
| `test_lint_end_to_end_sqlite` | Build a fixture plane, seed defects, run `lint`, then `lint --fix`, then `lint` again. Only the non-fixable findings remain. |

---

## 5. Acceptance Criteria

- [ ] AC1: `wikitoolkit lint` exists, and its default run writes nothing to the store. Verified by store hashes before and after.
- [ ] AC2: `--fix` only adds edges, rebuilds indexes, re-exports or repairs frontmatter. It never deletes a page or an edge.
- [ ] AC3: Asymmetric `references`/`related` edges get an inverse `related` edge with provenance `asserted`, logged as `LINT_FIX`.
- [ ] AC4: Broken links, which also cover scope violations, have severity `error`.
- [ ] AC5: Duplicate slugs are detected by computing the slug and looking it up in the wiki.
- [ ] AC6: Stale memories have severity `warning`.
- [ ] AC7: It runs unchanged against SQLite, InMemory and ArangoDB through `BaseWikiStore`. ArangoDB is covered by a mocked or skipped live test.
- [ ] AC8: Unfixable findings reach the ledger (deduplicated), the report files and page notes. Each target can be turned off.
- [ ] AC9: `wiki_lint` is available through the MCP server.
- [ ] AC10: The LLM pass runs only with `--llm`, respects `--llm-max-pairs` (default 50), and never fails the deterministic run.
- [ ] AC11: The OKF lint tests pass unchanged.
- [ ] AC12: The CI `test-wiki-extras` job runs `wikitoolkit lint --fail-on error`.
- [ ] AC13: `docs/wiki/lint.md` documents every rule id, its severity and whether it is fixable.
- [ ] AC14: `ruff check` is clean, and the tests in §4 pass.

---

## 6. Codebase Contract

Paths are relative to `packages/ai-parrot/src/parrot/knowledge/` unless stated.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SCHEMA_VERSION   # wiki/store.py:525, :50
from parrot.knowledge.wiki.models import WikiLintReport                 # wiki/models.py:302 (lazy export wiki/__init__.py:63)
from parrot.knowledge.wiki.export import page_frontmatter, export_okf_bundle  # wiki/export.py:86, :125
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper             # wiki/bookkeeper.py:175 log_operation
from parrot.knowledge.wiki.ledger.service import LedgerService          # wiki/ledger/service.py:116 from_root, :168 open_issue
from parrot.knowledge.pageindex.okf.lint import LintFinding, LintReport, lint_knowledge_base  # okf/lint.py:46,63,91
from parrot.knowledge.pageindex.okf.concept_id import _slugify          # okf/concept_id.py:31
from parrot.clients.factory import LLMFactory                           # used at wiki/cli.py:3747
```

### Existing Class Signatures
```python
# wiki/store.py
class BaseWikiStore(ABC):                                      # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...   # :544
    async def add_edges(self, edges: list[tuple]) -> int: ...  # :547  tuples (src, dst, rel, provenance)
    async def dump_pages(self) -> list[dict[str, Any]]: ...    # :590
    async def dump_edges(self) -> list[dict[str, Any]]: ...    # :593
    async def orphan_sources(self) -> list[str]: ...           # :600
    async def broken_edges(self) -> list[dict[str, Any]]: ...  # :603
    async def rebuild_from_tree(...)                           # :675
# SQLite: orphan_sources :2344, broken_edges :2354, missing_bodies :2364; FTS 'rebuild' pattern :1467 (inside _migrate_fts :1418)
# edges PK(src,dst,rel); provenance ∈ extracted|inferred|asserted; pages.origin ∈ ingest|memory|authored

# wiki/toolkit.py:415
async def lint(self, wiki_name: str, fix: bool = False) -> dict[str, Any]: ...  # fix is a no-op today; builds WikiLintReport at :484

# pageindex/okf/lint.py
class LintFinding(BaseModel):  # :46  kind Literal[orphan|broken_link|missing_concept|stale]; severity Literal[warning|error]
class LintReport(BaseModel):   # :63  tree_name, orphans, broken_links, missing_concepts, stale_claims, total_*
def lint_knowledge_base(graph: KnowledgeGraph, tree: dict, content_store: NodeContentStore, stale_days: int = 90) -> LintReport: ...  # :91
# pageindex/okf/tools.py:287  OKFToolkit.lint_knowledge_base(self, stale_days: int = 90) -> dict

# wiki/export.py:86   page_frontmatter(page: dict[str, Any], relates_to: list[dict[str, str]]) -> str  (keys: type,title,id,tags,timestamp,summary?,relates_to?)
# wiki/sources.py:532 SourceCollectionManager.is_stale(source_id)
# wiki/tools.py:807   create_wiki_tools(store, root=None, config=None, ledger_service=None) -> list[AbstractTool]; list literal `tools = [` at :830, `return tools` at :851
# wiki/decisions/models.py:153 DecisionRecord.source_status ∈ unknown|proposed|accepted|rejected|deprecated|superseded; :115 DecisionLink.relation ∈ explains|supported_by|supersedes
# wiki/cli.py:1446 click group `wiki`; `status` command :2143-2147; `link` :4033; LLM spec resolution for --extract :3735-3753
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AsymmetricRelatedRule.fix` | `BaseWikiStore.add_edges` | method call | `wiki/store.py:547` |
| `FtsIndexDriftRule.fix` | `BaseWikiStore.rebuild_index` (new) | method call | M4 |
| `ExportDriftRule.fix` | `export_okf_bundle` | function call | `wiki/export.py:125` |
| `FindingRouter` | `LedgerService.open_issue` | await | `wiki/ledger/service.py:168` |
| `LintRunner` | `WikiBookkeeper.log_operation` | call | `wiki/bookkeeper.py:175` |
| `WikiLintTool` | `create_wiki_tools` list | append | `wiki/tools.py:830` |

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit lint` command~~, ~~`wiki_lint` MCP tool~~
- ~~`parrot.knowledge.lint` package~~ (created by M1)
- ~~a public FTS rebuild on the store~~ (only inside `_migrate_fts`, `store.py:1418`; M4 adds `rebuild_index`)
- ~~working `fix=True`~~ in `LLMWikiToolkit.lint`
- ~~a `related` relation in use~~, and ~~reverse-edge sync~~; the export writes outgoing `relates_to` only
- ~~frontmatter validator~~, ~~duplicate slug detection~~, ~~title uniqueness constraint~~
- ~~`memories`/`notes` tables~~ (memories are `pages.origin='memory'`)
- ~~a severity model at the wiki level~~
- ~~`WIKI_LINT_LLM` env var~~ (introduced by M7)

### Edit Sites (Blueprint Anchors)

Verified against: `30a7f2631`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/__init__.py` (+ models, rule, context, runner, routing, packs/*) | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py` | MODIFY | `def lint_knowledge_base(` | `lint.py:91` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `    async def broken_edges(self) -> list[dict[str, Any]]: ...` | `store.py:603` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | `    async def lint(` | `toolkit.py:415` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | `class WikiLintReport(BaseModel):` | `models.py:302` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def status(path_: str \| None, ns_opt: str \| None, as_json: bool) -> None:` | `cli.py:2147` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `def create_wiki_tools(` | `tools.py:807` | 1 |
| `.github/workflows/ci.yml` | MODIFY | `        run: uv run pytest tests/knowledge/wiki/ -q --tb=short --continue-on-collection-errors` | `ci.yml:274` | 1 |
| `docs/wiki/lint.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/lint/` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async throughout. Rules never block, and the LLM calls are bounded by `asyncio.wait_for`.
- Pydantic v2 models, `self.logger`, Google docstrings.
- Every write goes through store APIs (`add_edges`, `rebuild_index`, `export_okf_bundle`). Never raw SQL from a rule.
- Fixes are idempotent and re-checked. Every applied fix is logged as `LINT_FIX` through `WikiBookkeeper`.
- Rules must work from `dump_pages`/`dump_edges` alone. Store fast-paths are optional.

### Known Risks / Gotchas
- **Federated store.** `broken_edges` on `FederatedWikiStore` (`federation.py` ~1488) classifies cross-namespace edges. Reuse that classification so a link to another namespace is not flagged as broken.
- **ArangoDB unreachable (VPN).** Fail fast with a clear error. Never fall back silently to SQLite.
- **Schema mismatch.** A v3 plane with v2 code (or the reverse) gets the report only, and `--fix` is refused.
- **Concurrent writers.** On a conflict, record a `fix-conflict` info finding. The next run retries.
- **Ledger flooding.** Mitigated by the per-rule cap and aggregation.
- **Pages created by `--fix`.** These are never pages, only edges. Notes added by routing must not trigger `orphan-page` or `duplicate-slug` on later runs.
- **`references` → `related` doubles the edge count.** On large planes this is expected and documented. `--skip asymmetric-related` opts out.
- **Shared files with FEAT-569 and the wikitoolkit-inbox work.** `wiki/cli.py`, `wiki/tools.py` and `wiki/mcp_server.py` are also edited by FEAT-569 (wikitoolkit-http-mcp) and the wikitoolkit-inbox brainstorm. Schedule M9 last and rebase-check before it starts.
- **OKF parity.** `lint_knowledge_base` output must stay byte-identical for the existing tests.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | existing | models |
| `pyyaml` | existing | frontmatter parse |
| `click` | existing | CLI |

There are no new dependencies. `difflib` from the stdlib covers anything beyond exact slug matching, if it is ever needed.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-625-wikitoolkit-lint`. Each task gets a sub-worktree inside it.
- **Module dependency graph**:
  - M1 is the root. Every pack imports `Finding`, `LintRule` and `LintContext` from it.
  - M2, M5, M6, M7 and M8 depend on M1 only.
  - M3 depends on M1 and M4, because it calls `rebuild_index`.
  - M4 has no dependencies.
  - M9 depends on M1–M8.
  - M10 depends on M9.
  - Expected waves: {M1, M4} → {M2, M3, M5, M6, M7, M8} → M9 → M10.
- **Shared files**: `lint/__init__.py` exports, so each pack task appends its exports. Serialize or merge carefully.
- **Exclusive resources**: none. No migration, lockfile or extension rebuild.
- **Cross-feature dependencies**: none blocking. M9 should start after FEAT-569's cli.py and tools.py changes land, or rebase onto them.

---

## 8. Open Questions

- [x] Surfaces in scope — *Resolved in brainstorm*: SQLite plane, ArangoDB, the exported markdown wiki, and memories/ADR.
- [x] Fix default — *Resolved in brainstorm*: report by default; `--fix` is opt-in and safe only.
- [x] Contradiction semantics — *Resolved in brainstorm*: deterministic rules, ADR status conflicts, and LLM-judged (opt-in).
- [x] Relation to OKF lint — *Resolved in brainstorm*: generalize into a shared engine.
- [x] Asymmetric `related` handling — *Resolved in brainstorm*: add an inverse asserted edge, attributed to lint; never delete.
- [x] Finding destinations — *Resolved in brainstorm*: ledger + JSON/md report + page notes.
- [x] Execution surface — *Resolved in brainstorm*: CLI + MCP tool, LLM opt-in.
- [x] `references` as symmetric `related` — *Resolved in brainstorm*: yes, `references` is treated as symmetric `related`, and the inverse is added on `--fix`.
- [x] Scope-violation policy — *Resolved in brainstorm*: an edge is out of scope when it is a broken link. It is folded into `broken-link` (§2).
- [x] Duplicate-slug definition — *Resolved in brainstorm*: compute the slug of each page and look it up in the wiki; if it already exists for another page, it is a duplicate.
- [x] Stale memory severity — *Resolved in brainstorm*: warning.
- [x] Run in hook/CI — *Resolved in brainstorm*: in CI (`--fail-on error`); not in the post-commit hook.
- [x] LLM model and pair cap — *Decided in spec (user deferred to spec)*: the order is `--llm-model` > `WIKI_LINT_LLM` > `WIKI_EXTRACT_LLM` > auto-detect; `LLMFactory.create(temperature=0)`; `--llm-max-pairs` defaults to 50.
- [x] LLM contradiction prompt and verdict schema — *Owner: implementer of M7, reviewed by Jesus*: default suggestion
- [ ] Should the default report dir `<storage_dir>/lint/` be git-ignored, or should it go under `artifacts/logs/`? — *Owner: Jesus* (can be decided during tasks)

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (brainstorm status is `exploration`, not `accepted`) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-03 | Jesus / Claude | Initial draft from the brainstorm |
