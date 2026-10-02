# TASK-3924: Studio migration files 0001–0005, MANIFEST and body checksum

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W0 — Studio migrations + runner (M1, part 1: files, checksum, manifest)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.3 (final executable DDL), §2.12 (file format, checksum bytes, manifest), §3 Module 1. Decision 6: no DDL at
startup — versioned SQL files shipped as package data, applied by the host. This task ships the five v1 files, the
manifest, and the pure (DB-free) half of `storage/migrate.py`: split/checksum/list/stamp. The DB half (ledger probe,
apply, CLI) is TASK-3926.

---

## Scope

- Create `migrations/0001_studio_migrations_ledger.sql` … `0005_studio_drafts_baseline.sql` with the bodies of
  spec §2.3 **verbatim** (each starts with `SELECT pg_advisory_xact_lock(4715391001);`), each followed by exactly one
  ledger trailer (`-- @studio-ledger` + the single `INSERT … ON CONFLICT (version) DO NOTHING;`).
- Create `migrations/MANIFEST.json` = `{"required": 5, "required_phase2": 8, "migrations": [...]}`.
- Create `storage/migrate.py` with the constants, `StudioMigration`, `split_body`, `body_checksum`,
  `list_migrations` and `stamp_migrations` (rewrites trailer hex + manifest from bodies — release tooling).
- Generate the real trailer hexes and manifest entries by running `stamp_migrations` once; commit the result.
- Add package-data `"parrot.handlers.studio.storage.migrations" = ["*.sql", "MANIFEST.json"]` to pyproject.
- Tests `test_checksum_body_split`, `test_migration_files_match_manifest` (the CI gate).

**NOT in scope**: `read_ledger`, `apply_studio_migrations`, `main` CLI and the console script (TASK-3926); 0006–0008 (phase 2: TASK-3952/32/33); the storage package marker (TASK-3922).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/__init__.py` | CREATE | empty package marker so setuptools package-data and importlib.resources address it |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0001_studio_migrations_ledger.sql` | CREATE | ledger table (§2.3) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0002_ai_agents.sql` | CREATE | ai_agents, ai_agent_assets, ai_agent_tooling, triggers (§2.3) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0003_ai_agent_drafts.sql` | CREATE | ai_agent_drafts + bump trigger (§2.3) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0004_ai_skills_catalog_tenancy.sql` | CREATE | baseline + in-place tenancy of ai_skills_catalog (§2.3) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0005_studio_drafts_baseline.sql` | CREATE | legacy studio_drafts baseline (§2.3) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json` | CREATE | required / required_phase2 / per-version sha256 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py` | CREATE | constants, StudioMigration, split_body, body_checksum, list_migrations, stamp_migrations |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | package-data entry for the migrations package |
| `packages/ai-parrot-server/tests/studio/storage/test_migration_files.py` | CREATE | checksum split + manifest CI gate |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
import hashlib, json                                   # stdlib
from importlib import resources                        # stdlib — read package data
from dataclasses import dataclass                      # stdlib
```

### Existing Signatures to Use
```toml
# packages/ai-parrot-server/pyproject.toml
[tool.setuptools.package-data]                         # line 109
"parrot.handlers" = ["*.sql"]                          # line 110
"parrot.handlers.models" = ["*.sql"]                   # line 111  ← anchor (occurrences: 1)
```
Spec §2.3 holds the five complete bodies (copy byte for byte, LF endings, UTF-8, no BOM, no BEGIN/COMMIT).

### Does NOT Exist
- ~~A migration runner in ai-parrot-server~~ — none; `packages/parrot-formdesigner/migrations/` is a precedent for
  numbered SQL only (not package data, not reusable).
- ~~`navigator.ai_studio_migrations`, `ai_agents`, `ai_agent_assets`, `ai_agent_tooling`, `ai_agent_drafts`~~ — no
  code references them today.
- ~~`CREATE TABLE` code for `studio_drafts` / `ai_skills_catalog`~~ — only model docstrings
  (`handlers/models/studio_drafts.py`, `handlers/models/skills_catalog.py`).
- The `parrot.handlers.studio.storage` package marker and the `tests/studio/storage` test-package marker are owned by
  TASK-3922; until it merges both directories import as implicit namespace packages, which is enough here
  (test module names in this feature are unique).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0001_studio_migrations_ledger.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0002_ai_agents.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0003_ai_agent_drafts.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0004_ai_skills_catalog_tenancy.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0005_studio_drafts_baseline.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_migration_files.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: exclusive: edits the dependency manifest packages/ai-parrot-server/pyproject.toml (package-data); no dependency (the storage directory imports as an implicit namespace package until TASK-3922's package marker merges); first writer of storage/migrate.py and MANIFEST.json (TASK-3926, -31, -32, -33 serialize after it)
- Cross-feature ordering: none — X16 lists STORAGE W0 in the early, sibling-independent subset (with FEAT-605 W0.1–W0.3/W1.1–W1.5 and TOOLKITS Wave 1).
- The ledger INSERT in each trailer carries the body's own sha256: run `stamp_migrations()` after writing the bodies,
  never hand-type a hex. The trailer is NOT hashed (§2.12), so stamping is not self-referential.
- `--stamp` as a CLI flag is wired in TASK-3926 (`main`); here it is the function only.
- Keep `migrate.py` under 500 lines across both tasks; this half should be ~150.

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
1. Write the five SQL bodies from spec §2.3 verbatim — *why*: the spec text is the reviewed, final DDL (R9).
2. Append to each a placeholder trailer (`-- @studio-ledger` + INSERT with 64 `0`s) — *why*: `stamp_migrations` rewrites it.
3. Write `migrate.py` (block below) and `MANIFEST.json` with zeroed hashes.
4. Run `python -c "from parrot.handlers.studio.storage.migrate import stamp_migrations; stamp_migrations()"` —
   *why*: produces the real trailer hexes and manifest; commit the rewritten files.
5. Add the package-data line; write the tests; run the Validation Commands.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py` (CREATE)
```python
"""Studio schema migrations: file format, checksum and listing (spec §2.12). Never imported at startup."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

STUDIO_SCHEMA_REQUIRED: int = 5
STUDIO_SCHEMA_REQUIRED_PHASE2: int = 8
STUDIO_MIGRATION_LOCK_KEY: int = 4715391001
STUDIO_MIN_SERVER_VERSION_NUM: int = 140000
LEDGER_MARKER: str = "-- @studio-ledger"
MIGRATIONS_PACKAGE: str = "parrot.handlers.studio.storage.migrations"


@dataclass(frozen=True)
class StudioMigration:
    version: int
    name: str
    body: bytes
    trailer: bytes
    checksum: str


def split_body(raw: bytes) -> tuple[bytes, bytes]:
    """Body = bytes up to and incl. the LF before the marker line; raise ValueError when absent or repeated."""
    # FILL IN: find b"\n" + LEDGER_MARKER.encode() + b"\n" (or marker at file start ⇒ error); count occurrences of
    #   the marker LINE; != 1 ⇒ ValueError — bounded by test_checksum_body_split.
    raise NotImplementedError


def body_checksum(raw: bytes) -> str:
    return hashlib.sha256(split_body(raw)[0]).hexdigest()


def _parse_name(filename: str) -> tuple[int, str]:
    """'0002_ai_agents.sql' -> (2, '0002_ai_agents')."""
    stem = filename.removesuffix(".sql")
    return int(stem.split("_", 1)[0]), stem


def list_migrations() -> list[StudioMigration]:
    """Package data via importlib.resources, sorted; validated against MANIFEST.json (contiguous, hashes)."""
    # FILL IN: iterate resources.files(MIGRATIONS_PACKAGE) for *.sql; build StudioMigration; load MANIFEST.json;
    #   raise ValueError on a gap, a version absent from the manifest, or checksum != manifest sha256.
    raise NotImplementedError


def stamp_migrations(directory: Path | None = None) -> None:
    """Release tooling: rewrite every trailer hex and MANIFEST.json from the bodies (repository only)."""
    # FILL IN: for each file rewrite the trailer INSERT's checksum literal; rewrite MANIFEST.json keeping
    #   "required" and "required_phase2" — bounded by §2.12 (trailer = marker line + one INSERT).
    raise NotImplementedError
```
**Why this shape**: constants and names are fixed by the §3 M1 skeleton (TASK-3926 and the probe import them).
`stamp_migrations` takes an optional directory so tests can stamp a tmp copy.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0002_ai_agents.sql` (CREATE) — pattern for all five
```sql
SELECT pg_advisory_xact_lock(4715391001);   -- STUDIO_MIGRATION_LOCK_KEY
-- FILL IN: the rest of the §2.3 body for this file, verbatim
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (2, '0002_ai_agents', '<written by stamp_migrations>')
ON CONFLICT (version) DO NOTHING;
```
**Why**: 0001 creates the ledger in its own body, so its trailer INSERT works on a fresh database.

### `packages/ai-parrot-server/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"parrot.handlers.models" = \["\*.sql"\]' packages/ai-parrot-server/pyproject.toml)
# AFTER — insert below `"parrot.handlers.models" = ["*.sql"]` (verified: pyproject.toml:111)
"parrot.handlers.studio.storage.migrations" = ["*.sql", "MANIFEST.json"]
```

### `packages/ai-parrot-server/tests/studio/storage/test_migration_files.py` (CREATE)
```python
"""FEAT-621 M1 — migration file format and manifest (AC1, AC2; CI gate)."""
import pytest

from parrot.handlers.studio.storage.migrate import (
    LEDGER_MARKER, STUDIO_SCHEMA_REQUIRED, body_checksum, list_migrations, split_body,
)


def test_checksum_body_split() -> None:
    raw = b"SELECT 1;\n" + LEDGER_MARKER.encode() + b"\nINSERT ... '00';\n"
    body, trailer = split_body(raw)
    assert body == b"SELECT 1;\n"
    # FILL IN: editing trailer hex keeps checksum; editing one body byte changes it;
    #   missing marker and repeated marker raise ValueError.


def test_migration_files_match_manifest() -> None:
    migs = list_migrations()
    assert [m.version for m in migs] == list(range(1, len(migs) + 1))
    assert len(migs) >= STUDIO_SCHEMA_REQUIRED
    # FILL IN: for each file: body hash == hex in its trailer == manifest sha256; every body's first statement is
    #   the advisory lock — mutation: change one body byte without restamping ⇒ RED.
```

### FILL IN checklist
- [ ] `split_body` marker detection (line-anchored, exactly once).
- [ ] `list_migrations` manifest validation.
- [ ] `stamp_migrations` trailer rewrite.
- [ ] Five bodies copied verbatim from §2.3; trailers stamped.

---

## Acceptance Criteria

- [ ] Five migration files exist with spec §2.3 bodies verbatim; each body's first statement is `SELECT pg_advisory_xact_lock(4715391001);` (AC1).
- [ ] Body checksum excludes the trailer; trailer hex == body sha256 == MANIFEST.json entry for every version; versions contiguous; `required` = 5 covered (AC2, `test_migration_files_match_manifest`).
- [ ] Migrations ship as package data (`importlib.resources` finds them from an installed wheel).
- [ ] No CREATE/ALTER outside `storage/migrations/*.sql` and `migrate.py` (AC1 grep gate).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_migration_files.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_checksum_body_split` | §2.12 checksum bytes, AC2 |
| `test_migration_files_match_manifest` | AC2 (CI gate) |

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
   `feat(agentstudio-db-storage): TASK-3924 — Studio migration files 0001–0005, MANIFEST and body checksum`.
8. Close with `scripts/sdd/close_task.sh TASK-3924 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5)
**Date**: 2026-09-30
**Notes**: Five bodies extracted programmatically from spec §2.3 (the '-- NNNN_name.sql' header comment line dropped; first statement is the lock, preceded only by comments in 0004/0005). Stamped via stamp_migrations; 3 tests pass.

**Deviations from spec**: none
