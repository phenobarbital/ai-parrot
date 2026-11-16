---
id: FEAT-713
title: Accounting Metrics Layer (revision) — parrot.semantic.accounting on the shipped ai-parrot-semantic, with a reusable in-process DuckDB engine
slug: accounting-metrics-layer
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-11-11
  summary_oneline: "Rewrite FEAT-713 on top of the ai-parrot-semantic package that exists on dev; resolve what FEAT-880 needs (DuckDB/Arrow)"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-semantic, ai-parrot, ai-parrot-server]
tags: [accounting, semantic-layer, duckdb, arrow, sqlglot, audit]
research_state: sdd/state/FEAT-713/
supersedes: sdd/specs/accounting-metrics-layer.spec.md (draft of 2026-10-21, to be rewritten by /sdd-spec)
created: "2026-11-11"
updated: "2026-11-11"
---

# FEAT-713 — Accounting Metrics Layer (revision): `parrot.semantic.accounting` on the shipped `ai-parrot-semantic`

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-713/`](../state/FEAT-713/)

This proposal revises FEAT-713 and keeps its reserved id. It does not replace the accepted brainstorm
(`sdd/proposals/accounting-metrics-layer.brainstorm.md`, Option B); it re-validates that brainstorm and
the draft spec against the code that exists on `dev` today.

---

## 0. Origin

The original request, preserved verbatim (translated from Spanish). The full source is at
`sdd/state/FEAT-713/source.md`.

> Re-write FEAT-713 `accounting-metrics-layer` (draft spec of 2026-10-21, never decomposed into tasks) on
> the basis of the `ai-parrot-semantic` package that already exists on `dev` after FEAT-704 merged
> (PR #1821). The original spec assumed FEAT-704 was paused and created the satellite skeleton itself
> (M1, AC2 and Q10 are obsolete). The new proposal must start from
> `packages/ai-parrot-semantic/src/parrot/semantic/` as it is today, keep the accepted brainstorm
> decisions that still hold, and resolve what FEAT-880 `datasetmanager-semantic-source` needs, including
> DuckDB/Arrow execution (AC10, AC17).

**Initial signals** (extracted, not interpreted):
- Verbs: "re-write", "keep", "resolve" → feature-shaped revision.
- Named entities: `ai-parrot-semantic`, FEAT-704, FEAT-880, `DatasetManager`, DuckDB, Arrow.
- Components / labels: none (inline source).
- Acceptance criteria provided: yes — the 17 criteria of the draft spec, to be re-validated.

---

## 1. Synthesis Summary

The draft spec was written while FEAT-704 was paused, so it created the `ai-parrot-semantic` satellite
itself and forbade any import from the generic layer. FEAT-704 has since shipped that satellite with a
native sqlglot compiler, a governed execution path, a signed audit ledger and CI/release wiring, which
makes the skeleton module and three acceptance criteria obsolete. The accounting design itself — closed
grammar, chart snapshot, per-interval validation, deterministic compiler with golden files — carries
over, because the generic `NativeCompiler` has no account sets, sign normalisation, effective dating or
cumulative windows and offers no engine seam. The revision becomes a `parrot.semantic.accounting`
sub-package that reuses the shipped `SemanticAuditLedger`, `Executor` and compile cache (owner decision
U1), keeps the original `DatasetPolicyGuard` posture and tenant sub-directories (U2, U4), and delivers
the one thing nothing in the repository provides: an in-process DuckDB engine over Arrow-registered
frames, built for reuse (U3). The DuckDB-backed dataset store that FEAT-880 deferred here becomes a
separate feature on top of that engine.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted at
> `sdd/state/FEAT-713/findings/`. Each cites the finding ID(s) that justify its inclusion.

### 2.1 Localization

`SL` = `packages/ai-parrot-semantic/src/parrot/semantic`, `CORE` = `packages/ai-parrot/src/parrot`.

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `SL/__init__.py` | `__all__` | 1-7 | package entry point; eagerly imports `SemanticLayerToolkit` | F002 |
| 2 | `packages/ai-parrot-semantic/README.md` | `Layering` | 6-9 | reserves "the future accounting extension"; requires it to stay independently importable | F002 |
| 3 | `SL/models.py` | `CompiledQuery` | 192-199 | existing pre-governance compiler output; the accounting `CompiledMetricQuery` must not reuse the name | F002 |
| 4 | `SL/models.py` | `Grain` | 12 | existing grain literal an accounting `Grain` would duplicate | F002 |
| 5 | `SL/engines/__init__.py` | `compile` | 29-46 | single compile entry point, hard-wired to `NativeCompiler` | F002 |
| 6 | `SL/engines/native.py` | `NativeCompiler` | 45-54 | generic measures / dimensions / joins compiler | F002 |
| 7 | `SL/execution.py` | `Executor.run_with_columns` | 52-90 | shipped execution path: `DatabaseQueryToolkit` source, env-named connection, dict rows | F001 |
| 8 | `SL/execution.py` | `ConnectionResolver.resolve` | 18-49 | `PARROT_SEMANTIC_CONN_*` overlay; DuckDB files default to read-only | F001, F012 |
| 9 | `CORE/tools/databasequery/sources/duckdb.py` | `DuckDBSource._execute_sync` | 110-156 | the only `duckdb.connect` in package sources: one short-lived connection per query | F001 |
| 10 | `SL/audit.py` | `SemanticAuditLedger.append` | 95-124 | signed, `storage(json_str)`, fail-closed-when-required ledger | F002 |
| 11 | `SL/audit.py` | `SemanticAuditEntry` | 23-67 | entry type the ledger is bound to | F002 |
| 12 | `SL/loader.py` | `SemanticModelLoader._build_snapshot` | 97-133 | flat models directory with a mandatory policy side-file | F002 |
| 13 | `SL/governance/pbac.py` | `PbacGate.authorize` | 63-100 | fail-closed PBAC adapter over `DataPlanePolicyGuard` | F002 |
| 14 | `SL/toolkit.py` | `SemanticLayerToolkit._run_governed` | 289-328 | single governed path; pattern for the finance query path | F002 |
| 15 | `packages/ai-parrot-semantic/tests/test_packaging.py` | `test_namespace_version_and_package_data` | 22-43 | pins the exact dependency list and extras dict | F003 |
| 16 | `packages/ai-parrot-semantic/pyproject.toml` | `dependencies` | 12-16 | sqlglot pin; `duckdb` and `bigquery` extras | F003 |
| 17 | `.github/workflows/ci.yml` | `Semantic-layer tests` | 668-671 | CI step that already runs the satellite tests with the `duckdb` extra | F003 |
| 18 | `CORE/bots/database/toolkits/sql.py` | `SQLToolkit.execute_query` | 297-302 | the execution path the draft spec chose; not used after U1 | F004 |
| 19 | `CORE/auth/dataset_guard.py` | `DatasetPolicyGuard` | 56 | guard for metric visibility (U2) | F004 |
| 20 | `CORE/security/audit_ledger.py` | `AbstractKMSSigner` | 135 | core signer used by the semantic ledger | F004 |
| 21 | `CORE/cli/__init__.py` | `cli._lazy_commands` | 170-217 | lazy CLI registry for a `finance` command (anchor moved from :109-139) | F004 |
| 22 | `packages/ai-parrot-server/src/parrot/scheduler/base.py` | `SchedulerManager.register_object_schedules` | 806-812 | scheduler seam for the daily live validation (anchor moved from :798) | F004 |
| 23 | `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` | `AgentSchedulerManager()` | 465 | the only scheduler construction found | F004 |
| 24 | `CORE/_imports.py` | `require_extra` | 248 | lazy-extra helper for importing `duckdb` | F004 |
| 25 | `CORE/tools/dataset_manager/tool.py` | `DatasetEntry._df` | 278 | datasets are pandas frames; no DuckDB / Arrow store | F005 |
| 26 | `CORE/tools/repl_worker/transport.py` | `pa.Table.from_pandas` | 120 | existing pandas → Arrow bridge | F005, F010, F014 |
| 27 | `sdd/specs/accounting-metrics-layer.spec.md` | `Module 6` | 570-604 | draft design of the DuckDB-over-Arrow and database runtimes | F006 |
| 28 | `sdd/specs/semantic-layer.spec.md` | `U6` | 1254 | owner decision of 2026-10-25: FEAT-704 creates the skeleton, FEAT-713 extends it | F002 |

### 2.2 Constraints Discovered

- **Packaging is done and pinned.** The satellite, its workspace source, the release entry, the CI
  step, the nightly matrix entry and the `duckdb` extra exist; `test_packaging.py` compares the
  dependency list and the extras dict by equality.
  *Implication*: the revision creates no packaging, and any new dependency or extra must update that
  test in the same task.
  *Evidence*: F003, F007

- **"Independently importable" is not true in code.** `SL/__init__.py` imports
  `SemanticLayerToolkit` eagerly, so importing `parrot.semantic.accounting` loads the governed stack.
  *Implication*: with U1 (reuse) the requirement loses most of its purpose; the spec must either
  restate it (lazy package `__init__` plus an import test) or remove it from the README.
  *Evidence*: F002

- **No engine seam.** `engines.compile` instantiates `NativeCompiler` directly, and the semantic-layer
  spec records "single compiler with no dispatch".
  *Implication*: the accounting compiler is a second, parallel compiler in the package; its relation
  to the reserved Rust compiler (FEAT-742) must be stated.
  *Evidence*: F002, F008

- **Two database execution stacks.** The shipped layer runs through `Executor` over
  `DatabaseQueryToolkit` with env-named connections; the draft spec ran through
  `SQLToolkit.execute_query`.
  *Implication*: after U1 the `database` target is the semantic `Executor`; the `SQLToolkit` runner and
  its `limit=1000` risk drop out.
  *Evidence*: F001, F004

- **DuckDB is only a queried database today.** `DuckDBSource` opens one connection per query and
  returns dict rows; nothing registers frames, keeps a root connection or returns Arrow.
  *Implication*: the DuckDB-over-Arrow engine is entirely new code and cannot be built on
  `DuckDBSource`.
  *Evidence*: F001, F005, F012

- **The audit ledger exists but is typed.** `SemanticAuditLedger` signs, stores and fails closed when
  required, but accepts only `SemanticAuditEntry`, stores SQL text and `user_id`, and requires
  durability only when a sink is configured.
  *Implication*: reuse (U1) needs a generalised entry contract; the accounting entry must still carry
  the keys the Postgres sink reads (`user_id`, `tenant_id`, `model`, `outcome`).
  *Evidence*: F002

- **Opposite governance postures.** The shipped layer fails closed over `DataPlanePolicyGuard` with
  table-level resources; the draft spec used `DatasetPolicyGuard` with "no guard ⇒ allow".
  *Implication*: U2 keeps the draft posture, so one package will hold two postures and the README must
  say which applies where.
  *Evidence*: F002, F004, F006

- **Flat models directory.** The shipped loader has no tenant level.
  *Implication*: U4 keeps `<models_dir>/<tenant>/<model>.yaml`; the accounting loader is its own
  loader and does not share `SemanticModelLoader`.
  *Evidence*: F002, F006

- **DatasetManager storage is pandas.** Datasets live on `entry._df`, read directly from many sites in
  `tool.py`, with a Redis Parquet cache; no recent commit or branch touches storage.
  *Implication*: a DuckDB-backed store is a cross-cutting DatasetManager change and stays out of this
  feature (U3).
  *Evidence*: F005, F011, F013

- **Dependencies.** `pyarrow>=25.0` is a core dependency; `duckdb` is declared only as the satellite's
  extra; polars is declared nowhere.
  *Implication*: the old AC17 already holds; the polars half of the old AC10 needs an optional import
  or must be dropped.
  *Evidence*: F003

- **Stale anchors.** The CLI registry and `register_object_schedules` moved; `docs/semantic/` does not
  exist (semantic docs live in `wiki/tools/semantic-layer.md`); no scheduler construction was found in
  `ai-parrot-server`.
  *Implication*: the toolkit, CLI, scheduler and docs modules need refreshed anchors, and the
  scheduled validation still has no verified call site.
  *Evidence*: F004

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched area |
|--------|------|---------|--------------|
| `b46144886c` | 2026-11-11 | FEAT-880 proposal (moves the DuckDB store to this revision) | `sdd/proposals/` |
| `ae7e21f16a` | after 2026-10-27 | read-only governed DuckDB connections | `SL/execution.py`, `CORE/tools/databasequery/sources/duckdb.py` |
| PR #1877 | 2026-10-30 | FEAT-769 semantic-layer example | `packages/ai-parrot-semantic/`, `examples/` |
| PR #1836 (`f514b78af6`) | late October | pandas-3 Arrow values in the REPL worker codec | `CORE/tools/repl_worker/` |
| PR #1817 (`b0106db533`) | late October | FEAT-750 Arrow transport for datasets | `CORE/tools/repl_worker/`, `CORE/bots/data.py` |
| PR #1821 | 2026-10-27 | FEAT-704 merged: `ai-parrot-semantic` with the native compiler | `packages/ai-parrot-semantic/` |
| `5620103b03` | 2026-10-25 | FEAT-704 rev2 proposal: sidemantic designed out | `sdd/proposals/` |
| `15d77efe4d` | 2026-10-21 | FEAT-713 draft spec (last change to the FEAT-713 documents) | `sdd/specs/` |

Since FEAT-769 the semantic package has had only release bumps and a docs move. DatasetManager had
three commits in 45 days, all authorization or error handling. Of 42 branches matching semantic,
accounting, duckdb or dataset, 40 are merged into `origin/dev`; the remaining unmerged one,
`new-dataset-manager`, was last touched on 2026-02-09. No branch exists for FEAT-713, FEAT-880 or
FEAT-742. *Evidence*: F007, F008, F009, F010, F011, F012, F013

---

## 3. Probable Scope

### What's New

- **`parrot.semantic.accounting` sub-package** in the existing satellite — contracts and error
  taxonomy, closed metric grammar, chart snapshot, loader with per-interval validation, and the
  deterministic sqlglot compiler with cumulative windows, hashing, lineage, self-check and per-dialect
  golden tests. These are the draft modules M2–M5, unchanged in substance.
- **Reusable in-process DuckDB engine over Arrow** — one root connection, Arrow-registered frames,
  per-thread cursors under `asyncio.to_thread`, `duckdb` imported lazily. It has no accounting
  dependency in its interface, so a later dataset-store feature can build on it (U3).
- **Accounting runtimes** — a DuckDB target that feeds frames to that engine through a
  `frame_provider`, and a database target that runs the compiled SQL through the semantic `Executor`
  (U1).
- **`AccountingToolkit`** (`tool_prefix = "finance"`: list, explain, query, validate), a
  `parrot finance` CLI command and an MCP-local configuration example.
- **Live validation** — assertions and chart drift, on demand and scheduled.
- **Accounting audit record** — `model_hash`, `snapshot_hash`, `sql_hash`, `lineage_ref`, assertion
  status and target, appended through the shared ledger (U1).
- **Documentation** — an accounting section following the `wiki/tools/` convention and a README update.

### What Changes

- **`SL/audit.py`::`SemanticAuditLedger`** — generalise the entry contract so an accounting entry can
  be signed and stored by the same ledger.  *Evidence*: F002
- **`SL/__init__.py`::`__all__`** and **`README.md`::`Layering`** — replace "future accounting
  extension" with the actual layering contract; decide the fate of "independently importable".
  *Evidence*: F002
- **`CORE/cli/__init__.py`::`cli._lazy_commands`** — register the lazy `finance` command and its
  extras hint.  *Evidence*: F004
- **`packages/ai-parrot-semantic/tests/test_packaging.py`** — only if a dependency or extra is added.
  *Evidence*: F003
- **`ai-parrot-server` scheduler adapter** — register the daily validation once a call site is
  verified.  *Evidence*: F004

### What's Untouched (Non-Goals)

- Satellite packaging, release entry, CI step and nightly matrix — delivered by FEAT-704 (the draft
  M1, AC2 and the `test-semantic` job of AC16 are dropped).
- The DuckDB-backed dataset store and any change to `DatasetManager` storage — a separate feature on
  top of the engine delivered here (U3).
- The generic `NativeCompiler`, `engines.compile`, `GovernancePipeline` and the `sl_*` tools.
- `SQLToolkit`, `AuditLedgerEntry` and `parrot/clients/base.py`.
- Joins to dimension tables, fiscal calendars, `parent:` hierarchy selectors, multi-entity
  consolidation, FX, result caching and an admin UI — the draft's non-goals, unchanged.
- Lowering accounting metrics into the generic layer, and the FEAT-742 Rust compiler.

### Patterns to Follow

- Compile off the event loop with `asyncio.to_thread` plus a compile cache keyed by model digest,
  canonical request and dialect.  *Evidence*: F002
- Sign `canonical_bytes()` with `AbstractKMSSigner` and forward `model_dump_json()` to an async
  storage callable.  *Evidence*: F002, F004
- One governed entry path in the toolkit, with a `_pre_execute` check for a bound
  `PermissionContext`.  *Evidence*: F002
- DuckDB work inside `asyncio.to_thread` with a lazy import and a clear error when the extra is
  missing; governed DuckDB files opened read-only.  *Evidence*: F001, F012
- pandas → Arrow through `pa.Table.from_pandas`, as the REPL worker transport does.
  *Evidence*: F005, F010, F014
- Lazy CLI command registration with an extras hint.  *Evidence*: F004

### Integration Risks

- **Where the reusable engine lives**: `ai-parrot-semantic` depends on `ai-parrot`, never the reverse.
  An engine placed in the satellite cannot be imported by a `DatasetManager` store in core; an engine
  placed in core needs a `duckdb` extra there, which contradicts the old AC17. This is the first open
  item for the spec.  *Evidence*: F003, F005
- **Two governance postures in one package**: finance metrics allow when no guard is configured (U2)
  while `sl_*` queries fail closed. Mitigation: state it in the README and the toolkit docstrings, and
  test both.  *Evidence*: F002, F004
- **Reuse of `Executor` under the draft's exactness rules**: the shipped contracts return dict rows
  with no Decimal handling, and the executor caps rows with a `limit + 1` probe. Mitigation: the spec
  defines Decimal conversion at the boundary and what truncation means for a rollup.  *Evidence*: F001, F002
- **Root connection shared across threads**: the only existing DuckDB code opens one connection per
  query, so the engine's concurrency model has no in-repo precedent. Mitigation: a concurrency test
  (the old AC10 asked for 8 concurrent requests).  *Evidence*: F001, F006
- **pandas → Arrow is a copy** and may carry object or float amounts. Mitigation: conversion errors
  and the `allow_float` rule of the draft.  *Evidence*: F005
- **Scheduled validation has no verified call site** (old Q11). Mitigation: resolve in the spec, or
  ship on-demand validation first.  *Evidence*: F004
- **Shared sqlglot pin**: a bump now changes the generic compiler and the accounting goldens together.
  *Evidence*: F003, F006

### Disposition of the draft spec

| Draft item | Disposition |
|---|---|
| M1 skeleton, AC2, Q10, risk "FEAT-704 merge collision", codex S11 | **dropped** — delivered by FEAT-704; owner decision of 2026-10-25 |
| Decision "standalone, never imports `parrot.semantic.*`", AC1 import rule | **replaced** by U1 (reuse) |
| M2 contracts, M3 grammar, M4 loader / snapshot / validation, M5 compiler + goldens; AC3–AC9, AC12 | **kept** |
| M6 `DuckDBRunner` | **kept and widened** into a reusable engine (U3) |
| M6 `DatabaseRunner` over `SQLToolkit` | **replaced** by the semantic `Executor` (U1) |
| M7 own `AccountingAuditLedger` | **replaced** by the shared ledger with an accounting entry (U1) |
| M8 toolkit / CLI / MCP, AC13, AC14 | **kept**; PBAC as drafted (U2); anchors refreshed |
| M9 scheduled validation, AC15, Q11 | **kept**; call site still open |
| M10 docs, AC16 | **kept**; path moves to the `wiki/tools/` convention; CI is already wired |
| Models at `<models_dir>/<tenant>/<model>.yaml` | **kept** (U4) |
| AC10 | **rewritten** — DuckDB engine over Arrow plus the semantic `Executor`; polars to be decided |
| AC17 | **already true**; revisit only if the engine moves to core |
| Non-goal "Modifying `DatasetManager`" | **kept**; the dataset store is a separate feature |

*Evidence*: F006 (inventory), F002, F003, F004

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The draft M1, AC2, Q10, the collision risk and codex S11 are obsolete | F002, F003, F007 | high | packaging files, tests, merge history and the semantic-layer spec U6 read directly |
| C2 | The reason FEAT-713 was standalone no longer exists; the package ships a clean-room native compiler | F002, F003, F008 | high | dependency list, packaging test, rev2 decision |
| C3 | The generic compiler cannot express the accounting model, so the accounting compiler stays separate | F002 | medium | `native.py` was read to line 140 only; absence beyond that is inferred from the outline |
| C4 | There is no engine seam to plug an accounting compiler into | F002 | high | `engines.compile` read directly |
| C5 | No in-process DuckDB engine over registered frames and no Arrow result path exists in package sources | F001, F005 | high | grep for duckdb imports, `register` and `fetch_arrow_table` |
| C6 | The old AC17 already holds | F003 | high | pyproject files read |
| C7 | The audit mechanics of the draft M7 already exist; only the entry shape and default mode differ | F002 | high | `audit.py` read directly |
| C8 | The draft's PBAC, executor, tenant layout and audit-mode choices each differ from the shipped layer | F001, F002, F004, F006 | high | both sides read |
| C9 | The draft M2–M5 carry over unchanged in substance | F006, F002 | medium | none cites a FEAT-704 premise; name collisions (`Grain`, `Metric`) and the shared pin need a pass |
| C10 | A DuckDB-backed dataset store and a frame-fed DuckDB runtime are different features | F005, F006 | high | `entry._df` accessor inventory and the draft non-goal |
| C11 | FEAT-880 does not need an accounting feature to work; what it deferred here is only the DuckDB store | F005, F009 | medium | from the FEAT-880 proposal; the FEAT-880 spec in progress was not read |
| C12 | Old integration points still resolve, with two moved anchors, no `docs/semantic/` and no verified scheduler call site | F004 | high | each symbol grepped |
| C13 | Collision risk is low | F007, F011, F013 | medium | branch-name search and recent history; a peer session was editing the FEAT-880 spec |
| C14 | The revised feature is roughly the draft M2–M10 with M6–M8 re-based, of similar size | F006, F003 | low | sizing by analogy; the engine's home can add a module in core |

Distribution: **9** high, **4** medium, **1** low.

> The low claim (C14) is about size, not design. The medium claims C3 and C11 are answerable by reading
> and are carried into the spec as follow-up research; they keep the overall confidence at medium.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — May `parrot.semantic.accounting` reuse the shipped semantic infrastructure, or does it
  stay standalone?** — *Resolved*: Reuse — `SemanticAuditLedger` (generalising the entry),
  `Executor` / `ConnectionResolver` over `DatabaseQueryToolkit` and the compile cache; only model,
  grammar, validation and compiler are accounting-specific.
  *Resolves claims*: C8, C14

- [x] **U2 — Which governance posture do finance metrics get?** — *Resolved*: The original spec's —
  `DatasetPolicyGuard` with `accounting:<tenant>:<model>:<metric>` resources; no guard configured
  means allow, as in `DatasetManager`.
  *Resolves claims*: C8

- [x] **U3 — What DuckDB scope does this revision take for FEAT-880?** — *Resolved*: A reusable
  engine here — an in-process DuckDB engine over Arrow (root connection, frame registration,
  per-thread cursors) designed for reuse; the DuckDB-backed dataset store goes into its own feature
  that builds on it.
  *Resolves claims*: C10, C11, C14

- [x] **U4 — Where do accounting models live?** — *Resolved*: Tenant sub-directories,
  `<models_dir>/<tenant>/<model>.yaml`, as the brainstorm decided.
  *Resolves claims*: C8

### Unresolved (defer to spec / implementation)

- [ ] **Where does the reusable DuckDB engine live — in `ai-parrot-semantic` or in core `ai-parrot`
  behind a new `duckdb` extra?** — *Owner*: tbd (decide in `/sdd-spec`)
  *Blocks claims*: C14
  *Plausible answers*: a) core, so a `DatasetManager` store can import it (the old AC17 changes) ·
  b) satellite, and the future store ships from the satellite too

- [ ] **Server scheduler call site for the daily validation (old Q11).** — *Owner*: tbd (research in
  `/sdd-spec`; lead: `AgentSchedulerManager()` in the agentd service)
  *Blocks claims*: C12

- [ ] **Is polars a supported frame type in v1?** It is declared nowhere in the workspace. —
  *Owner*: tbd
  *Blocks claims*: C9
  *Plausible answers*: a) pandas only in v1 · b) polars through an optional import, no new dependency

- [ ] **Does the accounting compiler fall inside or outside the scope of the FEAT-742 Rust
  compiler?** — *Owner*: tbd
  *Blocks claims*: C3

- [ ] **Fate of "the accounting extension must remain independently importable"** now that U1 allows
  reuse. — *Owner*: tbd
  *Plausible answers*: a) drop the sentence · b) keep it for the compile-only path (model, grammar,
  compiler) with a lazy package `__init__` and an import test

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-713`** — *Rationale*: localization is high-confidence, the accounting design carries
over, and the four forks about alignment with the shipped layer are closed by U1–U4; the remaining
items are spec-level decisions, three of them answerable by reading. The spec rewrites
`sdd/specs/accounting-metrics-layer.spec.md` in place.

### Alternatives

- **`/sdd-brainstorm FEAT-713`** — if the engine's home (core or satellite) should be weighed as an
  architectural option before the spec, since it decides how the future dataset store is packaged.
- **New feature for the DuckDB-backed dataset store** — the follow-up that FEAT-880 deferred; it
  depends on the engine delivered here and is not part of this feature.
- **Manual review** — not needed; research was not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-713/state.json` |
| Source (raw) | `sdd/state/FEAT-713/source.md` |
| Research plan | `sdd/state/FEAT-713/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-713/findings/F001-*.md` … `F014-*.md` |
| Lane originals | `sdd/state/FEAT-713/findings/.audit/` |
| Synthesis (JSON) | `sdd/state/FEAT-713/synthesis.json` |
| Earlier design research (draft spec) | `sdd/state/FEAT-713/design_research/` |

**Budget consumed**:
- Files read: 22 / 40
- Grep calls: 20 / 25
- Git calls: 6 / 10
- Wall time: 345s / 300s (longest lane; the codebase lane overran its 255s slice)
- Truncated: **no** — one planned query was skipped

**Execution notes**:
- Research ran in three parallel lanes (codebase, git, wiki); 22 lane findings merged into 14. The
  seven findings about the semantic package share citations and collapsed into `F002`.
- The research-plan gate was not presented for approval; the plan ran as generated.
- The citation check ran inline with a script rather than through the probe agent: 136 citations,
  131 matched their cited line range. The other five use paraphrased excerpts; four were confirmed by
  hand at the cited lines, and the fifth cites a file that was located but not opened.
- Not read: `native.py` and `loader.py` beyond line 140, `GovernancePipeline.govern`, the contents of
  `wiki/tools/semantic-layer.md` and of the examples, and the FEAT-880 spec in progress.

**Mode determination**: `auto` → resolved to `enrichment` (revision of a planned capability).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Code (Fable 5.2) |
