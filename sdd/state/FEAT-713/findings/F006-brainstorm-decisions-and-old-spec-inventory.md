---
id: F006
query_id: Q046, Q047
type: read
intent: "Inventory of brainstorm decisions and of the old spec's modules M8–M10, acceptance criteria, risks and open questions, as one-line items to re-validate."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_ids: [FC-009]
---

# F006 — Re-validation inventory: 9 brainstorm decisions, 10 modules, 17 acceptance criteria, 15 risks, 2 open questions, 11 codex suggestions

## Summary

The brainstorm (Option B: dedicated accounting compiler — YAML → Pydantic IR → sqlglot AST → single-scan
SQL; DuckDB over Arrow for DataFrames) resolved nine questions; the spec restates them (§8) and refines
two with the codex design review (sign key → `amount_convention`; audit → fail-closed). Options A (profile
on top of the generic semantic-layer engine), C (skill/prompt) and D (Flowtask materialisation) were
rejected or deferred. Items whose premise depends on "FEAT-704 is paused / sidemantic" are marked ⚠ below;
they are the ones the revision must re-decide. Everything else is accounting-domain design that does not
depend on the state of the package.

**Brainstorm decisions (brainstorm :365-373, spec :1065-1073)**
1. ⚠ Package home: `parrot.semantic.accounting` in `ai-parrot-semantic`, standalone, *not an engine of FEAT-704*; "this feature creates the satellite skeleton without sidemantic".
2. Models in git at `<models_dir>/<tenant>/<model>.yaml`; `model_hash` tied to a commit; admin UI v2.
3. Refuse requests (incl. cumulative windows) spanning a membership change; slice + `UNION ALL` is v2.
4. Explicit required sign key, no default (spec: `amount_convention` with four values).
5. `parent:` hierarchy selectors are v2 (unless spike S3 says otherwise).
6. Natural calendar by `posting_date` + cumulative YTD/QTD/MTD in v1; fiscal calendars are non-goals.
7. Live assertions both on demand (`parrot finance validate --live`) and scheduled.
8. Own signed `AccountingAuditEntry` (core signers, `storage(json_str)`), `lineage_ref`, lineage rebuilt not stored; `AuditLedgerEntry` not extended; spec adds `FINANCE_AUDIT_MODE=required`.
9. ⚠ Lowering into the generic layer "deferred until FEAT-704 resumes".

**Modules (spec §3)**
- ⚠ M1 satellite skeleton (create pyproject/README/`__init__`/`version.py`, root uv source, release entry, `test-semantic` CI job, nightly).
- M2 contracts & errors (`accounting/models.py`, `errors.py`) · M3 grammar (Pratt parser, closed AST) · M4 loader / `ChartSnapshot` / per-interval validation · M5 compiler + golden tests (duckdb, postgres, bigquery) + self-check.
- M6 runtimes: `runtime/arrow.py`, `runtime/duckdb.py` (`DuckDBRunner`: root connection, `con.register`, per-thread cursor, `to_thread`, semaphore `FINANCE_DUCKDB_THREADS`, `fetch_arrow_table`), `runtime/database.py` (`DatabaseRunner` over `SQLToolkit.execute_query`).
- M7 audit ledger (`AccountingAuditLedger(signer, storage, mode)`).
- M8 `AccountingToolkit` (`tool_prefix="finance"`; `list_metrics`, `explain_metric`, `query_metric`, `validate_model`; kwargs `models_dir`, `database_toolkit: SQLToolkit`, `frame_provider`, `policy_guard: DatasetPolicyGuard`, `ledger`, `duckdb_threads`), `ModelCatalog`, `cli.py` (`parrot finance validate|explain`), core CLI lazy registration, `.parrot/mcp-toolkits.yaml` example.
- M9 `live.py` `run_live_validation` + server adapter `ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` (`@schedule(ScheduleType.DAILY)`, `register_object_schedules`).
- M10 docs `docs/semantic/accounting-metrics-layer.md` + README sections ("the FEAT-704 layering contract").

**Acceptance criteria (spec :816-832)**
- ⚠ AC1 installs as PEP 420 satellite; `import parrot.semantic.accounting` works with/without `duckdb`; no module imports `sidemantic`, `parrot.semantic.*` outside `accounting`, or `ai-parrot-server`.
- ⚠ AC2 `version.py` / `release.py` entry identical to `origin/feat-FEAT-704-semantic-layer`; layering note in README.
- AC3 `amount_convention` mandatory; four normalisations proven by golden SQL + DuckDB execution.
- AC4 `load_model` reports every problem; completeness/overlap/exclusions per interval.
- AC5 `model_hash` covers model + chart snapshot; `sql_hash` covers dialect + SQL; 50 compiles ⇒ one hash; goldens for duckdb/postgres/bigquery.
- AC6 closed grammar; `GrammarError` with position.
- AC7 membership-boundary requests refused with `PeriodSpansMembershipChange`.
- AC8 cumulative mtd/qtd/ytd over natural calendar; cumulative ratio = ratio of cumulative sums.
- AC9 empty groups ⇒ 0; zero denominators ⇒ NULL + warning; Decimal end to end; floats rejected unless `allow_float`.
- AC10 same compiled AST executes on DuckDB (Arrow-registered pandas and polars frames, per-thread cursors, 8 concurrent requests) and through `SQLToolkit.execute_query` with no change to `SQLToolkit` or `DatasetManager`; Postgres parity when a DSN is provided.
- AC11 every executed query appends a signed `AccountingAuditEntry`; `FINANCE_AUDIT_MODE=required` fails closed; `lineage_ref` rebuilds the `Lineage`.
- AC12 compiler self-check before SQL is returned.
- AC13 exactly four `finance_*` tools; PBAC filtering through `DatasetPolicyGuard`; no result cache.
- AC14 `parrot finance validate <model> [--live]` lazily registered in core CLI.
- AC15 server adapter registers a daily live validation; `chart_drift` / `assertion_failed` flags; `block` assertion makes `query_metric` raise.
- ⚠ AC16 CI runs the satellite tests (`test-semantic` job + nightly); ruff TID251; docs in `docs/semantic/…`.
- AC17 no breaking change to public API; `pyarrow` stays a core dependency; `duckdb` only an extra of the satellite.

**Non-goals relevant to FEAT-880 (spec :69-84)**: no joins to dimension tables; no result caching (compile cache only); ⚠ "Materialisation via Flowtask and lowering into the generic semantic layer — both deferred until FEAT-704 resumes"; **"Modifying `SQLToolkit`, `DatasetManager`, `AuditLedgerEntry` or `parrot/clients/base.py`"**.

**Risks (spec :1018-1046)**: ⚠ FEAT-704 merge collision · sqlglot rendering drift (pin + goldens) · account in two sets · membership change inside window · chart drift · set valid after period · unknown dimension/filter · division by zero · NULL vs 0 · DuckDB connection across threads · pandas object/float amounts · `execute_query` default limit 1000 · PBAC resource naming `accounting:<tenant>:<model>:<metric>` · audit fail-closed in dev · scheduler call site not found · name collision with core `finance` extra (`ta-lib`).

**Open questions (spec :1074-1075)**: ⚠ Q10 FEAT-704 spec amendment ("extend the skeleton created by FEAT-713") — moot, the skeleton was created by FEAT-704 · Q11 server scheduler call site — still open (see FC-007).

**Codex design review (spec :1087-1097)**: S1 immutable `ChartSnapshot` · S2 one IR, per-dialect rendering · S3 compiler self-check · S4 `amount_convention` · S5 per-interval completeness · S6 numeric/empty semantics · S7 accounting kept separate from the DatasetManager catalog (`frame_provider`) · S8 no shared DatasetManager caches · S9 separate durable audit contract, fail-closed · S10 structural vs live assertions (`on_failure: flag | block`) · ⚠ S11 ownership of the `parrot.semantic` satellite (confirmed + escalated).

## Citations

- path: `sdd/proposals/accounting-metrics-layer.brainstorm.md`
  lines: 12-12
  symbol: `Recommended Option`
  excerpt: |
    **Recommended Option**: B

- path: `sdd/proposals/accounting-metrics-layer.brainstorm.md`
  lines: 52-158
  symbol: `Options Explored`
  excerpt: |
    ### Option A: Express the accounting model as a profile on top of the generic semantic layer engine (BSL / Ibis)
    ### Option B: Dedicated accounting compiler — YAML → Pydantic IR → sqlglot AST → single-scan SQL; DuckDB over Arrow for DataFrames — *recommended*
    ### Option C: Keep the knowledge in a skill / prompt (status quo)
    ### Option D: Pre-materialised metric tables via Flowtask (ETL), agents only read

- path: `sdd/proposals/accounting-metrics-layer.brainstorm.md`
  lines: 365-373
  symbol: `Open Questions (resolved)`
  excerpt: |
    - [x] **Package home** → `parrot.semantic.accounting` in the `ai-parrot-semantic` satellite, as a **standalone package, not an engine** of FEAT-704. FEAT-704 is paused until sidemantic (AGPL-3.0) is migrated away; ...
    - [x] **Sign convention** → explicit required key `amount_sign: by_nature | signed`, no default.
    - [x] **Lowering into the generic layer** → deferred until FEAT-704 resumes; not committed in either spec now.

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 35-39
  symbol: `Problem Statement`
  excerpt: |
    FEAT-704 is also **paused** until its AGPL-3.0 dependency (sidemantic) is
    migrated away, so this layer cannot depend on it.

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 69-84
  symbol: `Non-Goals`
  excerpt: |
    - Result caching of any kind (compile cache only — codex S8).
    - Materialisation via Flowtask (brainstorm Option D) and lowering into the generic semantic layer (Option A) —
      both deferred until FEAT-704 resumes.
    - Modifying `SQLToolkit`, `DatasetManager`, `AuditLedgerEntry` or `parrot/clients/base.py` — the layer is purely
      additive to core (see §2 Integration Points).

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 92-97
  symbol: `Overview`
  excerpt: |
    The satellite skeleton created here is a **byte-level mirror of the one on `origin/feat-FEAT-704-semantic-layer`
    minus sidemantic** ...
    `parrot.semantic.accounting` never imports anything from `parrot.semantic.*` outside itself.

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 389-401
  symbol: `Module 1`
  excerpt: |
    ### Module 1: `ai-parrot-semantic` distribution skeleton (sidemantic-free)
    - **Responsibility**: make `parrot.semantic` an installable PEP 420 satellite ...

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 570-604
  symbol: `Module 6`
  excerpt: |
    ### Module 6: Runtimes — DuckDB over Arrow, and SQLToolkit
    `duckdb.py` owns one root `duckdb.connect()` (in-memory), registers Arrow tables with `con.register(name, table)`,
    executes on `root.cursor()` inside `asyncio.to_thread`, bounded by a semaphore of `FINANCE_DUCKDB_THREADS` ...

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 631-690
  symbol: `Module 8`
  excerpt: |
    `toolkit.py` — `AccountingToolkit(AbstractToolkit)` with `tool_prefix = "finance"`, constructor kwargs
    `models_dir`, `database_toolkit: SQLToolkit | None`, `frame_provider: Callable[[str], Awaitable[pd.DataFrame]] | None`,
    `policy_guard: DatasetPolicyGuard | None`, `ledger: AccountingAuditLedger | None`, `duckdb_threads`.
    ... no guard configured ⇒ allow (same semantics as `DatasetManager`).

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 692-720
  symbol: `Module 9`
  excerpt: |
    ### Module 9: Scheduled live validation (server adapter)
    - **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/live.py`;
      `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` (new)

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 722-727
  symbol: `Module 10`
  excerpt: |
    - **Path**: `docs/semantic/accounting-metrics-layer.md`, `packages/ai-parrot-semantic/README.md` (sections)

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 816-832
  symbol: `Acceptance Criteria`
  excerpt: |
    - [ ] AC1 `ai-parrot-semantic` installs as a PEP 420 satellite ...
    - [ ] AC10 The same compiled AST executes on DuckDB (Arrow-registered pandas and polars frames, per-thread cursors, 8 concurrent requests) and through `SQLToolkit.execute_query` without any change to `SQLToolkit` or `DatasetManager`; ...
    - [ ] AC17 No breaking changes to any existing public API; `pyarrow` stays a core dependency; `duckdb` is only an extra of the satellite.

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 1018-1046
  symbol: `Known Risks / Gotchas`
  excerpt: |
    - **FEAT-704 merge collision** — mitigated by mirroring its M1 files ...
    - **Scheduler call site** — the exact server location that constructs the scheduler was not found under `manager/` ...
    - **Name collision** — core already has an unrelated `finance` extra (`ta-lib`); never add dependencies there.

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 1065-1075
  symbol: `Open Questions`
  excerpt: |
    - [ ] Q10 FEAT-704 amendment — when FEAT-704 resumes, its M1 ("Distribution skeleton") must become "extend the skeleton created by FEAT-713" ...
    - [ ] Q11 Server scheduler call site — ... (no `SchedulerManager(` construction found under `manager/`).

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 1087-1097
  symbol: `Design Research Cross-Check`
  excerpt: |
    | S7 | Keep accounting execution separate from the DatasetManager catalog contract (architecture) | CONFIRM | ... frames arrive through an injected `frame_provider`; DatasetManager unmodified |
    | S11 | Resolve ownership of the `parrot.semantic` satellite before creating it (architecture) | CONFIRM + ESCALATE | ...

## Notes

- Stale-by-evidence (see FC-001/002/004/005/006/007): M1 entirely; AC2; the `test-semantic` job name in
  AC16; Q10; risk "FEAT-704 merge collision"; codex S11; the premise of decisions 1 and 9; the docs path
  in M10; the CLI and scheduler line anchors in M8/M9.
- Now-contestable (premise changed, decision not automatically wrong): "never imports `parrot.semantic.*`
  outside itself" (AC1) vs reuse of `SemanticAuditLedger`, `ConnectionResolver`/`Executor`, `PbacGate`,
  `SemanticModelLoader` conventions; `DatabaseRunner` over `SQLToolkit` vs the semantic `Executor` over
  `DatabaseQueryToolkit`; PBAC "no guard ⇒ allow" via `DatasetPolicyGuard` vs the fail-closed
  `DataPlanePolicyGuard` gate; tenant sub-directories vs the flat models dir + policy side-file;
  `FINANCE_AUDIT_MODE` vs `audit_required`; own `Grain` literal vs `parrot.semantic.models.Grain`.
- FEAT-880 dependency: the old spec's non-goal "Modifying DatasetManager" and codex S7 directly contradict
  FEAT-880 U4's wording that the DuckDB-backed dataset store is folded into this revision.
- The brainstorm body (options text, spikes S1-S4 at :351, "Does NOT Exist" list at :331) was read by
  headings only; spec lines 833-984 (codebase contract tables) were not re-read line by line — their
  anchors were re-checked independently in FC-007.
