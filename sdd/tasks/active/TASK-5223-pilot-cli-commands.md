# TASK-5223: `parrot contracts pilot` CLI (M2)

**Feature**: FEAT-815 — Contracts Pilot Signoff & End-to-End Validation
**Spec**: `sdd/specs/contracts-pilot-signoff-e2e.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5222
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M2 (W1); covers AC2, AC3, AC4.

**Deliberate deviation from spec §3 M2 path**: the spec puts the CLI at `parrot/sdd/scripts/contracts_pilot.py`, but `parrot.sdd.scripts` is the SDD-tooling namespace and the command is `parrot contracts pilot`. Top-level commands register through `cli._lazy_commands` (`parrot/cli/__init__.py`), each pointing at a subsystem-owned `cli` module (e.g. `"wiki": "parrot.knowledge.wiki.cli"`). Follow that pattern: `parrot/knowledge/contracts/cli.py`.

## Scope

- `cli.py`: click group `contracts` → subgroup `pilot` with `run-case`, `record`, `signoff`.
- `run-case --matrix <yaml> --case <id> --dsn <dsn> --tenant <id> [--schema contracts] [--out <json>]`: builds `PostgresContractCatalog` from explicit `--dsn` (or `GRAPHINDEX_PG_DSN`; never a default), runs `catalog.search(case.question)`, prints/writes the hit list as citation refs (`contract_id` + rank) — never card text bodies (AC2, AC10).
- `record --case <id> --disposition <v> --reviewer <name> [--citation ref ...] [--answer-id] [--feedback]`: appends a `CaseDisposition` to a dispositions JSON file (default `sdd/state/FEAT-815/pilot-dispositions.json`), replacing an earlier entry for the same case (AC3).
- `signoff --reviewer <name> --matrix <yaml> [--sign]`: writes `PilotSignoff` to `sdd/state/FEAT-815/pilot-signoff.json`; `--sign` sets `signed_off_at` and is **refused** unless every matrix case has a disposition (AC4).
- Register `"contracts": "parrot.knowledge.contracts.cli"` in `cli._lazy_commands`.
- Round-trip tests using click's `CliRunner` and a fake catalog (no Postgres).

**NOT in scope**: Model changes (TASK-5222), any LLM answer generation, automatic outreach, E2E.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/cli.py` | CREATE | click group `contracts pilot` |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | register lazy `contracts` command |
| `packages/ai-parrot/tests/knowledge/contracts/test_pilot_dispositions.py` | CREATE | AC2–AC4 CLI round-trip |

## Codebase Contract (Anti-Hallucination)

Re-verified on 2026-11-05 against `dev` (post `71ef3ad4c8`).

### Verified Imports

```python
import click
from parrot.knowledge.contracts.pilot import CaseDisposition, CaseMatrix, PilotSignoff  # created by TASK-5222
from parrot.knowledge.contracts.catalog import ContractCatalogStore, SearchHit  # catalog.py:290 (class), :188 (SearchHit)
from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog  # catalog_postgres.py:276
```

### Existing Signatures to Use

| Callable | Signature | Source |
|---|---|---|
| `PostgresContractCatalog.__init__` | `(self, dsn: Optional[str] = None, *, pool=None, tenant_id: str, schema: str = "contracts", principal=None, now=...)` — raises `ValueError` with neither dsn nor pool | `catalog_postgres.py:294` |
| `ContractCatalogStore.search` | `async (self, query: str, top_k: int = 8) -> list[SearchHit]` | `catalog.py:398` |
| `SearchHit` | `card: ContractCard; rank: float = 0.0` | `catalog.py:188` |
| `cli._lazy_commands` | dict name → module path; module must expose a click command named `cli` or matching — CHECK how `LazyGroup.get_command` resolves the attribute (`parrot/cli/__init__.py:83`) | `cli/__init__.py:169` |
| Anchor | `    "wiki": "parrot.knowledge.wiki.cli",` — occurrences: 1 (verified grep -c) | `cli/__init__.py:173` |

### Does NOT Exist

- ~~`parrot.knowledge.contracts.temporal.TemporalDrain`~~ — does not exist; the spec §6 name is wrong. The drain lives on `ContractTemporalPublisher.drain(ctx, *, limit=10) -> TemporalDrainReport` (`temporal.py:156,184`).
- ~~`parrot.knowledge.contracts.datasource.ContractDatasource`~~ — wrong name; the class is `ContractCardDataSource` (`datasource.py:130`).
- ~~`ContractCatalogStore.lookup()` / `.query()`~~ — no such methods; use `search(query, top_k=8) -> list[SearchHit]` (`catalog.py:398`) and `get(contract_id)` (`catalog.py:367`).
- ~~A default Postgres DSN~~ — `PostgresContractCatalog` refuses to build without explicit `dsn` or `pool` (`catalog_postgres.py:294`).
- ~~`parrot.sdd.scripts.contracts_pilot`~~ — not created; see Context deviation.
- ~~A `pool.close()`-free catalog~~ — check whether `PostgresContractCatalog` needs an explicit open/close (grep `async def (open|close|connect)` in catalog_postgres.py) before using it.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/contracts/cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/contracts/test_pilot_dispositions.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py#ContractCatalogStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py#PostgresContractCatalog"
  ]
}
```

## Implementation Notes

- Pydantic v2, strict type hints, Google docstrings, `logging.getLogger(__name__)` — never `print` (CLI output goes through `click.echo`).
- No real contract text anywhere in committed files (spec AC10): evidence is referenced only by `contract_id` / `node_id` / `version_n` / `answer_id`.
- Parallelism: imports PilotCase/CaseMatrix/CaseDisposition/PilotSignoff from TASK-5222 (knowledge/contracts/pilot.py).

## Implementation Blueprint

### Steps (in order)

1. Read `LazyGroup.get_command` (`cli/__init__.py:~83`) to learn which attribute name it loads — name the click group accordingly.
2. Create `cli.py`; keep the Postgres import lazy inside `_search` — because `asyncpg` is optional.
3. Register the lazy command.
4. Tests: `CliRunner` with `monkeypatch` replacing `_search` by a fake returning fixed refs; write to `tmp_path`.

#### `packages/ai-parrot/src/parrot/knowledge/contracts/cli.py` (CREATE)

```python
"""`parrot contracts pilot` — twelve-case pilot acceptance CLI (FEAT-815, W1)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import click

from parrot.knowledge.contracts.pilot import CaseDisposition, CaseMatrix, PilotSignoff

logger = logging.getLogger(__name__)
STATE_DIR = Path("sdd/state/FEAT-815")
DISPOSITIONS = STATE_DIR / "pilot-dispositions.json"
SIGNOFF = STATE_DIR / "pilot-signoff.json"


@click.group()
def cli() -> None:
    """Contracts card operations."""


@cli.group()
def pilot() -> None:
    """Pilot acceptance: run cases, record dispositions, sign off."""


async def _search(dsn: str, tenant: str, schema: str, question: str, top_k: int) -> list[dict]:
    """Run one case question through the catalog; returns citation refs, never card text."""
    from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog  # lazy: asyncpg optional

    catalog = PostgresContractCatalog(dsn, tenant_id=tenant, schema=schema)
    # FILL IN: open/close the catalog per its real lifecycle API (verify first); map each SearchHit to
    #          {"contract_id": hit.card.contract_id, "rank": hit.rank} — bounded by AC2/AC10 (no text bodies).
    ...


@pilot.command("run-case")
@click.option("--matrix", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--case", "case_id", required=True)
@click.option("--dsn", default=lambda: os.environ.get("GRAPHINDEX_PG_DSN"), help="Explicit DSN; no default.")
@click.option("--tenant", required=True)
@click.option("--schema", default="contracts")
@click.option("--top-k", default=8, show_default=True)
@click.option("--out", type=click.Path(path_type=Path))
def run_case(matrix: Path, case_id: str, dsn: str | None, tenant: str, schema: str, top_k: int, out: Path | None) -> None:
    """Execute one case against the catalog and print its citation refs (AC2)."""
    if not dsn:
        raise click.UsageError("--dsn or GRAPHINDEX_PG_DSN is required; there is no default DSN.")
    # FILL IN: find the case (UsageError if unknown), asyncio.run(_search(...)), echo JSON, write --out if given.


@pilot.command("record")
# FILL IN: options per Scope; --disposition is click.Choice(["pass","fail","skip","handoff"]).
def record(**kwargs) -> None:
    """Record (or replace) one reviewer disposition (AC3)."""
    # FILL IN: load existing list from DISPOSITIONS (or --file), replace same case_id, reviewed_at=now(UTC),
    #          validate via CaseDisposition, write back with indent=2.


@pilot.command("signoff")
# FILL IN: --reviewer, --matrix, --sign flag, --notes, --dispositions/--out path overrides.
def signoff(**kwargs) -> None:
    """Write the signoff artifact; --sign is refused until all twelve cases are dispositioned (AC4)."""
    # FILL IN: build PilotSignoff; if --sign and a matrix case lacks a disposition -> click.ClickException
    #          listing the missing case ids; never write signed_off_at otherwise.
```

**Why**: the DSN has no default because the FEAT-539 conftest and `PostgresContractCatalog` both refuse an implicit DSN — the CLI must not reintroduce one. Path overrides on every command exist so the tests write into `tmp_path`, never the real `sdd/state/`.

#### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)

```python
# AFTER — insert below `    "wiki": "parrot.knowledge.wiki.cli",` (verified: cli/__init__.py:173)
# occurrences: 1 (verified: grep -c '"wiki": "parrot.knowledge.wiki.cli"' packages/ai-parrot/src/parrot/cli/__init__.py)
    # FEAT-815 — contracts pilot acceptance CLI.
    "contracts": "parrot.knowledge.contracts.cli",
```

**Why**: lazy registration keeps `parrot --help` from importing asyncpg.


### FILL IN checklist

- [ ] `_search` lifecycle + hit mapping
- [ ] `run-case` body
- [ ] `record` options + body
- [ ] `signoff` options + refusal logic
- [ ] Tests

## Acceptance Criteria

- [ ] `run-case` without DSN fails with a usage error; with a (faked) catalog prints `contract_id`+rank refs only (AC2).
- [ ] `record` writes/replaces a disposition with reviewer + UTC timestamp (AC3).
- [ ] `signoff --sign` refuses while any of the 12 cases lacks a disposition; succeeds and writes `pilot-signoff.json` once all 12 exist (AC4).
- [ ] `parrot contracts pilot --help` lists the three commands.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/contracts/test_pilot_dispositions.py -q`

## Test Specification

| Test | Verifies |
|---|---|
| `test_run_case_requires_dsn` | no DSN fallback |
| `test_run_case_emits_reference_only_citations` | AC2, AC10 |
| `test_record_replaces_same_case` | AC3 |
| `test_signoff_refused_until_all_cases_recorded` | AC4 |
| `test_signoff_writes_artifact_when_complete` | AC4 |

## Agent Instructions

1. Read the spec and this task; confirm every `Depends-on` task is `done` in `sdd/tasks/index/contracts-pilot-signoff-e2e.json`.
2. Work in the feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`; verify each Codebase Contract entry before writing code.
3. Implement only the files listed above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Close with `parrot sdd task close TASK-5223 contracts-pilot-signoff-e2e verified` and fill in the Completion Note.

## Completion Note

*(Agent fills this in when done)*
