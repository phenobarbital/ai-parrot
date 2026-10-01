# TASK-3926: Migration ledger probe, apply_studio_migrations and parrot-studio-migrate CLI

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W0 — Studio migrations + runner (M1, part 2: ledger probe, apply, CLI)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3924, TASK-3925
**Assigned-to**: unassigned

---

## Context

Spec §2.2 (probe: three read-only statements), §2.12 (properties, concurrent runners, CLI flags, supported PG),
§3 Module 1 skeleton (`LedgerState`, `read_ledger`, `apply_studio_migrations`, `main`), §4 fixtures. The probe logic
lives here so `backend.py` (TASK-3932) only maps a `LedgerState` to a backend.

---

## Scope

- `LedgerState(present, applied, server_version_num)` with `complete_for(required, manifest)` and
  `problems(required, manifest)` (missing / drift / unknown; also a host-created unique INDEX on
  `ai_skills_catalog(name)` alone → warning line, §7 gotcha).
- `read_ledger(conn)`: `SHOW server_version_num`; `SELECT to_regclass('navigator.ai_studio_migrations')`;
  `SELECT version, checksum … ORDER BY version`. Never DDL.
- `apply_studio_migrations(pool, *, dry_run=False) -> list[int]`: refuse PG < 14; per pending file:
  `studio_transaction` → execute body (its first statement takes the advisory lock) → re-read the ledger → skip if
  recorded → execute trailer → commit. Never called by `setup()`/`on_startup`.
- `main(argv)`: `--dsn`, `--dry-run`, `--verify` (exit 1 on any problem), `--print` (pending body+trailer for
  `psql -1 -v ON_ERROR_STOP=1 -f`), `--stamp` (calls `stamp_migrations`); console script `parrot-studio-migrate`.
- `tests/studio/storage/conftest.py` with the spec §4 fixtures (`studio_pool`, `_truncate_studio_tables`,
  `real_request`, `no_subprocess`).
- Integration tests listed below.

**NOT in scope**: Backend selection (`ensure_studio_storage`, TASK-3932); phase-2 required version switch (TASK-3952).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py` | MODIFY | LedgerState, read_ledger, apply_studio_migrations, main |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | [project.scripts] parrot-studio-migrate |
| `packages/ai-parrot-server/tests/studio/storage/conftest.py` | CREATE | studio_pool, _truncate_studio_tables, real_request, no_subprocess |
| `packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py` | CREATE | real-Postgres migration, probe, constraint and trigger tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.migrate import (STUDIO_MIN_SERVER_VERSION_NUM, STUDIO_SCHEMA_REQUIRED,
    LEDGER_MARKER, list_migrations, stamp_migrations, StudioMigration)              # TASK-3924
from parrot.handlers.studio.storage.repositories import studio_transaction, _exec, _fetch_all  # TASK-3925
from asyncdb import AsyncPool                                                       # spec §4 fixture
from navigator_session.data import SessionData                                      # tests/handlers/test_ui_surfaces_scope.py:18
from aiohttp.test_utils import make_mocked_request                                  # tests/studio/test_catalogs.py:17
```

### Existing Signatures to Use
```toml
# packages/ai-parrot-server/pyproject.toml
[project.scripts]                                         # line 87 (occurrences: 1)
parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"   # line 88
```
Precedent for the DSN-gated skip: `tests/stores/test_multimodal_pgvector_integration.py:39`
(`TEST_DSN = os.getenv("TEST_PGVECTOR_DSN")`).

### Does NOT Exist
- ~~`parrot-studio-migrate`~~ console script — created here.
- ~~`BotManager.setup()` calling any migration~~ — must never exist.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: exclusive: edits packages/ai-parrot-server/pyproject.toml ([project.scripts]) and creates tests/studio/storage/conftest.py that later storage tests load; extends storage/migrate.py after TASK-3924 (list_migrations, constants); imports studio_transaction/_exec from TASK-3925 (storage/repositories.py)
- Cross-feature ordering: none — STORAGE W0 is in X16's early subset. FieldSync's own runner applies the same files
  raw, one transaction each; `test_host_runner_records_same_checksums` is that contract.
- The parrot runner re-reads the ledger AFTER the body took the advisory lock: that is what makes two concurrent
  runners record each version once (§2.12). Mutation: drop the lock line in a tmp copy ⇒ the 20× loop catches it.
- `test_version_bumps_on_child_write` raw-SQL half (a `psql`-style UPDATE bumps `version`) lives here; the
  repository/service halves live in TASK-3929/15.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. Append the ledger/apply/CLI code to `migrate.py` (block below) — *why*: §3 M1 skeleton fixes these names.
2. Add the console script; write `conftest.py` (spec §4 fixtures, verbatim shape).
3. Write the integration tests; run them against a dedicated PG 14+ database.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py` (MODIFY — append after `stamp_migrations`)
```python
@dataclass(frozen=True)
class LedgerState:
    present: bool
    applied: dict[int, str]
    server_version_num: int

    def complete_for(self, required: int, manifest: Mapping[int, str]) -> bool:
        return self.present and not self.problems(required, manifest)

    def problems(self, required: int, manifest: Mapping[int, str]) -> list[str]:
        # FILL IN: "missing N" for 1..required not applied; "drift N" for checksum != manifest; "unknown N" for a
        #   ledger version absent from the manifest; "server < 14" — bounded by test_migrations_detect_altered_and_missing.
        raise NotImplementedError


async def read_ledger(conn: Any) -> LedgerState:
    """SHOW server_version_num; to_regclass(...); SELECT version, checksum ... Never DDL."""
    # FILL IN: three statements on `conn`; absent ledger ⇒ LedgerState(False, {}, num).
    raise NotImplementedError


async def apply_studio_migrations(pool: Any, *, dry_run: bool = False) -> list[int]:
    """Per pending file: studio_transaction → body (advisory lock first) → re-read ledger → skip if recorded →
    trailer → commit. Returns versions applied. Never called at startup."""
    from .repositories import _exec, studio_transaction   # local: repositories imports models only
    # FILL IN: PG version gate (RuntimeError naming STUDIO_MIN_SERVER_VERSION_NUM); loop list_migrations().
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI: --dsn, --dry-run, --verify, --print, --stamp."""
    # FILL IN: argparse; asyncio.run over an AsyncPool("pg", dsn=...); --verify exit 1 when problems().
    raise NotImplementedError
```
Add `import argparse, asyncio` and `from typing import Any, Mapping` to the module imports.

### `packages/ai-parrot-server/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '\[project.scripts\]' packages/ai-parrot-server/pyproject.toml)
# AFTER — insert below `parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"` (verified: pyproject.toml:88)
parrot-studio-migrate = "parrot.handlers.studio.storage.migrate:main"
```

### `packages/ai-parrot-server/tests/studio/storage/conftest.py` (CREATE)
```python
"""FEAT-621 storage test fixtures (spec §4)."""
import asyncio
import os

import pytest
from aiohttp.test_utils import make_mocked_request
from asyncdb import AsyncPool
from navigator_session.data import SessionData

from parrot.handlers.studio.storage.migrate import apply_studio_migrations

STUDIO_TABLES = ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog")


async def _truncate_studio_tables(pool) -> None:
    # FILL IN: TRUNCATE navigator.<t> CASCADE for STUDIO_TABLES (never the ledger).
    ...


@pytest.fixture
async def studio_pool():
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; Studio storage integration tests need Postgres")
    pool = AsyncPool("pg", dsn=dsn)
    await pool.connect()
    await apply_studio_migrations(pool)
    yield pool
    await _truncate_studio_tables(pool)
    await pool.close()


def real_request(app, method, path, *, user_id="u1", groups=(), superuser=False, match_info=None):
    req = make_mocked_request(method, path, app=app, match_info=match_info or {})
    req["NAV_SESSION"] = SessionData(data={"session": {"user_id": user_id, "groups": list(groups), "superuser": superuser}})
    return req


@pytest.fixture
def no_subprocess(monkeypatch):
    async def _refuse(*a, **k):
        raise AssertionError("a process was started")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse)
```

### `packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py` (CREATE)
```python
"""FEAT-621 M1 — real-Postgres migration tests (AC1, AC2, AC3)."""
# FILL IN one test per row of the Test Specification table; each test that needs an EMPTY database drops the
#   navigator.ai_* tables and the ledger itself first (never the whole schema).
```

### FILL IN checklist
- [ ] `problems`, `read_ledger`, `apply_studio_migrations`, `main`.
- [ ] `_truncate_studio_tables`.
- [ ] The eight integration tests.

---

## Acceptance Criteria

- [ ] 0001–0005 apply twice on an empty DB and on a FEAT-467 DB (catalogue/drafts pre-created with the docstring DDL incl. `uuid_generate_v4()`, with rows); ledger = 5 rows with manifest checksums; second run applies nothing; `--verify` exits 0 (AC1).
- [ ] `--verify`/`problems` report altered checksum, missing version and unknown version 99; exit 1 (AC2).
- [ ] Two concurrent runners (and parrot vs a raw per-file-transaction runner) record each version once (AC2).
- [ ] A generic host runner leaves the same ledger checksums as the manifest (`test_host_runner_records_same_checksums`, AC2).
- [ ] `read_ledger` on a DB without the ledger creates nothing (`test_probe_is_read_only`).
- [ ] Raw-SQL inserts violating X1 constraints are refused (`test_constraints_raw_sql`, AC3); agent delete cascades through the touch trigger; a raw UPDATE bumps `version`.
- [ ] `setup()`/`on_startup` never reach `apply_studio_migrations` (grep gate, AC1).
- [ ] Regression: `pytest packages/ai-parrot-server/tests/studio/storage/test_migration_files.py -q` (from TASK-3924) still green.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_migrations_apply_twice` | AC1 |
| `test_migrations_detect_altered_and_missing` | AC2 |
| `test_migrations_concurrent_runners` | AC2 (mutation: drop advisory lock ⇒ caught by a 20× loop) |
| `test_host_runner_records_same_checksums` | AC2, FieldSync runner contract |
| `test_probe_is_read_only` | §2.2 |
| `test_constraints_raw_sql` | AC3 |
| `test_delete_cascades_with_touch_trigger` | §2.3 triggers |
| `test_version_bumps_on_child_write` (raw-UPDATE half) | §2.6 trigger |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3926 — Migration ledger probe, apply_studio_migrations and parrot-studio-migrate CLI`.
8. Close with `scripts/sdd/close_task.sh TASK-3926 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
