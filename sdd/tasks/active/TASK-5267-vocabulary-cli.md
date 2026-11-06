# TASK-5267: `parrot ontology` CLI group and lazy registration

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5256, TASK-5261, TASK-5262, TASK-5265
**Assigned-to**: unassigned

---

## Context

Spec Module 11 (CLI half). A click group `ontology` with seven subcommands, each a thin
`asyncio.run` wrapper over the Phase 2 modules, registered lazily in `parrot.cli` so `parrot --help`
stays cheap. The `ontology-store` extra was added by TASK-5252; the HTTP routes are TASK-5268.

---

## Scope

- `vocabulary/cli.py` with `@click.group() def ontology()` and subcommands (spec lines 979–985):
  - `init-schema` → `create_ontology_pg_pool` + `ensure_schema`;
  - `register <ontology_id> --base-iri <iri> [--title <text>]` → `PostgresOntologyPublisher.ensure_ontology`;
  - `publish <ontology_id> <turtle_file> [--shapes <file>] [--notes <text>]` → `publish`; prints version,
    changed and diff counts; on `OntologyValidationError` prints every issue and exits 1;
  - `version <ontology_id>` → `PostgresOntologyStore.version`;
  - `export <ontology_id> [--as-of <n>] [--format turtle|jsonld] [-o <file>]` → `export` (stdout when no `-o`);
  - `snapshot <ontology_id> [--version <n>] [--dest <dir>] [--from-turtle <file> --base-iri <iri>]` →
    from PostgreSQL: `load_version` + `build_snapshot`; from Turtle (offline): `parse_turtle` +
    `validate_content` + `materialise_inverses` + `build_closure` + `content_checksum` → `VersionContent(version=--version or 1)` + `build_snapshot`;
  - `publish-catalog --tenant <tenant_id> [--catalog-dsn <dsn>]` → `CatalogVocabularyPublisher.publish_tenant`
    (catalog DSN defaults to `parrot.conf.default_dsn`).
  - Common options on DB commands: `--dsn` (default `ONTOLOGY_PG_DSN`), `--schema` (default `ONTOLOGY_PG_SCHEMA`).
  - Output via `click.echo` (CLI output, not logging — the repo's existing CLIs do the same).
- `parrot/cli/__init__.py`: add `"ontology": "parrot.knowledge.ontology.vocabulary.cli",` to
  `_lazy_commands` and `"ontology": "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]",`
  to `_lazy_extras`.
- `test_vocabulary_cli.py`.

**NOT in scope**: HTTP routes (TASK-5268); pyproject (TASK-5252).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/cli.py` | CREATE | click group |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | lazy command + extra hint |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_cli.py` | CREATE | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click
from parrot.cli import cli                                     # verified: parrot/cli/__init__.py:165
from parrot.conf import default_dsn                            # verified: parrot/conf.py:72
# inside command bodies (lazy):
from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool, ensure_schema   # TASK-5256
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher               # TASK-5260
from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore              # TASK-5261
from parrot.knowledge.ontology.vocabulary.snapshot import build_snapshot                           # TASK-5262
from parrot.knowledge.ontology.vocabulary.catalog_bridge import CatalogVocabularyPublisher         # TASK-5265
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle, validate_content  # TASK-5258/5259
from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses       # TASK-5257
```

### Existing Signatures to Use
```python
# parrot/cli/__init__.py
@click.group(cls=LazyGroup)
def cli(): ...                                                         # :164-165
cli._lazy_commands = {                                                 # :169
    ...
    "wiki": "parrot.knowledge.wiki.cli",                               # :174  (anchor, occurrences: 1)
    ...
}
cli._lazy_extras = {                                                   # :217
    ...
    "jiratoolkit": "ai-parrot-tools: pip install ai-parrot-tools",     # last entry before "}"
}
# LazyGroup.get_command returns getattr(mod, cmd_name.replace("-", "_"))   # :99-100 → the group MUST be named `ontology`
```

### Does NOT Exist
- ~~`parrot ontology`~~ — no such command today.
- ~~a `parrot.knowledge.ontology.cli` module~~ — the module is `parrot.knowledge.ontology.vocabulary.cli`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli"]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `cli.py` group + subcommands (driver imports inside each command) — *why*: `parrot --help` must
   not import asyncpg/rdflib.
2. Register the command and the extra hint in `parrot/cli/__init__.py`.
3. Tests.

### `.../vocabulary/cli.py` (CREATE)
```python
"""`parrot ontology` — publish, export and snapshot ontology vocabularies (FEAT-824)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import click


@click.group()
def ontology() -> None:
    """Ontology vocabulary store: publish, export and snapshot."""


@ontology.command("init-schema")
@click.option("--dsn", default=None, help="asyncpg DSN (default: ONTOLOGY_PG_DSN).")
@click.option("--schema", default=None, help="Schema name (default: ONTOLOGY_PG_SCHEMA or ontology_store).")
def init_schema(dsn: str | None, schema: str | None) -> None:
    """Create the vocabulary schema if missing."""

    async def _run() -> None:
        from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool, ensure_schema

        pool = await create_ontology_pg_pool(dsn, schema=schema)
        try:
            await ensure_schema(pool, schema)
        finally:
            await pool.close()

    asyncio.run(_run())
    click.echo("ontology schema ready")


# FILL IN: register, publish, version, export, snapshot, publish-catalog — same shape as init-schema,
#          options per TASK-5267 Scope; publish prints each ValidationIssue and raises SystemExit(1).
```

### `parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "wiki": "parrot.knowledge.wiki.cli",' parrot/cli/__init__.py)
# AFTER — insert below `    "wiki": "parrot.knowledge.wiki.cli",` (verified: parrot/cli/__init__.py:174)
    "ontology": "parrot.knowledge.ontology.vocabulary.cli",
```
```python
# occurrences: 1 (verified: grep -c '    "jiratoolkit": "ai-parrot-tools: pip install ai-parrot-tools",' parrot/cli/__init__.py)
# AFTER — insert below that line (inside cli._lazy_extras)
    "ontology": "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]",
```

### `.../vocabulary/test_vocabulary_cli.py` (CREATE) — required cases
```python
from click.testing import CliRunner
from parrot.cli import cli

def test_cli_commands_registered(): ...     # `ontology --help` lists the seven subcommands
def test_snapshot_from_turtle_offline(tmp_path, golden_v1, golden_base_iri): ...   # writes v1.sqlite, no DB
async def test_publish_and_version(pg_pool, pg_schema_name, tmp_path, golden_v1): ...  # integration: init-schema, register, publish, version == 1
```
Note: CLI commands call `asyncio.run`, so the integration test must invoke `CliRunner` from a
**sync** test (or `asyncio.to_thread`) — never from inside a running loop.

### FILL IN checklist
- [ ] six remaining subcommands.
- [ ] tests.

---

## Acceptance Criteria

- [ ] `parrot ontology --help` lists `init-schema register publish version export snapshot publish-catalog`.
- [ ] `parrot --help` still imports neither asyncpg nor rdflib.
- [ ] A missing driver shows the `ai-parrot[ontology-store]` hint.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_cli.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm every `Depends-on` task is `done`.
2. Re-run the two `grep -c` anchor checks; mark `in-progress`; implement.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; commit only the listed files.
4. Close with `parrot sdd task close TASK-5267 ontology-backend verified`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `publish-catalog` gains `--catalog-dsn` (default `parrot.conf.default_dsn`)
because the catalog tables and the vocabulary schema may live in different databases.
