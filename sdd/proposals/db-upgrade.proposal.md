---
id: FEAT-884
title: "parrot self migration — packaged, ledger-tracked schema migrations for parrot-owned tables (navigator.ai_bots first), modelled on navauth self upgrade"
slug: db-upgrade
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-11-12
  summary_oneline: "parrot self migration — versioned DB schema migrations for parrot tables (starting with navigator.ai_bots), mirroring navauth self upgrade"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [database, schema-migrations, cli, ai-bots, postgres]
research_state: sdd/state/FEAT-884/
created: 2026-11-12
updated: 2026-11-12
---

# FEAT-884 — `parrot self migration`: packaged, ledger-tracked schema migrations for parrot-owned tables

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-884/`](../state/FEAT-884/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at `sdd/state/FEAT-884/source.md`.

> db-upgrade -- en navigator-auth implementamos "navauth self upgrade" para actualizar cambios en tablas y
> mantener up-to-date cambios en las estructuras de las tablas, debemos imitar eso en parrot con
> "parrot self migration" para permitir que los cambios en tablas relacionadas (empezando con
> navigator.ai_bots) se documenten y permitan ejecutar una migración efectiva de cambios de manera fácil

**Initial signals** (extracted, not interpreted):
- Verbs: "implementamos", "imitar", "permitir" → feature-shaped (enrichment).
- Named entities: `navauth self upgrade` (navigator-auth), `parrot self migration`, `navigator.ai_bots`.
- Components / labels: none (inline source).
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

The request is to give parrot what navigator-auth got with `navauth self upgrade`: schema changes to
parrot-owned tables written as versioned SQL files that ship with the package, are recorded in a ledger
table, and are applied with one command, `parrot self migration`. `navigator.ai_bots` is the first
target, and the need is concrete:
- The table is defined twice, by the strict `BotModel` in `packages/ai-parrot/src/parrot/models/bots.py`
  and by the destructive `packages/ai-parrot-server/src/parrot/handlers/creation.sql`, and the two have
  already drifted.
- Every column change since April has been shipped as a hand-run script in `sdd/migrations/`, with no
  order and no record of which environment ran it.
- Because `BotModel` is strict, a single missing column breaks every bot load.

The reference design is navigator-auth's FEAT-110:
- SQL files numbered per set (`sql/<set>/NNN_*.sql`).
- A sha256 ledger keyed by `(set, filename)`.
- An advisory lock and one transaction per file.
- `--check` and exit codes 0–3.
- An admin connection string with a fallback.
- Startup only warns about pending files.

Parrot already has a ledger runner of its own, `parrot-studio-migrate`, but it only covers the Agent Studio
tables. The user decided:
- Build a new runner in the navauth style and keep Studio's ledger separate.
- Cover `ai_bots` and the `navigator.*` tables that create themselves at runtime.
- Support both idempotent files and an explicit `baseline` verb.
- Make the command a verb group.
- Move the `ai_bots` scripts into the package and keep `creation.sql` for fresh installs only.

A spec can follow directly.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-884/findings/`. Each cites the finding ID(s) that justify
> its inclusion. **No fabricated paths or symbols.** Citations were checked with the
> `sdd-contract-probe` fixed commands (153 checks, 150 verified — see §7).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/self_/cli.py` | `self_group` | 1-19 | click group `parrot self` (managed runtime `~/.parrot`); the `migration` group is registered here, its implementation imported lazily | F012, F018 |
| 2 | `packages/ai-parrot/src/parrot/self_/cli.py` | `doctor` | 58-84 | readiness checks with ✓/✗ and `fix:` hints — home for a read-only "pending schema migrations" row | F012 |
| 3 | `packages/ai-parrot/src/parrot/cli/__init__.py` | `cli._lazy_commands` | 170-194 | root `LazyGroup` registry (`self` → `parrot.self_.cli`); supports satellite-provided commands with install hints | F012, F013, F021 |
| 4 | `packages/ai-parrot/src/parrot/models/bots.py` | `BotModel` | 100-468 | strict asyncdb model of `navigator.ai_bots` (49 fields, `Meta.strict=True`) — the target schema | F003 |
| 5 | `packages/ai-parrot/src/parrot/models/bots.py` | `_fold_legacy_bot_columns` | 43-44 | compat shim tolerating pre-fold databases — evidence of unknown schema versions in deployed environments | F003 |
| 6 | `packages/ai-parrot-server/src/parrot/handlers/creation.sql` | `navigator.ai_bots` | 12-81 | destructive bootstrap DDL (`DROP … CASCADE` at line 9) with hand-appended ALTERs; lacks FEAT-752 columns | F001, F002, F003 |
| 7 | `sdd/migrations/ai-bots-homologate-botmodel.sql` | `ai-bots-homologate-botmodel` | 1-40 | idempotent additive catch-up (`Status : pending`) — seed for the baseline migration | F003, F005, F020 |
| 8 | `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` | — | 1-12 | de-facto file convention: own `BEGIN/COMMIT`, `ADD COLUMN IF NOT EXISTS`, rollback in comments | F005, F017 |
| 9 | `sdd/migrations/` | — | — | 15 loose, unpackaged, unordered SQL files (8 ai_bots schema, data fixes, planogram/ontology data) | F004, F017, F020, F021 |
| 10 | `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py` | `apply_studio_migrations` | 191-216 | existing parrot ledger runner (`navigator.ai_studio_migrations`, console script `parrot-studio-migrate`), Studio tables only | F010, F013 |
| 11 | `packages/ai-parrot/src/parrot/conf.py` | `default_dsn` | 65-77 | runtime DSN from `DB*` settings; no admin/DDL DSN exists | F014 |
| 12 | `packages/ai-parrot/src/parrot/conf.py` | `PARROT_SCHEMA` | 121-122 | configurable schema / bots-table names (`PARROT_SCHEMA`, `PARROT_BOTS_TABLE`) | F001, F014 |
| 13 | `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py` | `PostgresTaskMemoryStore.verify_schema` | 612-642 | third in-repo pattern: startup version check + explicit `apply_migrations` at deploy | F011 |
| 14 | `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` | `test_load_database_bots_untouched` | — | byte-freeze gate on `creation.sql` + BotModel docstring DDL (`_SANCTIONED_REWRITES`) | F003 |
| 15 | `../navigator-auth/navigator_auth/migrations/runner.py` | `upgrade` | 278-287 | reference runner: `(set, filename)` sha256 ledger, session advisory lock, transaction per file | F007 |
| 16 | `../navigator-auth/navigator_auth/migrations/catalog.py` | `discover` | 62-113 | reference catalog: `sql/<set>/NNN_*.sql`, ordered `MIGRATION_SETS`, `render_sql` placeholders | F008 |
| 17 | `../navigator-auth/navigator_auth/migrations/cli.py` | `build_parser` | 21-41 | reference CLI: `navauth self upgrade --check/--dsn/--user/--set/--fail-fast`, exit codes 0-3 | F007, F019 |
| 18 | `../navigator-auth/navigator_auth/migrations/startup.py` | `warn_pending_migrations` | 56-79 | reference startup behaviour: read-only warning, never DDL | F009 |
| 19 | `packages/ai-parrot/tests/self_/test_self_cli.py` | — | — | test home for the new CLI verbs | F015 |

### 2.2 Constraints Discovered

- **Strict model.** `BotModel` selects every declared field by name; a column the code expects but the
  table lacks fails *every* bot load (`column "toolkit_config" does not exist`).
  *Implication*: migrations must run before deploying code that adds fields; a model-vs-DB column check is
  high value. *Evidence*: F003
- **`creation.sql` is not a migration.** It starts with `DROP TABLE IF EXISTS navigator.ai_bots CASCADE`,
  its constraint/trigger statements fail on re-run, and it lacks the five FEAT-752 columns.
  *Implication*: the baseline must be rewritten as guarded, additive SQL. *Evidence*: F002, F003
- **Byte-freeze gate.** `creation.sql` and the BotModel docstring DDL are frozen by
  `test_storage_gates.py::test_load_database_bots_untouched`; deliberate edits need a `_SANCTIONED_REWRITES`
  entry. *Implication*: demoting `creation.sql` (U5) is a sanctioned rewrite. *Evidence*: F003
- **Configurable names.** `PARROT_SCHEMA` / `PARROT_BOTS_TABLE` are configurable, yet every existing
  script hard-codes `navigator.ai_bots`. *Implication*: SQL uses placeholders rendered from config (navauth's
  `render_sql`). *Evidence*: F003, F008, F014
- **SQL must ship in-package.** `sdd/` is in no wheel; navauth decided "SQL lives in-package"
  (`test_wheel_contains_sql`). *Implication*: the catalog is package data loaded with `importlib.resources`.
  *Evidence*: F004, F019, F020
- **Cross-distribution placement.** The `ai_bots` DDL ships from ai-parrot-server, while `BotModel` and the
  `self_` CLI live in core, and runtime self-created tables are spread over core and server.
  *Implication*: the catalog must discover sets contributed by installed distributions (entry points), not
  a hard-coded tuple like navauth's `MIGRATION_SETS`. *Evidence*: F001, F008, F011, F012, F013
- **asyncdb `execute()` returns errors instead of raising.** *Implication*: the runner uses a raw asyncpg
  connection and checks every statement (navauth `acquire_raw` / `execute_checked`). *Evidence*: F007, F019
- **Self-transacted scripts.** Existing `sdd/migrations` files carry their own `BEGIN/COMMIT` and rollback DDL in
  comments. *Implication*: strip `BEGIN/COMMIT` when importing into a per-file-transaction runner.
  *Evidence*: F005
- **An existing ledger already lives in `navigator`.** `navigator.ai_studio_migrations` has different semantics
  (integer versions, body checksum, xact lock, MANIFEST). *Implication*: per U1 it stays separate; the new
  ledger needs a clearly distinct name. *Evidence*: F010
- **Startup never runs DDL.** navauth warns only, Studio never migrates at startup, task-memory verifies and
  refuses. *Implication*: startup/doctor integration is read-only. *Evidence*: F009, F010, F011
- **No admin credential.** `conf.py` only builds the runtime `default_dsn`. *Implication*: add an optional
  admin DSN setting with fallback + notice (navauth precedence). *Evidence*: F014
- **Naming.** `parrot self` is scoped to the managed runtime, `self update` exists, and `migrate_legacy_uv`
  already uses "migration" inside `self_`. *Implication*: help text must make clear this is *database
  schema* migration. *Evidence*: F012, F018

### 2.3 Recent History (Relevant)

| Commit | When | Repo | Message / effect | Evidence |
|--------|------|------|------------------|----------|
| `089ff13` | 2026-11-12 | navigator-auth | hardening of `navauth self upgrade`: bounded upgrade lock, quoted CLI DSN, startup warning scoped to enabled sets | F016 |
| `788cab0` | 2026-11-11 | navigator-auth | FEAT-110 `new-command-migration` spec (implemented same day as TASK-159..170) | F016 |
| — | 2026-11-10 | ai-parrot | FEAT-872 legacy uv migration (`migrate_legacy_uv`) in `self_` | F018 |
| — | 2026-11-02 | ai-parrot | FEAT-633 (PR #1823) ships `parrot self`; ~22 installer-focused commits since | F018 |
| — | 2026-10-28 | ai-parrot | FEAT-752 suggestion columns (5 cols) — added to BotModel, never to `creation.sql` | F002, F003 |
| `4f05450930` | 2026-10-22 | ai-parrot | `BotModel` tolerates legacy columns because "the fold migrations are still pending on staging/prod" | F003 |
| — | 2026-10-21 | ai-parrot | `creation.sql` re-homologated to BotModel "field-for-field (44 columns)" | F003 |
| `fd6748e669` | 2026-07-17 | ai-parrot | model change shipped before its DDL was applied everywhere → compat shim (TASK-4577) | F003 |

Column timeline of `navigator.ai_bots` (F003, F017): reranker/parent_searcher config (04-29) → prompt_config
(04-30) → embedding_model fold (05-06) → legacy LLM columns folded into model_config (07-14) →
toolkit_config/mcp_servers (09-23) → language nullable (10-08) → 44-column homologation (10-21) →
suggestion columns (10-28). Every step was tracked by hand.

---

## 3. Probable Scope

### What's New

- **Core migrations package** (catalog + runner + Pydantic status/report models), modelled on navauth
  FEAT-110 and shaped by U1:
  - Files are `sql/<set>/NNN_<name>.sql`, shipped as package data.
  - Sets are discovered from installed distributions through an entry-point group.
  - Files are checksummed with sha256 and each one is reported as APPLIED, PENDING or CHANGED.
  - An advisory lock prevents concurrent runs, and each file runs in its own transaction.
  - Every statement's result is checked, and errors are sanitized so credentials are never printed.
- **Parrot ledger table** in `PARROT_SCHEMA`, keyed by `(migration_set, filename)`, distinct from
  `navigator.ai_studio_migrations` (U1).
- **`bots` set** for `navigator.ai_bots`:
  - `001` is a guarded baseline built from `ai-bots-homologate-botmodel.sql` plus the FEAT-752 columns.
  - The fold and data-fix steps follow in the order of their git dates.
  - Everything is templated with `{schema}` / `{bots_table}`.
- **Runtime-table sets (U2)** for the `navigator.*` tables that create themselves at runtime with
  `CREATE TABLE IF NOT EXISTS` (F011 names `ui_surfaces`, `ui_surface_shares`, `crew_definitions`,
  `metric_definitions`, `studio_drafts`, `ai_skills_catalog`, `service_scheduler`, …). Each gets a baseline
  that matches today's runtime DDL, so that later column changes become versioned files.
- **CLI verb group (U4):**
  - `parrot self migration status`: the `--check` equivalent, with exit code 1 when anything is pending or changed.
  - `upgrade [--set …] [--fail-fast] [--reapply-changed]`
  - `baseline`: records files as applied without running them (U3).
  - `new <set> <name>`: scaffolds the next `NNN_*.sql`.
  - All verbs take `--dsn`; exit codes are 0 ok, 1 pending, 2 failed, 3 config.
- **Read-only integration:** a row in `parrot self doctor`, plus a startup warning where database bots
  are loaded.
- **Documentation and a guard test:** a "how to add a migration" convention, and a test that the
  `bots` set covers every `BotModel` column.

### What Changes

- **`packages/ai-parrot/src/parrot/self_/cli.py`::`self_group`**: registers the `migration` group with
  lazy imports. *Evidence*: F012
- **`packages/ai-parrot/src/parrot/self_/cli.py`::`doctor`**: adds a pending-migrations check.
  *Evidence*: F012
- **`packages/ai-parrot/src/parrot/conf.py`::`default_dsn`**: adds an optional admin DSN setting,
  falling back to `default_dsn` with a notice. *Evidence*: F014
- **`packages/ai-parrot-server/src/parrot/handlers/creation.sql`::`navigator.ai_bots`**: becomes a
  fresh-install-only file whose header points to `parrot self migration`. This is a sanctioned rewrite
  in `test_storage_gates.py` (U5). *Evidence*: F002, F003
- **`sdd/migrations/`**: the `ai_bots` scripts move into the packaged `bots` set and are removed from
  here. The planogram, ecotank and ontology files stay (U5). *Evidence*: F017, F020
- **Runtime-DDL modules of the U2 tables**: their schema becomes owned by a migration set. Whether the
  runtime `CREATE TABLE IF NOT EXISTS` stays as a create-on-first-use fallback is a spec decision
  (§5). *Evidence*: F011

### What's Untouched (Non-Goals)

- Down/rollback migrations (navauth non-goal); rollback DDL stays as comments where it exists.
- Data migrations and non-parrot domain data (planogram, ecotank, ontology seeds in `sdd/migrations/`).
- Agent Studio's runner and its `navigator.ai_studio_migrations` ledger (U1 — kept apart for now).
- task-memory's own `verify_schema` / `apply_migrations` mechanism.
- External migration tools (alembic etc.) and non-Postgres databases.
- Running DDL at application startup.

### Patterns to Follow

- **navauth FEAT-110:**
  - Module split: catalog / runner / checks / startup / cli.
  - Sets, the `(set, filename)` ledger, `--check` semantics, exit codes 0–3.
  - Admin connection string precedence, sanitized errors.
  - The lessons from its post-ship hardening: a bounded lock, a quoted DSN, and a startup warning scoped to enabled sets.

  *Evidence*: F006, F007, F008, F009, F016, F019
- **Agent Studio runner:**
  - Package data loaded with `importlib.resources`.
  - Safe when two runners start at once.
  - `--print`, which emits the pending SQL for a DBA.
  - Tests split into file-only tests and live-database tests that skip when PostgreSQL is unreachable.

  *Evidence*: F010, F015
- **`LazyGroup`:** lazy imports and install hints for commands whose code lives in another
  distribution. *Evidence*: F012, F013
- **Check at startup, apply at deploy** (task-memory `verify_schema`). *Evidence*: F011

### Integration Risks

- **Pre-existing databases at unknown versions:** the scripts were partly applied by hand, and the fold
  scripts `DROP` columns. Mitigation: guard every statement with `IF EXISTS` / `IF NOT EXISTS`, and use
  `baseline` (U3) for environments known to be current. Keep `_fold_legacy_bot_columns` until every
  environment reports clean. *Evidence*: F003, F017, F020
- **The runtime database user may lack DDL rights.** Mitigation: an admin DSN option with a fallback and a
  notice. *Evidence*: F014, F019
- **U2 widens scope across distributions and live features.** Some tables, such as `studio_drafts` and
  `ai_skills_catalog`, already appear both in runtime DDL and in a Studio migration. `crew_definitions`
  arrived only recently, with FEAT-860. Mitigation: inventory the tables in the spec and give each one
  exactly one owner. *Evidence*: F010, F011
- **Two ledgers in `navigator`.** Mitigation: a distinct ledger name, and help/doctor text that names both.
  *Evidence*: F010
- **`self_` is a high-churn installer package.** Mitigation: the runner gets its own package;
  `self_/cli.py` only registers the verbs. *Evidence*: F018
- **The byte-freeze gate on `creation.sql`.** Mitigation: register the rewrite in `_SANCTIONED_REWRITES`.
  *Evidence*: F003

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `parrot self` is a click group in core `self_/cli.py`, lazily registered; adding a verb is one more command | F012, F013 | high | direct reads |
| C2 | `navigator.ai_bots` is defined by the strict `BotModel` (core, 49 fields) and by `creation.sql` (server) | F001, F002, F003 | high | grep + read, probe-verified |
| C3 | `creation.sql` is destructive, partly non-idempotent and drifted (no FEAT-752 columns) — not usable as a migration | F002, F003 | high | DROP at line 9 verified; `enable_suggestions` count 0 |
| C4 | ai_bots changes are tracked only by hand-run loose SQL in `sdd/migrations/` (15 files, 8 ai_bots schema) | F005, F017, F020, F021 | high | `git ls-files` + per-file inspection |
| C5 | Deployed environments sit at unknown ai_bots schema versions | F003 | medium | commit message + compat shim; no live DB inspected |
| C6 | navauth self upgrade = sets + `(set, filename)` sha256 ledger + advisory lock + per-file txn + `--check` + exit 0-3 + admin DSN + read-only startup; no rollback, no baseline | F006, F007, F008, F009, F016, F019 | high | spec + code read, verified |
| C7 | Parrot already ships a Studio-only ledger runner (`parrot-studio-migrate`) that does not cover ai_bots | F010, F013 | high | migrate.py + server pyproject |
| C8 | Parrot has ≥4 independent schema mechanisms | F004, F010, F011 | high | each cited directly |
| C9 | Runtime self-created tables handle CREATE but not column evolution | F011 | medium | ~70 of 163 CREATE TABLE sites inspected |
| C10 | parrot conf has no admin/DDL DSN | F014 | medium | absence grep scoped to conf.py |
| C11 | Migration SQL must be templated (configurable schema/table names) | F003, F008, F014 | high | conf.py read |
| C12 | Migration SQL must ship inside a package | F004, F019, F020 | high | layout + navauth decision |
| C13 | `creation.sql` + docstring DDL are byte-frozen by a test gate | F003 | medium | from a wiki lesson; test file exists, symbol not read |
| C14 | The verb name risks confusion with `self update` / `migrate_legacy_uv` | F012, F018 | medium | names verified; user impact is judgement |
| C15 | `parrot setup` / `parrot install` provision no DB tables | F021 | medium | absence grep scoped to two packages |
| C16 | An ai_bots version chain can be reconstructed from git dates of `sdd/migrations` files | F017, F003 | medium | order inferred; some files edited after creation |
| C17 | The runner must not rely on asyncdb `execute()` to detect failure | F007, F019 | high | documented navauth gotcha with code |
| C18 | The ai_bots DDL ships from ai-parrot-server while BotModel and the CLI are core | F001, F012 | high | file locations verified |

Distribution: **11** high, **7** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Which runner should `parrot self migration` build on?** — *Resolved*: navauth-style, Studio
  apart — new generic runner mirroring navauth (sets, `(set, filename)` ledger); Studio keeps its own ledger
  for now. *Resolves claims*: C7, C8
- [x] **U2 — What is the v1 scope?** — *Resolved*: ai_bots + runtime tables — also cover `navigator.*` tables
  that self-create at runtime (ui_surfaces, crew_definitions, …). *Resolves claims*: C8, C9
- [x] **U3 — How are databases with hand-applied changes adopted?** — *Resolved*: idempotent + baseline —
  files stay idempotent (first run is a no-op where applied) AND a `baseline`/stamp records files without
  running them. *Resolves claims*: C5, C16
- [x] **U4 — CLI shape?** — *Resolved*: group with verbs —
  `parrot self migration status | upgrade | baseline | new` (`new` scaffolds the next `NNN_*.sql` for a set).
  *Resolves claims*: C1, C14
- [x] **U5 — Fate of `sdd/migrations/` and `creation.sql`?** — *Resolved*: move ai_bots scripts into the
  package set (removed from `sdd/migrations`); planogram/ontology files stay; `creation.sql` becomes
  fresh-install only and points to the command (sanctioned rewrite). *Resolves claims*: C3, C4, C13

### Unresolved (defer to spec / implementation)

- [ ] **Exact v1 inventory of runtime self-created tables (U2), and whether their runtime
  `CREATE TABLE IF NOT EXISTS` stays as a first-use fallback or is removed in favour of the migration set.**
  Only ~70 of 163 `CREATE TABLE` sites were inspected. — *Owner*: tbd. *Blocks claims*: C9
- [ ] **Where each set lives.** For example, `bots` could sit in core next to `BotModel` or in
  ai-parrot-server next to `creation.sql`. The entry-point group name for satellite sets also has to be
  chosen. — *Owner*: tbd. *Blocks claims*: C18
- [ ] **Names of the ledger table and of the admin connection-string setting** (navauth uses
  `schema_migrations` and `AUTH_ADMIN_DSN`). — *Owner*: tbd. *Blocks claims*: C10
- [ ] **Coordination with FEAT-860** (`navigator.crew_definitions`, which creates itself at runtime and
  arrived recently): does its DDL become a migration set baseline in v1? — *Owner*: tbd. *Blocks claims*: C9

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-884`**. *Rationale*:
- The code locations are known with high confidence and the reference design is concrete.
- The two architectural choices, which runner (U1) and how wide the scope is (U2), were settled in Q&A.
- The remaining items in §5 are spec-level details, not new forks.

### Alternatives

- **`/sdd-brainstorm FEAT-884`**: if you want to compare runner designs again, for example unifying with
  Studio's ledger now instead of later.
- **Manual review**: read `sdd/state/FEAT-884/findings/` before writing the spec, especially F010 (Studio
  runner) and F011 (runtime tables), given the widened U2 scope.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-884/state.json` |
| Source (raw) | `sdd/state/FEAT-884/source.md` |
| Research plan | `sdd/state/FEAT-884/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-884/findings/F001-*.md` … `F021-*.md` (lane originals in `findings/.audit/`) |
| Citation probe | `sdd/state/FEAT-884/citation_probe.json` |
| Synthesis (JSON) | `sdd/state/FEAT-884/synthesis.json` |

**Budget consumed** (profile `default`, parallel lanes codebase / git / wiki):
- Files read: 18 / 40
- Grep calls: 22 / 25
- Git calls: 8 / 10
- Wall time: ~302 s / 300 s (codebase lane was the longest; no query skipped)
- Truncated: **no**

**Merge**: 27 lane findings → 20 canonical (7 merged), plus 1 parent follow-up (F021).
**Citation probe**: 153 fixed-command checks run inline (same commands as `sdd-contract-probe`):
- 150 verified.
- 2 stale: the server `models/bots.py` is a re-export shim, and one runner line range was shifted when two findings were merged.
- 1 missing: a historical pre-move path.

All three are tagged in the owning findings' Notes.

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs: "implementamos", "imitar", "permitir").

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Code (Opus 5.5) |
