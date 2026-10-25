---
id: FEAT-704
revision: 2
title: "Semantic layer rev2 — native sqlglot compiler as the only engine, sidemantic (AGPL-3.0) removed, SemaFlow (MIT) staged for the Rust phase, BSL reserved for joins"
slug: semantic-layer-rev2
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-25
  summary_oneline: "FEAT-704 rev2 — drop sidemantic (AGPL), own sqlglot compiler as sole engine, SemaFlow (MIT) for the Rust phase, BSL reserved for joins"
  files: [artifacts/semantic-layer.research.md, artifacts/accounting-metrics-layer.brainstorm.md]
supersedes: sdd/proposals/semantic-layer.proposal.md
amends: sdd/specs/semantic-layer.spec.md
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-semantic, ai-parrot, ai-parrot-server, ci]
tags: [semantic-layer, sqlglot, licensing, clean-room, semaflow, rust, pyo3, rls, pbac]
research_state: sdd/state/FEAT-704/rev2/
created: 2026-10-25
updated: 2026-10-25
---

# FEAT-704 rev2 — Semantic layer without sidemantic: one native compiler, Rust later, BSL only for joins

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: artifacts/semantic-layer.research.md` (decision block 2026-10-21) + `artifacts/accounting-metrics-layer.brainstorm.md` (Appendix A, SemaFlow audit) + inline instructions
> **Audit**: [`sdd/state/FEAT-704/rev2/`](../state/FEAT-704/rev2/)
> **Supersedes**: [`semantic-layer.proposal.md`](semantic-layer.proposal.md) (2026-10-14: BSL/Ibis recommended, sidemantic as legal-conditioned alternative) · **Amends**: [`semantic-layer.spec.md`](../specs/semantic-layer.spec.md) (FEAT-704, approved rev 0.2)

---

## 0. Origin

Full source, including the verbatim inline instructions and the mid-run owner decision, is at `sdd/state/FEAT-704/rev2/source.md`.

> **Decisión (2026-10-21) — supersede la recomendación original de este documento.** [...] ai-parrot **no adopta ninguna librería de capa semántica como núcleo**:
> - **sidemantic queda descartado** del todo: ni dependencia, ni referencia de código. [...] De sidemantic solo se usa lo que es público y no suyo: los esquemas de Cube y dbt MetricFlow que importa, consultados en su documentación original.
> - **Implementación propia** [...]: un único compilador Pydantic → IR → sqlglot con gramática cerrada [...] Sin joins en v1.
> - **SemaFlow (MIT)** es la fuente de código derivado, con acreditación, cuando el compilador pase a Rust/PyO3 (`sql_ast.rs` + `dialect/`); en v1 es referencia de diseño acreditada.
> - **BSL/Ibis** [...] pasa a **reservado para la fase de joins** [...]
> - La gobernanza (RLS desde PBAC, allowlist por rol, guard sqlglot positivo, AuditLedger) es código de ai-parrot con cualquier motor; esa parte del research sigue vigente íntegra.

Mid-run decision (2026-10-25), on learning that the FEAT-704 feature branch already implements all 20 tasks around sidemantic:

> we can discard that branch because was focused on sidemantic, that is discarded, or re-used the code no related to sidemantic

**Initial signals** (extracted, not interpreted):
- Verbs: "eliminar", "re-hacer el research", "descartado", "se conservan tal cual" → a scoped re-decision over an existing feature, not a new one.
- Named entities: FEAT-704, sidemantic (AGPL-3.0), SemaFlow (MIT), BSL/Ibis, Cube, dbt MetricFlow, Apache Ossie, sqlglot, Rust/PyO3.
- Explicit invariants: clean-room rule for sidemantic; SemaFlow derivation must be attributed; execution pipeline, positive sqlglot guard, `SemanticQuery` and the MCP surface are kept unchanged.
- Acceptance criteria provided: no (the decision block fixes direction, not acceptance).

---

## 1. Synthesis Summary

FEAT-704 is approved and, contrary to its `dev` index, fully built: `origin/feat-FEAT-704-semantic-layer` carries all 20 tasks done with sidemantic `==0.12.0` as the semantic core and a native sqlglot compiler as fallback (`packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`), unmerged, with no PR and conflicts against `dev` (C1, C2, C9). The owner has now removed sidemantic for licence reasons and treats that branch as a salvage source only. The coupling to sidemantic is narrow: one loader (`loader.py`, which hands a sidemantic graph to everything via `LoadedModel.layer`), the engine dispatch, the sidemantic adapter and two `Literal` fields (C3); 62% of the satellite source and the whole HTTP handler never mention it (C4). Rev2 therefore amends FEAT-704 rather than restarting it: a typed, clean-room semantic model graph replaces the sidemantic graph, the existing native compiler becomes the only engine, the governance/audit/toolkit code is salvaged as-is, FEAT-738's already-merged RLS fix replaces M12, and the Rust/PyO3 phase (deriving SemaFlow's `sql_ast.rs` + `dialect/` under MIT with attribution) is staged as a later feature. "BSL reserved for joins" is kept as an option but must be reconciled with the repo's recorded Ibis NO-GO (C7). Recommended next step: `/sdd-spec` amending `semantic-layer.spec.md` to rev 0.3, with five scoping questions (§5) answered in its §8.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-704/rev2/findings/F001–F015`. Paths marked **(branch)** exist only on `origin/feat-FEAT-704-semantic-layer` and were read with `git show`; they do not exist on `dev`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` (branch) | `SemanticModelLoader.load` | 83-173 | only import site of sidemantic; builds members, physical schema, scoping from `layer.graph` — rewrite target | F006, F009 |
| 2 | same file (branch) | `LoadedModel` | 58-70 | `layer: Any` = sidemantic graph → typed graph | F006 |
| 3 | `.../engines/native.py` (branch) | `NativeCompiler` | 18-236 | existing sqlglot compiler for the v1 subset; six `layer.graph` call sites; becomes the sole engine | F007 |
| 4 | `.../engines/__init__.py` (branch) | `compile` | 31-50 | two-way engine dispatch → single path | F007 |
| 5 | `.../engines/sidemantic_engine.py` (branch) | `compile_sidemantic` | 18-169 | sidemantic adapter — delete | F007, F009 |
| 6 | `.../models.py` / `.../policy.py` (branch) | `CompiledQuery.engine`, `ModelPolicy.engine` | 148 / 56 | `Literal["sidemantic","native"]` and default `"sidemantic"` | F008 |
| 7 | `.../governance/{guard,lineage,masking,pbac,pipeline,rls}.py` (branch) | `GovernancePipeline` et al. | 881 lines total | engine-neutral governance — salvage as-is | F009 |
| 8 | `.../toolkit.py`, `audit.py`, `cache.py`, `catalog.py`, `execution.py`, `results.py`, `ossie.py`, `errors.py`, `context.py` (branch) | `SemanticLayerToolkit`, `SemanticAuditLedger`, … | 1,374 lines total | engine-neutral — salvage as-is | F009 |
| 9 | `packages/ai-parrot-server/src/parrot/handlers/semantic.py` (branch) | `SemanticLayerHandler` | 1-202 | HTTP surface — salvage as-is | F009, F004 |
| 10 | `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py` (branch commit `b9f9983d67`) | DuckDB source | 1-101 | worker-thread execution fix — re-apply on dev | F004 |
| 11 | `.../tests/test_native_compiler.py` (branch) | `test_native_dialect_snapshots` | 68 | golden-SQL oracle that replaces parity tests | F008 |
| 12 | `sdd/specs/semantic-layer.spec.md` | G5, G7, Non-Goals, §2 Overview, M1, M4, M5, AC1/AC11/AC16/AC18, §8 Q1/Q2 | 60-75, 89-100, 329, 406-444, 762-779, 1099-1100 | sections rev 0.3 rewrites | F002 |
| 13 | `sdd/tasks/index/semantic-layer.json` | TASK-4467, TASK-4468, TASK-4482 | 1-20 | re-scope 4467/4468, drop 4482 | F003, F014 |
| 14 | `sdd/specs/accounting-metrics-layer.spec.md` | M1, §8 Q10 | 389-402, 1074 | FEAT-713 owns the sidemantic-free skeleton and waits for FEAT-704's amendment | F011 |
| 15 | `sdd/tasks/completed/TASK-1437-ibis-connection-spike.md`; `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/compiler.py` | Completion Note; docstring | 124-134; 19 | the recorded Ibis NO-GO | F010 |
| 16 | `packages/navrules/rust/Cargo.toml`; `pyproject.toml`; `.github/workflows/release.yml` | `navrules_native`; `[tool.parrot.worktree.native_group]`; `PyO3/maturin-action@v1` | 1-30; 294-320; 387-392 | Rust/PyO3 precedents for the Rust phase | F012 |
| 17 | `packages/ai-parrot/pyproject.toml`; `packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py` | `sqlglot>=20.0`; `SQLGLOT_DIALECT_MAP` | 182; 6 | pins and shared dialect map | F013 |
| 18 | `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` | `AuthorizingDataSource._apply_rls` | 1-75 | FEAT-738 fix already on dev; branch copy must not be salvaged | F014, F015 |

### 2.2 Constraints Discovered

- **Clean-room rule.** sidemantic's code is never opened or ported; only its public documentation and the Cube / dbt MetricFlow / Ossie formats, read from their original specs, inform the typed model schema. *Implication*: the schema and loader are written from public format docs; the branch's sidemantic-API glue (`loader.py` body, `sidemantic_engine.py`, the Ossie compatibility shim) is deleted, not adapted. *Evidence*: F001, F006.
- **Branch is salvage only** (owner, 2026-10-25). *Implication*: fresh worktree off `origin/dev`; `git checkout origin/feat-FEAT-704-semantic-layer -- <zero-reference paths>`; the branch's 20 `done` stamps are not carried. *Evidence*: F004, F009.
- **Ibis NO-GO is on record** (TASK-1437, cited at `spatial/compiler.py:19`, codified as a FEAT-704 Non-Goal). The NO-GO reasons were connection mapping (asyncpg DSN ≠ libpq, BigQuery credentials shim); compile-only `ibis.to_sql` was never evaluated. *Implication*: "BSL reserved for joins" must be written as an explicit, scoped re-opening in whichever spec starts the joins phase; rev2 adds no Ibis/BSL dependency. *Evidence*: F010, F002.
- **Determinism contract.** Byte-identical SQL per (model digest, canonical query, dialect); never iterate a dict/set into SELECT, GROUP BY or `IN` order (the SemaFlow `HashMap` lesson). *Implication*: narrow sqlglot pin in the satellite (branch used `>=30.1,<31`; venv has 30.23.0; core's `>=20.0` is too loose) plus per-dialect golden SQL and a cross-process hash test. *Evidence*: F001, F013, F004.
- **Governance is already engine-neutral.** PBAC gate, lineage, RLS push-down, masking, positive guard and signed audit run on the compiled sqlglot AST. *Implication*: no semantic change in `governance/`, `audit`, `cache`, `catalog`, `execution`, `results`, `toolkit`, handler; only the `engine` field disappears. *Evidence*: F002, F009.
- **FEAT-713 coupling.** The accounting layer (draft spec, same 1.3.0 target, not yet decomposed) plans to create the sidemantic-free satellite skeleton and asks (Q10) for FEAT-704's M1 to become "extend". *Implication*: one owner for `packages/ai-parrot-semantic/pyproject.toml`; `parrot.semantic.accounting` must import without the generic layer. *Evidence*: F011.
- **FEAT-738 already shipped M12.** TASK-4678/4679 (merged 2026-10-24, PR #1801) fixed `authorizing.py` and `handlers/datasets.py`; the branch conflicts with `dev` exactly on those files. *Implication*: drop FEAT-704 M12/TASK-4482; never salvage those files or `uv.lock`. *Evidence*: F014, F004.
- **Rust/PyO3 precedents exist, THIRD_PARTY.md does not.** navrules (pyo3 0.29, abi3-py311, maturin, `extension-module` feature off for `cargo test`), parrot_codec, yaml_rs; worktrees copy/auto-build `.so` via `native_group`; release builds with `maturin-action`. *Implication*: the Rust phase joins those mechanisms and creates `THIRD_PARTY.md` with SemaFlow's MIT header before the first derived line lands. *Evidence*: F012.
- **Join scope tension.** The branch's native compiler already does declared one-to-many joins with fan-out rejection; the decision block says "sin joins en v1". *Implication*: owner decision (U4). *Evidence*: F007, F001.
- **Open ledger issues** `issue:3c4d154c0172` (toolkit catalog hardening) and `issue:46e8f6219bf5` (LIKE wildcard escaping) were raised against the salvaged toolkit/catalog code. *Implication*: claimed and fixed by the salvage tasks. *Evidence*: F014.

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `5b88bce7a` | 2026-10-24 | Jesus Lara | fix(handlers): TASK-4679 — per-user dataset clones no longer share a DataSource | `handlers/datasets.py` |
| `55619c5ce` | 2026-10-24 | Jesus Lara | fix(dataset-manager): TASK-4678 — request-scoped RLS injection | `dataset_manager/sources/authorizing.py` |
| `25b1fa594` (branch tip) | 2026-10-21 | — | style(semantic-layer): FEAT-704 — full lint pass (20/20 tasks done on branch) | `packages/ai-parrot-semantic/**` |
| `15d77efe4` | 2026-10-21 | Jesus Lara | sdd: add spec for FEAT-713 — accounting-metrics-layer | `sdd/specs/accounting-metrics-layer.spec.md` |
| `43cd6bcb3` | 2026-10-21 | Jesus Lara | sdd: accept brainstorm for accounting-metrics-layer | `sdd/proposals/accounting-metrics-layer.brainstorm.md` |
| `dd97dec23` | 2026-10-19 | Jesus | sdd: resolve §8 open questions for semantic-layer (FEAT-704, spec rev 0.2) | `sdd/specs/semantic-layer.spec.md` |
| `0324bb1d4` | 2026-10-19 | Jesus Lara | sdd: add spec for FEAT-704 — semantic-layer | `sdd/specs/semantic-layer.spec.md` |

Branch state: base `05d62af07` (2026-10-19), 1,379 `dev` commits behind, no PR, `merge-tree` conflicts in `handlers/datasets.py`, `test_datasets_clone.py`, `authorizing.py`, `test_authorizing_data_source.py`, `uv.lock` (F004).

---

## 3. Probable Scope

### What's New

- **Typed semantic model graph** — `parrot/semantic/model.py`: frozen Pydantic v2 `SemanticModel` / `Dimension` (categorical, numeric, time + grain) / `Metric` (`agg`, `sql`, optional `filter`, derived expression) / `Relationship` (cardinality), canonical sorted digests. Authored from Cube, dbt MetricFlow and Apache Ossie 0.1.1 public specs (clean-room). Replaces `LoadedModel.layer: Any`.
- **Loader rewrite** — `loader.py` reads the own YAML format and Ossie documents into that graph; keeps `PhysicalSchema`, `sqlglot_schema()`, policy binding, digests and directory fingerprint from the branch; drops temp staging and the sidemantic Ossie shim.
- **Sole compiler** — `engines/native.py` re-pointed to the typed graph (six call sites), promoted from "fallback" to the engine; v1 additions fixed in the spec: filtered measures lowered to `FILTER (WHERE …)` or `CASE WHEN` per dialect (SemaFlow design reference, attributed in-doc), derived metrics over metrics; fan-out rejection kept.
- **Determinism test kit** — per-dialect golden SQL (postgres, bigquery, duckdb), DuckDB execution oracle against hand-computed expectations, cross-process hash check (brainstorm S2). Replaces the sidemantic parity tests (AC11/AC18).
- **Rust phase (later, own FEAT)** — PyO3 crate deriving SemaFlow `sql_ast.rs` + `dialect/{duckdb,postgres,bigquery}.rs` (~1,150 lines, `serde_json`-only) under MIT with attribution; `THIRD_PARTY.md`; `native_group` + release-matrix entries; upstream issue for manylinux wheels. Rev2 only fixes the IR shape it must consume.
- **Spec amendment** — FEAT-704 rev 0.3 + re-scoped tasks (see below).

### What Changes

- **`sdd/specs/semantic-layer.spec.md`** — G5 → "MIT-only satellite, no AGPL"; G7 → "single native compiler"; Non-Goals keep the Ibis NO-GO but add the scoped re-opening clause for a joins phase; §2 Overview around the typed graph; M1 pins (`sqlglot` narrow, `pyyaml`, `jsonschema` for Ossie; no `sidemantic`); M4 → "typed model + loader" (no spike); M5 → "sole compiler + golden tests"; AC1/AC11/AC16/AC18 lose sidemantic; §8 Q1/Q2 marked superseded. *Evidence*: F002.
- **`sdd/tasks/index/semantic-layer.json`** — TASK-4467 re-scoped, TASK-4468 re-scoped, TASK-4482 dropped (delivered by FEAT-738); everything stays `pending` on dev. *Evidence*: F003, F014.
- **`packages/ai-parrot-semantic/pyproject.toml` + `README.md`** — dependency list without sidemantic; licence notice removed; "Layering" section per FEAT-713. *Evidence*: F004, F005, F011.
- **`ruff.toml`** — keep the repo-wide TID251 `sidemantic` ban as a permanent guard; remove the satellite per-file ignore; `test_packaging` asserts the ban fires everywhere. *Evidence*: F005.
- **`models.py` / `policy.py`** — drop the `engine` Literal and its default. *Evidence*: F008.
- **Fixtures** — `orders.yml` re-expressed in the own format; `orders.policy.yaml` without `engine:`. *Evidence*: F008.
- **`databasequery/sources/duckdb.py`** — re-apply the branch's worker-thread fix on top of `dev`. *Evidence*: F004.
- **`sdd/specs/accounting-metrics-layer.spec.md` Q10** — resolved by naming the skeleton owner (U6). *Evidence*: F011.

### What's Untouched (Non-Goals)

- `governance/`, `audit.py`, `cache.py`, `catalog.py`, `context.py`, `errors.py`, `execution.py`, `results.py`, `toolkit.py`, `ossie.py` (validation), `handlers/semantic.py` — salvaged as-is after import re-verification.
- `SemanticQuery`, `sl_*` tool surface, mcp-local YAML section, HTTP routes, result handles, signed audit ledger (the source says these "se conservan tal cual").
- `parrot/clients/base.py`, `DatabaseQueryToolkit`, `RlsRegistry`, `DataPlanePolicyGuard` (spec Non-Goals unchanged).
- Ibis / BSL — no dependency in rev2; a joins phase is a later spec.
- Symmetric aggregates, cumulative / time-comparison / cohort metrics — were sidemantic-only in v1 and stay out.
- The accounting compiler itself (FEAT-713) — a sibling package; only skeleton ownership is coordinated here.

### Patterns to Follow

- PEP 420 satellite without `src/parrot/__init__.py`, dynamic version, package-data for `schemas/*.json` and `sql/*.sql` (branch pyproject, ai-parrot-embeddings layout). *Evidence*: F004, F011.
- Golden snapshot tests per dialect already exist (`test_native_dialect_snapshots`) — extend. *Evidence*: F008.
- Shared `SQLGLOT_DIALECT_MAP` / `driver_to_dialect` for driver→dialect mapping. *Evidence*: F013, F003.
- Rust: navrules layout (pyo3 0.29 abi3-py311, maturin, `extension-module` feature off for `cargo test`), `serde_json` `preserve_order` for determinism (parrot_codec), `native_group` registration, never `maturin develop` in automated paths. *Evidence*: F012.

### Integration Risks

- **Salvage drift** — branch 1,379 commits behind, core conflicts. *Mitigation*: only zero-reference satellite files + handler are checked out from the branch; core edits re-applied by hand; import-boundary tests rerun. *Evidence*: F004, F014.
- **Parity oracle lost** — AC11/AC18 compared against sidemantic. *Mitigation*: golden SQL + DuckDB execution + cross-process determinism. *Evidence*: F008.
- **Skeleton ownership race** with FEAT-713. *Mitigation*: spec names one owner; the other "extends" with a byte-level diff check. *Evidence*: F011.
- **BSL-for-joins vs Ibis NO-GO** — silent contradiction. *Mitigation*: rev 0.3 states the NO-GO's scope and the re-opening rule; no dependency now. *Evidence*: F010, F002.
- **Scope regression** if "no joins in v1" strips a tested subset. *Mitigation*: U4; default recommendation keeps one-to-many + fan-out rejection. *Evidence*: F007, F001.
- **SemaFlow hygiene** — unfilled MIT template, personal git fork for BigQuery, `ring` breaks manylinux. *Mitigation*: derive only `sql_ast.rs` + `dialect/`; record upstream copyright as best known; open the wheel issue. *Evidence*: F001, F012.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | FEAT-704 is fully implemented (20/20 tasks, 56 satellite files, 16 outside) on the unmerged branch with no PR | F004 | high | git log / diff / ls-tree / merge-base / gh read directly |
| C2 | On dev the index shows all 20 tasks pending and no `packages/ai-parrot-semantic` exists | F003, F005, F015 | high | index parsed; ls and wiki confirm absence |
| C3 | sidemantic coupling is confined to `loader.py`, `engines/` and two Literal fields | F006, F007, F008, F009 | high | per-file grep counts + direct reads |
| C4 | 2,264 / 3,630 satellite lines (62%) have zero sidemantic references; +521 need a one-line edit; handler is clean | F009 | high | counted per file |
| C5 | The native compiler covers the v1 subset incl. one-to-many joins with fan-out rejection | F007, F002 | high | code and spec M5 read |
| C6 | Removing sidemantic removes the parity oracle; golden SQL + DuckDB execution replace it | F008 | medium | inference; replacement is a design choice |
| C7 | Ibis NO-GO concerned connection mapping; compile-only BSL never evaluated; spec codified it as Non-Goal | F010, F002 | high | Completion Note + spec read |
| C8 | FEAT-713 creates the sidemantic-free skeleton and asks FEAT-704 to "extend" (Q10) | F011 | high | spec M1 + Q10 read |
| C9 | FEAT-704 M12/TASK-4482 is superseded by FEAT-738; the branch conflicts exactly there | F014, F004 | high | git log + merge-tree coincide |
| C10 | The Rust phase can follow navrules; `THIRD_PARTY.md` must be created | F012 | high | Cargo/pyproject/Makefile/release.yml read; no THIRD_PARTY/NOTICE |
| C11 | Determinism needs a narrow sqlglot pin in the satellite | F013, F004, F001 | high | pins read; contract in source |
| C12 | SemaFlow `sql_ast.rs` + `dialect/` (~1,150 lines) is the derivable slice | F001 | medium | owner's Appendix A audit; not re-verified upstream here |
| C13 | Clean-room means authoring the schema from public specs and deleting (not adapting) our sidemantic glue | F001, F006 | medium | rule explicit; application to our own glue is judgement |
| C14 | Two open ledger issues attach to salvaged toolkit/catalog code | F014 | high | ledger list read |
| C15 | "No joins in v1" conflicts with the branch's working one-to-many subset | F001, F007 | high | both texts read; resolution is U4 |

Distribution: **12** high, **3** medium, **0** low. Overall = min(median high, localization high, scope medium) = **medium** — the facts are firm; the task-graph shape depends on U2/U4/U6.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Is the FEAT-704 branch a merge base or a salvage source?** — *Resolved (owner, 2026-10-25)*: "we can discard that branch because was focused on sidemantic, that is discarded, or re-used the code no related to sidemantic" → salvage source only.
  *Resolves claims*: C1, C4

### Unresolved (defer to spec / implementation)

- [ ] **U2 — Stay inside FEAT-704 (spec rev 0.3; TASK-4467/4468 re-scoped; TASK-4482 dropped) or supersede with a new FEAT id?** — *Owner*: Jesus
  *Blocks claims*: C2 · *Plausible answers*: a) amend FEAT-704 (recommended — 20 TASK ids reserved, spec ~80% unchanged) · b) new FEAT superseding 704, 704 closed as abandoned
- [ ] **U3 — Rust phase: own FEAT now or after the Python compiler ships? Crate inside the satellite (`packages/ai-parrot-semantic/rust/`, navrules style) or a separate distribution?** — *Owner*: Jesus
  *Blocks claims*: C10, C12 · *Plausible answers*: a) defer; rev2 fixes the IR shape and the `THIRD_PARTY.md` rule (recommended) · b) own FEAT now, crate inside the satellite · c) own FEAT now, separate distribution
- [ ] **U4 — v1 join scope: keep the branch's declared one-to-many joins with fan-out rejection, or enforce "sin joins en v1" (single-table models)?** — *Owner*: Jesus
  *Blocks claims*: C5, C15 · *Plausible answers*: a) keep one-to-many + fan-out rejection (recommended — already tested) · b) single-table only; joins wait for the BSL/Rust phase
- [ ] **U5 — How is "BSL/Ibis reserved for the joins phase" recorded against the Ibis NO-GO?** — *Owner*: Jesus
  *Blocks claims*: C7 · *Plausible answers*: a) rev 0.3 note re-scoping the NO-GO to connections, compile-only re-evaluable by a later spec (recommended) · b) research text only, no repo commitment
- [ ] **U6 — Who creates `packages/ai-parrot-semantic/` first, FEAT-713 or FEAT-704 rev2, and does the other "extend" with a byte-level check?** — *Owner*: Jesus
  *Blocks claims*: C8 · *Plausible answers*: a) rev2 creates it (owns the generic layer); FEAT-713 M1 → "extend" · b) FEAT-713 creates it as written; rev2 M1 → "extend" (resolves 713 Q10)

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-704`** (amend `sdd/specs/semantic-layer.spec.md` to rev 0.3) — *Rationale*: the architectural fork is closed by the owner's 2026-10-21 decision block and the 2026-10-25 branch disposition; localization is high-confidence and 62% of the code exists; U2–U6 are spec-level scoping choices for §8, not alternatives to brainstorm.

Suggested shape of the amendment: M1 skeleton (owner per U6) → M2/M3 contracts and policy (salvage) → M4 typed model + loader (new, clean-room) → M5 sole compiler + golden tests → M6–M11 salvage with import re-verification and the two ledger issues → M12 removed. Rust phase as a follow-up FEAT referencing this proposal §3.

### Alternatives

- **`/sdd-brainstorm`** — only if U4 (single-table v1) or U3 (Rust now) is answered in a way that reopens the compiler design.
- **`/sdd-task`** — not applicable; this is a multi-module amendment.
- **Manual review** — read `sdd/state/FEAT-704/rev2/findings/F004` and `F009` before deciding U2/U6; they quantify what the branch gives for free.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-704/rev2/state.json` |
| Source (raw) | `sdd/state/FEAT-704/rev2/source.md` |
| Research plan | `sdd/state/FEAT-704/rev2/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-704/rev2/findings/F001-*.md` … `F015-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-704/rev2/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed** (profile `default`):
- Files read: 36 / 40
- Grep calls: 12 / 25
- Git calls: 7 / 10
- Wiki queries: 7 queries + 3 pages (free)
- Wall time: ~4,380 s / 300 s — exceeded by interactive pacing, not query volume; all 15 planned queries ran, none skipped, so the run is recorded as complete, not truncated
- Truncated: **no**

**Mode determination**: `auto` → `enrichment` (additive re-decision over an existing feature; no failure to explain).

**Gates**: autonomous run — plan and review gates were not presented; `approved_by_user: false` is recorded in `state.json`, and this document carries the Q&A as §5 Unresolved for `/sdd-spec` §8.

**State directory**: kept under the existing `sdd/state/FEAT-704/` as `rev2/` because this proposal amends an approved spec whose TASK ids are already reserved; a new FEAT id is reserved by `/sdd-spec` only if U2 is answered "supersede".

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (sequential research, wiki-first) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Fable 5.1) |
